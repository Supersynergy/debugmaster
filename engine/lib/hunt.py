"""hunt — the flagship: find the smallest, best-hidden bugs, ranked by impact.

Pipeline (each stage degrades gracefully):
  1. dirty set        : git porcelain (what the user is touching now)
  2. static engine    : bughunt regex + Python-AST hidden-bug rules
  3. tool fusion      : ruff/bandit/semgrep/gitleaks/... normalized + deduped
  4. history mine     : gitrisk bugfix-density + logical co-change suspects
  5. metrics          : complexity/nesting/size proxies
  6. risk model       : per-file P(bug) blend (+ optional IsolationForest)
  7. learn            : re-rank findings by per-rule learned precision; persist
  8. rank             : severity x precision x file-risk x blast-radius x dirty

Output: ranked suspects with file:line, evidence, fix, and a verify command;
plus co-change "forgotten edit" suspects the static engine cannot see; written
as md + json + ai-brief.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

try:
    from . import (
        bizlogic,
        bughunt,
        common,
        fusion,
        gitrisk,
        learn,
        metrics,
        reach,
        riskmodel,
        suppress,
    )
except ImportError:
    import bizlogic
    import bughunt
    import common
    import fusion
    import gitrisk
    import learn
    import metrics
    import reach
    import riskmodel
    import suppress

VERIFY = {
    "python": "python3 -m py_compile {file} && ruff check {file}",
    "rust": "cargo check && cargo clippy",
    "go": "go vet ./... && go build ./...",
    "typescript": "npx tsc --noEmit",
    "javascript": "node --check {file}",
    "shell": "shellcheck {file}",
}


def git_changed(repo: Path) -> list[str]:
    if not common.git_ok(repo):
        return []
    cp = common.run(["git", "-C", str(repo), "status", "--porcelain=v1", "-uall"])
    out = []
    for line in cp.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if not common.is_skipped(Path(path).parts):
            out.append(path.strip())
    return out


def verify_cmd(file: str) -> str:
    import shlex

    lang = common.lang_of(file)
    return VERIFY.get(lang, "re-run debugmaster hunt on this file").replace(
        "{file}", shlex.quote(file)
    )


def hunt(
    repo: Path,
    *,
    profile: str = "fast",
    fuse: bool = True,
    limit: int = 25,
    dirty_only: bool = False,
    scan_limit: int = 6000,
    timeout: int = 90,
    record: bool = True,
    use_cache: bool = True,
) -> dict:
    repo = Path(repo).resolve()
    t0 = time.time()
    changed = git_changed(repo)
    changed_set = set(changed)

    # HEAD cache: a clean tree at the same HEAD+profile cannot have changed, so
    # skip the whole pass and return the prior report (huge win on repeated CI runs).
    cache_key = _cache_key(repo, profile, fuse)
    if use_cache and not changed and cache_key:
        cached = _cache_load(repo, cache_key)
        if cached:
            cached["cached"] = True
            cached["elapsed_s"] = 0.0
            return cached

    # 2. static + business-logic engines in ONE pass: walk the tree once, read each
    #    file once, parse each Python file once, and run both engines on the shared
    #    AST. Two separate scan_repo() calls re-walked, re-read and re-parsed every
    #    file — this halves I/O and AST cost while keeping peak memory flat.
    only = changed_set if (dirty_only and changed_set) else None
    static = _combined_static(repo, only, scan_limit)
    # 2c. test-gap: changed source with no covering test (a bug no linter sees)
    static += reach.test_gaps(repo, changed) if changed else []

    # 3. tool fusion
    fused, scanners = [], []
    if fuse:
        fr = fusion.run(repo, profile=profile, timeout=timeout)
        fused, scanners = fr["findings"], fr["scanners"]

    all_findings = fusion.dedupe(static + fused)

    # 3b. suppression: drop accepted/known findings (.debugmaster-ignore + inline
    #     markers) so signal stays high. The count is reported, never hidden.
    all_findings, suppressed = suppress.filter_findings(repo, all_findings)

    # 4. history
    mined = gitrisk.mine(repo, max_commits=1500)
    hist = gitrisk.risk_scores(mined)
    cochange = gitrisk.missing_cochange(mined, changed) if changed else []

    # 7. learned precision
    rule_ids = {f.rule_id for f in all_findings}
    pmap = learn.precision_map(repo, rule_ids) if rule_ids else {}

    # 6. signals -> file risk. Only score candidate files (have findings / dirty /
    #    historically risky) so blast-radius stays cheap.
    fw = riskmodel.finding_weight(all_findings, pmap)
    candidates = (
        set(fw) | changed_set | set(sorted(hist, key=hist.get, reverse=True)[:50])
    )
    # metrics only for the files we actually score — not the whole repo (big win on
    # large monorepos where most files never become candidates).
    mtr = metrics.metrics_for(repo, candidates)
    fan = reach.fan_in(repo, list(candidates)) if candidates else {}
    signals = {}
    for f in candidates:
        signals[f] = {
            "history": hist.get(f, 0.0),
            "structure": mtr.get(f, {}).get("risk_proxy", 0.0),
            "finding_weight": fw.get(f, 0.0),
            "dirty": f in changed_set,
            "fan_in": fan.get(f, 0),
        }
    file_risk = riskmodel.score_files(signals)

    # 8. rank each finding
    ranked = []
    for f in all_findings:
        sev = common.SEVERITY_RANK.get(f.severity, 2)
        prec = pmap.get(f.rule_id, 0.6)
        fr_score = file_risk.get(f.file, {}).get("score", 0.0) / 100.0
        dirty_boost = 0.5 if f.file in changed_set else 0.0
        priority = sev * prec * (1.0 + 0.6 * fr_score + dirty_boost)
        d = f.as_dict()
        d["priority"] = round(priority, 2)
        d["precision"] = round(prec, 2)
        d["file_risk"] = round(file_risk.get(f.file, {}).get("score", 0.0), 1)
        d["dirty"] = f.file in changed_set
        d["verify"] = verify_cmd(f.file)
        ranked.append(d)
    ranked.sort(key=lambda d: d["priority"], reverse=True)

    # risky files (for "where to look even without a concrete finding")
    risky = sorted(file_risk.items(), key=lambda kv: kv[1]["score"], reverse=True)
    risky_rows = [{"file": f, **v} for f, v in risky[:15] if v["score"] > 0]

    if record and all_findings:
        try:
            learn.record(repo, all_findings)
        except Exception:
            pass

    sev_counts = {}
    for f in all_findings:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1

    verdict = _verdict(all_findings, cochange)
    report = {
        "repo": str(repo),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed_s": round(time.time() - t0, 1),
        "verdict": verdict,
        "profile": profile,
        "cached": False,
        "dirty_files": len(changed),
        "totals": {
            "findings": len(all_findings),
            "by_severity": sev_counts,
            "cochange_suspects": len(cochange),
            "files_scored": len(file_risk),
            "suppressed": suppressed,
        },
        "scanners": scanners,
        "top_suspects": ranked[:limit],
        "cochange_suspects": cochange[:12],
        "risky_files": risky_rows,
        "history_ok": mined.get("ok", False),
    }
    if use_cache and not changed and cache_key:
        _cache_save(repo, cache_key, report)
    return report


def _scan_one(repo: Path, relp: str, lang: str) -> list:
    """Scan a single file with both engines, sharing one read + one AST parse."""
    text = common.read_text(repo / relp)
    if not text:
        return []
    lines = text.splitlines()
    path = repo / relp
    out = bughunt._scan_lines(repo, path, lang, lines)
    out += bizlogic._scan_regex(repo, path, lang, lines)
    if lang == "python":
        tree = common.parse_python(text)
        out += bughunt._scan_python_ast(repo, path, text, lines, tree=tree)
        out += bizlogic._scan_python(repo, path, text, lines, tree=tree)
    return out


def _scan_chunk(args) -> list:
    """Process-pool worker: scan a batch of files. Module-level so it is picklable."""
    repo_str, items = args
    repo = Path(repo_str)
    out = []
    for relp, lang in items:
        out += _scan_one(repo, relp, lang)
    return out


_PARALLEL_MIN_FILES = 200  # below this, pool spawn overhead outweighs the speedup


def _combined_static(repo: Path, only: set[str] | None, scan_limit: int) -> list:
    """Run bughunt + bizlogic over the repo in a single file walk.

    Per file: read once, line-scan with both engines, and for Python parse once and
    hand the same tree to both AST visitors. The scan is CPU-bound (AST walking), so
    on a large repo it is fanned out across a process pool sized to ~75% of cores
    (`common.worker_count`) — the GIL makes threads useless here, and capping below
    100% leaves the machine responsive. Output is identical to the serial path."""
    files = []
    for path, lang in common.iter_source_files(repo, limit=scan_limit):
        relp = common.rel(repo, path)
        if only is not None and relp not in only:
            continue
        files.append((relp, lang))

    workers = common.worker_count()
    if workers > 1 and len(files) >= _PARALLEL_MIN_FILES:
        try:
            return _scan_parallel(repo, files, workers)
        except Exception:
            pass  # fork unavailable / pickling issue -> deterministic serial fallback
    out = []
    for relp, lang in files:
        out += _scan_one(repo, relp, lang)
    return out


def _scan_parallel(repo: Path, files: list, workers: int) -> list:
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    nchunks = workers * 4  # several batches per worker => load-balanced, low IPC
    size = max(1, (len(files) + nchunks - 1) // nchunks)
    chunks = [(str(repo), files[i : i + size]) for i in range(0, len(files), size)]
    ctx = mp.get_context("fork")  # fork: workers inherit imports, no re-exec of bin/
    out = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
        for part in ex.map(_scan_chunk, chunks):
            out.extend(part)
    return out


HUNT_VERSION = "6"  # bumped: parallel static scan (process pool, ~75% cores)


def _rules_hash() -> str:
    """Fingerprint the active rule set so changing rules busts stale caches."""
    import hashlib

    ids = ",".join(sorted(r.id for r in bughunt.RULES))
    ids += "|biz:" + ",".join(sorted(r[0] for r in bizlogic.REGEX_RULES))
    return hashlib.sha1((HUNT_VERSION + "|" + ids).encode()).hexdigest()[:10]


def _cache_key(repo: Path, profile: str, fuse: bool) -> str | None:
    if not common.git_ok(repo) or not common.have("git"):
        return None
    cp = common.run(["git", "-C", str(repo), "rev-parse", "HEAD"])
    head = cp.stdout.strip()
    if cp.returncode != 0 or not head:
        return None
    return f"{head}:{profile}:{int(fuse)}:{_rules_hash()}"


def _cache_load(repo: Path, key: str) -> dict | None:
    f = repo / ".debugmaster" / "hunt-cache.json"
    if not f.exists():
        return None
    try:
        blob = json.loads(f.read_text())
        return blob["report"] if blob.get("key") == key else None
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def _cache_save(repo: Path, key: str, report: dict) -> None:
    try:
        d = repo / ".debugmaster"
        d.mkdir(parents=True, exist_ok=True)
        (d / "hunt-cache.json").write_text(json.dumps({"key": key, "report": report}))
    except OSError:
        pass


def _verdict(findings, cochange) -> str:
    if any(f.severity == "critical" for f in findings):
        return "CRITICAL"
    if any(f.severity == "high" for f in findings):
        return "FAIL"
    if findings or cochange:
        return "WARN"
    return "CLEAN"


def markdown(rep: dict) -> str:
    L = [
        f"# Debugmaster Hunt — {rep['repo']}",
        "",
        f"Verdict: **{rep['verdict']}** · profile `{rep['profile']}` · {rep['elapsed_s']}s · "
        f"dirty {rep['dirty_files']}",
        f"Findings: **{rep['totals']['findings']}** {rep['totals']['by_severity']} · "
        f"co-change suspects {rep['totals']['cochange_suspects']}",
        "",
        "## Top Suspects (severity × learned-precision × blast-radius)",
        "",
    ]
    for i, f in enumerate(rep["top_suspects"], 1):
        flag = " ·DIRTY" if f.get("dirty") else ""
        L.append(
            f"{i}. **{f['severity'].upper()}** `{f['file']}:{f['line']}` "
            f"[{f['rule_id']}] p={f['priority']} prec={f['precision']} risk={f['file_risk']}{flag}"
        )
        L.append(f"   - {f['message']}")
        if f.get("snippet"):
            L.append(f"   - `{f['snippet'][:140]}`")
        if f.get("fix"):
            L.append(f"   - fix: {f['fix']}")
        if f.get("triage"):
            t = f["triage"]
            L.append(
                f"   - 🤖 {'REAL' if t['real'] else 'FAKE'} ({t['confidence']}) — {t['reason']}"
            )
        L.append(f"   - verify: `{f['verify']}`")
    if rep["cochange_suspects"]:
        L += ["", "## Forgotten-Edit Suspects (historically co-change, clean now)", ""]
        for c in rep["cochange_suspects"]:
            L.append(
                f"- `{c['path']}` — co-changes with dirty `{c['partner']}` "
                f"{c['co_changes']}× (confidence {c['confidence']}). Check if it needs the same edit."
            )
    if rep["risky_files"]:
        L += [
            "",
            "## Highest-Risk Files",
            "",
            "| file | score | history | struct | findings | ctx |",
            "|---|--:|--:|--:|--:|--:|",
        ]
        for r in rep["risky_files"]:
            fa = r["factors"]
            L.append(
                f"| `{r['file']}` | {r['score']} | {fa['history']} | {fa['structure']} | {fa['findings']} | {fa['context']} |"
            )
    L += [
        "",
        "## How To Act",
        "",
        "1. Fix CRITICAL/HIGH suspects first; run each verify command.",
        "2. Confirm or dismiss to teach the model: "
        "`debugmaster learn-feedback <file> <line> <rule_id> real|fake`.",
        "3. Inspect forgotten-edit suspects — they are bugs no linter can see.",
        "",
    ]
    return "\n".join(L) + "\n"


def ai_brief(rep: dict) -> str:
    L = [
        "# Debugmaster Hunt — AI Brief",
        "",
        f"Verdict: {rep['verdict']} · findings {rep['totals']['findings']} "
        f"{rep['totals']['by_severity']} · co-change {rep['totals']['cochange_suspects']}",
        f"Repo: {rep['repo']}",
        "",
        "Top suspects:",
    ]
    for f in rep["top_suspects"][:12]:
        L.append(
            f"- {f['severity']} {f['file']}:{f['line']} [{f['rule_id']}] p={f['priority']} — {f['message'][:90]}"
        )
    if rep["cochange_suspects"]:
        L.append("")
        L.append("Forgotten-edit suspects:")
        for c in rep["cochange_suspects"][:6]:
            L.append(
                f"- {c['path']} (co-changes with {c['partner']}, conf {c['confidence']})"
            )
    L += [
        "",
        "Instruction: fix highest-priority first; run its verify command before claiming done; "
        "do not revert unrelated user changes. Give feedback so ranking improves next run.",
        "",
    ]
    return "\n".join(L)


def write(rep: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "debugmaster-hunt.json").write_text(json.dumps(rep, indent=2))
    (out_dir / "debugmaster-hunt.md").write_text(markdown(rep))
    (out_dir / "debugmaster-hunt-ai-brief.md").write_text(ai_brief(rep))


if __name__ == "__main__":
    import sys

    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    rep = hunt(repo, fuse=("--no-fuse" not in sys.argv))
    print(markdown(rep))
