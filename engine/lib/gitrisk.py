"""Git-history bug mining.

History is the cheapest oracle for where bugs hide: files that were fixed often
stay buggy, files that always change together but didn't this time signal a
forgotten edit. Pure stdlib over `git log`.

Signals:
  - bugfix density   : commits whose message looks like a bug fix touching a file
  - churn            : commit count + lines changed, recency-weighted
  - author spread    : distinct authors (bus-factor / coordination defects)
  - recency          : exponential decay so recent activity dominates
  - co-change coupling (logical coupling, Zimmermann et al.): if dirty file A
    historically co-changes with B at high confidence but B is clean now, B is a
    likely missing change -> a hidden bug the compiler cannot see.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

try:
    from . import common
except ImportError:  # standalone: `python3 lib/gitrisk.py`
    import common

BUGFIX_RE = re.compile(
    r"\b(fix(e[sd])?|bug|defect|patch|hotfix|regress(ion)?|revert|crash|leak|"
    r"race|deadlock|npe|nullpointer|segfault|overflow|corrupt|broken|wrong|"
    r"incorrect|fault|fail(ure|ed|ing)?|issue|err(or)?|oops|typo)\b",
    re.IGNORECASE,
)

HALF_LIFE_DAYS = 90.0  # recency weight halves every 90 days


def _decay(age_days: float) -> float:
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def mine(
    repo: Path,
    *,
    max_commits: int = 1500,
    since: str | None = None,
    max_files_per_commit: int = 30,
) -> dict:
    """Single-pass `git log --numstat` mine. Returns per-file metrics + coupling."""
    if not common.git_ok(repo) or not common.have("git"):
        return {"ok": False, "reason": "no git", "files": {}, "coupling": {}}

    cmd = [
        "git",
        "-C",
        str(repo),
        "log",
        "--no-merges",
        f"--max-count={max_commits}",
        "--date=unix",
        "--pretty=format:\x01%H\x09%an\x09%at\x09%s",
        "--numstat",
    ]
    if since:
        cmd.insert(5, f"--since={since}")
    try:
        cp = common.run(cmd, timeout=60)
    except (OSError, ValueError) as e:  # git absent / args issue — degrade, never crash
        return {"ok": False, "reason": str(e)[:120], "files": {}, "coupling": {}}
    if cp.returncode != 0:
        return {"ok": False, "reason": cp.stderr[-200:], "files": {}, "coupling": {}}

    now = time.time()
    files: dict[str, dict] = {}
    cochange: dict[str, Counter] = defaultdict(Counter)
    commit_ts = now
    commit_is_bug = False
    commit_author = ""
    commit_files: list[str] = []

    def flush():
        if not commit_files:
            return
        # co-change only for human-sized commits (skip mass refactors/vendoring)
        if 2 <= len(commit_files) <= max_files_per_commit:
            for i, a in enumerate(commit_files):
                for b in commit_files[i + 1 :]:
                    cochange[a][b] += 1
                    cochange[b][a] += 1

    for line in cp.stdout.splitlines():
        if line.startswith("\x01"):
            flush()
            parts = line[1:].split("\t")
            if len(parts) >= 4:
                try:
                    commit_ts = float(parts[2])
                except ValueError:
                    commit_ts = now
                commit_author = parts[1]
                commit_is_bug = bool(BUGFIX_RE.search(parts[3]))
            commit_files = []
            continue
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) != 3:
            continue
        added, deleted, path = cols
        if " => " in path:  # renames: `a/{b => c}/d` or plain `old => new`
            if "{" in path:
                path = re.sub(r"\{[^}]*=> ([^}]*)\}", r"\1", path).replace("//", "/")
            else:
                path = path.split(" => ", 1)[1]
        if common.is_skipped(Path(path).parts):
            continue
        f = files.setdefault(
            path,
            {
                "commits": 0,
                "bugfix_commits": 0,
                "churn": 0,
                "recency_weight": 0.0,
                "bugfix_weight": 0.0,
                "authors": set(),
                "last_ts": 0.0,
            },
        )
        age = max(0.0, (now - commit_ts) / 86400.0)
        w = _decay(age)
        f["commits"] += 1
        f["churn"] += (int(added) if added.isdigit() else 0) + (
            int(deleted) if deleted.isdigit() else 0
        )
        f["authors"].add(commit_author)
        f["last_ts"] = max(f["last_ts"], commit_ts)
        f["recency_weight"] += w
        if commit_is_bug:
            f["bugfix_commits"] += 1
            f["bugfix_weight"] += w
        commit_files.append(path)
    flush()

    for f in files.values():
        f["authors"] = len(f["authors"])

    return {
        "ok": True,
        "files": files,
        "coupling": cochange,
        "scanned_commits": min(max_commits, cp.stdout.count("\x01")),
    }


def risk_scores(mined: dict) -> dict[str, float]:
    """Composite per-file history risk in [0, 100]. Higher = historically buggier."""
    files = mined.get("files", {})
    if not files:
        return {}
    max_bug = max((f["bugfix_weight"] for f in files.values()), default=0.0) or 1.0
    max_churn = max((f["churn"] for f in files.values()), default=0) or 1
    max_rec = max((f["recency_weight"] for f in files.values()), default=0.0) or 1.0
    out = {}
    for path, f in files.items():
        bug = f["bugfix_weight"] / max_bug
        churn = math.log1p(f["churn"]) / math.log1p(max_churn)
        rec = f["recency_weight"] / max_rec
        authors = min(f["authors"], 8) / 8.0
        # bugfix history is the strongest defect predictor -> weight it highest
        score = 100.0 * (0.45 * bug + 0.25 * churn + 0.15 * rec + 0.15 * authors)
        out[path] = round(score, 1)
    return out


def missing_cochange(
    mined: dict,
    changed: list[str],
    *,
    min_support: int = 3,
    min_confidence: float = 0.55,
    limit: int = 25,
) -> list[dict]:
    """Files that historically co-change with a dirty file but are clean now.

    confidence(A->B) = co(A,B) / commits(A). High confidence + clean B = likely
    forgotten edit. This catches the bug class compilers and linters cannot: a
    half-applied change.
    """
    files = mined.get("files", {})
    coupling = mined.get("coupling", {})
    changed_set = set(changed)
    suspects: dict[str, dict] = {}
    for a in changed:
        commits_a = files.get(a, {}).get("commits", 0)
        if commits_a < min_support:
            continue
        for b, co in coupling.get(a, {}).items():
            if b in changed_set or co < min_support:
                continue
            conf = co / commits_a
            if conf < min_confidence:
                continue
            cur = suspects.get(b)
            if cur is None or conf > cur["confidence"]:
                suspects[b] = {
                    "path": b,
                    "partner": a,
                    "co_changes": co,
                    "confidence": round(conf, 2),
                    "partner_commits": commits_a,
                }
    rows = sorted(
        suspects.values(),
        key=lambda r: (r["confidence"], r["co_changes"]),
        reverse=True,
    )
    return rows[:limit]


if __name__ == "__main__":
    import json
    import sys

    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    m = mine(repo, max_commits=800)
    scores = risk_scores(m)
    top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:15]
    print(
        json.dumps(
            {"ok": m["ok"], "files_tracked": len(m["files"]), "top_risky": top},
            indent=2,
        )
    )
