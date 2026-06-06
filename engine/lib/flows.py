"""Active debugging flows — beyond static scanning into root-cause and review.

These encode the loops developers actually run:
  bisect   reproduce → automatically git-bisect a test command → the exact
           commit that introduced the bug (deterministic, no LLM).
  explain  paste a stacktrace → localize every in-repo frame, show the code,
           and run the engines on those files → ranked suspects.
  review   "is this change safe?" → hunt scoped to what changed vs a base ref,
           plus forgotten co-change suspects → a PR-style verdict. The flow built
           for the 2026 reality of reviewing AI-generated diffs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

try:
    from . import common, hunt
except ImportError:
    import common
    import hunt

# matches "File "/path/x.py", line 42" and "at foo (/path/x.js:42:7)" and "path/x.go:42"
FRAME_RES = [
    re.compile(r'File "([^"]+)", line (\d+)'),
    re.compile(r"(?:at\s+\S+\s+\()?([\/\w.\-]+\.\w+):(\d+)(?::\d+)?"),
]


def bisect(repo: Path, good: str, bad: str, test_cmd: str, timeout: int = 600) -> dict:
    """Automate `git bisect run`. Returns the first bad commit + the log."""
    repo = Path(repo).resolve()
    if not common.git_ok(repo) or not common.have("git"):
        return {"ok": False, "reason": "not a git repo"}
    common.run(["git", "-C", str(repo), "bisect", "reset"], timeout=30)
    start = common.run(
        ["git", "-C", str(repo), "bisect", "start", bad, good], timeout=30
    )
    if start.returncode != 0:
        return {"ok": False, "reason": start.stderr[-300:], "stage": "start"}
    try:
        run = common.run(
            ["git", "-C", str(repo), "bisect", "run", "bash", "-lc", test_cmd],
            timeout=timeout,
        )
    except Exception as e:
        common.run(["git", "-C", str(repo), "bisect", "reset"], timeout=30)
        return {"ok": False, "reason": str(e)[:200], "stage": "run"}
    log = run.stdout + "\n" + run.stderr
    culprit = None
    m = re.search(r"([0-9a-f]{7,40}) is the first bad commit", log)
    if m:
        sha = m.group(1)
        show = common.run(
            ["git", "-C", str(repo), "show", "-s", "--format=%h %an %s", sha],
            timeout=15,
        )
        culprit = show.stdout.strip()
    reset = common.run(["git", "-C", str(repo), "bisect", "reset"], timeout=30)
    out = {
        "ok": bool(culprit),
        "first_bad_commit": culprit,
        "log_tail": log[-3000:],
        "test_cmd": test_cmd,
    }
    if reset.returncode != 0:  # leave a loud warning — repo may be mid-bisect
        out["warning"] = (
            "git bisect reset failed; run `git bisect reset` manually. "
            + reset.stderr[-200:]
        )
    return out


def explain(repo: Path, trace: str, limit: int = 12) -> dict:
    """Localize a stacktrace into the repo and surface suspects around each frame."""
    repo = Path(repo).resolve()
    frames = []
    seen = set()
    for rx in FRAME_RES:
        for m in rx.finditer(trace):
            raw, line = m.group(1), int(m.group(2))
            rel = _to_repo_rel(repo, raw)
            if rel and (rel, line) not in seen:
                seen.add((rel, line))
                frames.append({"file": rel, "line": line})
    frames = frames[:limit]
    # show code context + which engine findings sit near each frame
    changed = set(hunt.git_changed(repo))
    enriched = []
    for fr in frames:
        p = repo / fr["file"]
        ctx = ""
        if p.exists():
            lines = common.read_lines(p)
            lo, hi = max(0, fr["line"] - 3), min(len(lines), fr["line"] + 2)
            ctx = "\n".join(
                f"{'>' if j + 1 == fr['line'] else ' '} {j + 1}: {lines[j]}"
                for j in range(lo, hi)
            )
        enriched.append({**fr, "in_diff": fr["file"] in changed, "context": ctx})
    error_line = next((ln.strip() for ln in trace.splitlines()[::-1] if ln.strip()), "")
    # Python ("most recent call last") = deepest is the LAST in-repo frame;
    # JS/Java/Go stacks list the throw site FIRST.
    py_order = "most recent call last" in trace.lower()
    deepest = (enriched[-1] if py_order else enriched[0]) if enriched else None
    return {
        "frames": enriched,
        "deepest_repo_frame": deepest,
        "error": error_line[:300],
        "next": "Start at the deepest in-repo frame; if it is in your diff, suspect the change. "
        "Run `debugmaster hunt <repo> --dirty` and the per-file verify command.",
    }


def _within(repo: Path, p: Path) -> str | None:
    """Return repo-relative path iff p resolves INSIDE repo (no ../ escape)."""
    try:
        return str(p.resolve().relative_to(repo))
    except (ValueError, OSError):
        return None


def _to_repo_rel(repo: Path, raw: str) -> str | None:
    raw = raw.strip()
    p = Path(raw)
    if p.is_absolute():
        return _within(repo, p)  # only if inside the repo
    # relative frame: must resolve inside the repo and exist
    cand = repo / raw
    rel = _within(repo, cand)
    if rel and cand.exists():
        return rel
    # last path segments fallback (site-packages-stripped) — still must stay inside
    parts = Path(raw).parts
    for i in range(1, len(parts)):
        sub = repo / Path(*parts[i:])
        rel = _within(repo, sub)
        if rel and sub.exists():
            return rel
    return None


def changed_vs_base(repo: Path, base: str) -> list[str]:
    """Files changed between base..HEAD plus the working tree."""
    out = set(hunt.git_changed(repo))
    if common.git_ok(repo) and common.have("git"):
        cp = common.run(
            ["git", "-C", str(repo), "diff", "--name-only", f"{base}...HEAD"],
            timeout=30,
        )
        if cp.returncode == 0:
            for ln in cp.stdout.splitlines():
                if ln.strip() and not common.is_skipped(Path(ln).parts):
                    out.add(ln.strip())
    return sorted(out)


def review(
    repo: Path,
    base: str | None = None,
    *,
    profile: str = "fast",
    timeout: int = 90,
    fuse: bool = True,
) -> dict:
    """'Is this change safe?' — hunt scoped to the changeset, framed as a PR verdict."""
    repo = Path(repo).resolve()
    changed = changed_vs_base(repo, base) if base else hunt.git_changed(repo)
    rep = hunt.hunt(
        repo,
        profile=profile,
        fuse=fuse,
        timeout=timeout,
        dirty_only=False,
        record=False,
        use_cache=False,
    )
    changed_set = set(changed)
    on_change = [f for f in rep["top_suspects"] if f["file"] in changed_set]
    crit = [f for f in on_change if f["severity"] in ("critical", "high")]
    if crit:
        decision = "REQUEST-CHANGES"
    elif on_change or rep["cochange_suspects"]:
        decision = "COMMENT"
    else:
        decision = "APPROVE"
    return {
        "decision": decision,
        "base": base or "working-tree",
        "changed_files": len(changed),
        "findings_on_change": on_change[:20],
        "forgotten_edit_suspects": rep["cochange_suspects"][:8],
        "verdict": rep["verdict"],
        "note": "Findings limited to changed files. Forgotten-edit suspects are files that "
        "historically change with these but did not — review them too.",
    }


def source_fingerprint(repo: Path, *, limit: int = 8000) -> dict:
    """{rel_path: mtime} for source files — cheap change-detection for `watch`."""
    fp = {}
    for path, _lang in hunt.common.iter_source_files(repo, limit=limit):
        try:
            fp[hunt.common.rel(repo, path)] = path.stat().st_mtime
        except OSError:
            continue
    return fp


def scan_files(repo: Path, rel_files: list[str]) -> list:
    """Run both static engines over a specific set of files (used by `watch`)."""
    out = []
    for relp in rel_files:
        lang = hunt.common.lang_of(relp)
        if lang:
            out += hunt._scan_one(repo, relp, lang)
    out.sort(
        key=lambda f: (-hunt.common.SEVERITY_RANK.get(f.severity, 0), f.file, f.line)
    )
    return out


def watch(repo: Path, *, interval: float = 2.0, max_rounds: int | None = None) -> None:
    """Re-scan changed files on every save until interrupted. Blocking; prints a
    compact finding list per change. `max_rounds` bounds it for tests."""
    import time

    repo = Path(repo).resolve()
    prev = source_fingerprint(repo)
    print(f"# debugmaster watch — {repo} ({len(prev)} files) · Ctrl-C to stop")
    rounds = 0
    while max_rounds is None or rounds < max_rounds:
        time.sleep(interval)
        rounds += 1
        cur = source_fingerprint(repo)
        changed = [f for f in cur if cur[f] != prev.get(f)]
        if not changed:
            continue
        prev = cur
        findings = scan_files(repo, changed)
        ts = time.strftime("%H:%M:%S")
        if not findings:
            print(f"[{ts}] {len(changed)} changed · clean ✅")
            continue
        print(f"[{ts}] {len(changed)} changed · {len(findings)} finding(s):")
        for f in findings[:15]:
            print(
                f"   {f.severity.upper():8} {f.file}:{f.line} [{f.rule_id}] {f.message[:80]}"
            )


_REGRESS_TEMPLATE = '''
@pytest.mark.skipif(not _DEBUGMASTER, reason="debugmaster not installed")
def test_no_regression_{slug}():
    """Locks the fix for [{rule_id}] at {file}:{line}.

    {message}
    Fix: {fix}

    Fails while the bug is present; passes once fixed; guards against regression forever.
    """
    out = subprocess.run(
        [_DEBUGMASTER, "scan-bugs", {file!r}, "--class", {cls!r}],
        capture_output=True, text=True,
    ).stdout
    assert "{rule_id}" not in out, (
        "debugmaster still flags [{rule_id}] in {file} — the bug is not fixed yet"
    )
'''

_REGRESS_HEADER = '''"""Regression guards generated by `debugmaster regress`.

Each test re-runs debugmaster on the offending file and fails until the finding is
gone — turning a one-off bug into a permanent guard. Skips cleanly if debugmaster
is not on PATH.
"""
import shutil
import subprocess

import pytest

_DEBUGMASTER = shutil.which("debugmaster")
'''


def regress(repo: Path, file: str, rule_id: str, line: int = 0) -> dict:
    """Generate a runnable pytest that locks a confirmed finding as fixed.

    The test re-invokes `debugmaster scan-bugs <file>` and asserts the rule no longer
    appears — red now, green after the fix, a permanent regression guard after that."""
    repo = Path(repo).resolve()
    rep = hunt.hunt(repo, fuse=False, record=False, use_cache=False)
    match = next(
        (
            f
            for f in rep["top_suspects"]
            if f["file"] == file
            and f["rule_id"] == rule_id
            and (not line or f["line"] == line)
        ),
        None,
    )
    if match is None:
        return {
            "ok": False,
            "reason": f"no current finding {rule_id} at {file}"
            + (f":{line}" if line else ""),
        }
    cls = rule_id.split("-")[0] if "-" in rule_id else rule_id
    slug = re.sub(
        r"[^a-z0-9]+", "_", f"{rule_id}_{Path(file).stem}_{match['line']}".lower()
    )
    body = _REGRESS_TEMPLATE.format(
        slug=slug,
        rule_id=rule_id,
        file=file,
        line=match["line"],
        message=match["message"][:160].replace('"', "'"),
        fix=(match.get("fix") or "").replace('"', "'"),
        cls=cls,
    )
    tdir = repo / "tests"
    tdir.mkdir(exist_ok=True)
    dst = tdir / "test_debugmaster_regress.py"
    if dst.exists():
        existing = dst.read_text()
        if f"test_no_regression_{slug}(" in existing:
            return {
                "ok": True,
                "path": str(dst),
                "test": f"test_no_regression_{slug}",
                "note": "already present",
            }
        dst.write_text(existing.rstrip() + "\n\n" + body)
    else:
        dst.write_text(_REGRESS_HEADER + "\n" + body)
    return {
        "ok": True,
        "path": str(dst),
        "test": f"test_no_regression_{slug}",
        "run": f"pytest {dst}::test_no_regression_{slug}",
    }


def review_comment_markdown(res: dict) -> str:
    """Render a review result as a PR-comment body."""
    icon = {"REQUEST-CHANGES": "🔴", "COMMENT": "🟡", "APPROVE": "🟢"}.get(
        res["decision"], ""
    )
    L = [
        f"## 🔍 debugmaster review — {icon} **{res['decision']}**",
        f"_{res['changed_files']} changed file(s) vs `{res['base']}` · repo verdict {res['verdict']}_",
        "",
    ]
    fos = res["findings_on_change"]
    if not fos and not res["forgotten_edit_suspects"]:
        L.append("No issues on the changed lines. ✅")
    if fos:
        L += ["### Findings on your change", ""]
        for f in fos:
            L.append(
                f"- **{f['severity'].upper()}** `{f['file']}:{f['line']}` "
                f"[{f['rule_id']}] — {f['message'][:160]}"
            )
            if f.get("fix"):
                L.append(f"  - fix: {f['fix']}")
    if res["forgotten_edit_suspects"]:
        L += ["", "### Forgotten-edit suspects"]
        for c in res["forgotten_edit_suspects"]:
            L.append(
                f"- `{c['path']}` (co-changes with `{c['partner']}`, confidence {c['confidence']})"
            )
    L += ["", "<sub>— debugmaster · `review`</sub>"]
    return "\n".join(L) + "\n"


def post_pr_comment(repo: Path, body: str, *, pr: str | None = None) -> dict:
    """Post a comment to the current (or given) PR/MR via gh, else glab. If neither
    CLI is present, return the body so the caller can print it — never a hard fail."""
    repo = Path(repo).resolve()
    if common.have("gh"):
        cmd = ["gh", "pr", "comment"] + ([pr] if pr else []) + ["--body", body]
        cp = common.run(cmd, cwd=repo, timeout=45)
        if cp.returncode == 0:
            return {"posted": True, "tool": "gh", "url": cp.stdout.strip()}
        return {
            "posted": False,
            "tool": "gh",
            "reason": (cp.stderr or cp.stdout).strip()[:300],
        }
    if common.have("glab"):
        cmd = ["glab", "mr", "note"] + ([pr] if pr else []) + ["-m", body]
        cp = common.run(cmd, cwd=repo, timeout=45)
        if cp.returncode == 0:
            return {"posted": True, "tool": "glab", "url": cp.stdout.strip()}
        return {
            "posted": False,
            "tool": "glab",
            "reason": (cp.stderr or cp.stdout).strip()[:300],
        }
    return {
        "posted": False,
        "tool": None,
        "reason": "no gh/glab CLI found — comment body printed",
    }


def fix_verify(repo: Path, file: str, rule_id: str, line: int = 0) -> dict:
    """Close the loop: run the finding's verify command, re-scan the file, and on a
    clean pass auto-record learn-feedback so a confirmed-and-fixed bug teaches the
    ranker. This is the last hop the pipeline was missing."""
    from . import bizlogic, bughunt, learn

    repo = Path(repo).resolve()
    cmd = hunt.verify_cmd(file)
    passed, output = None, ""
    if cmd and not cmd.startswith("re-run"):
        cp = common.run(["bash", "-lc", cmd], cwd=repo, timeout=180)
        passed = cp.returncode == 0
        output = (cp.stdout + cp.stderr)[-1500:]
    # re-scan just this file: is the finding still there?
    p = repo / file
    lang = common.lang_of(file) or ""
    still = False
    if p.exists():
        fs = bughunt.scan_file(repo, p, lang) + bizlogic.scan_file(repo, p, lang)
        still = any(f.rule_id == rule_id and (line == 0 or f.line == line) for f in fs)
    fixed = (passed is not False) and not still
    learned = None
    if fixed and line:
        # the finding was actionable and is now gone -> it was a real bug
        learned = learn.feedback(repo, file, line, rule_id, real=True)
    return {
        "verify_cmd": cmd,
        "verify_passed": passed,
        "finding_still_present": still,
        "fixed": fixed,
        "learned": learned,
        "output_tail": output,
    }


PRE_COMMIT = """#!/usr/bin/env bash
# debugmaster pre-commit gate — blocks commits with high/critical findings on changed files
set -e
DM="$(command -v debugmaster || echo "{dm}")"
out="$("$DM" review . --no-fuse 2>/dev/null || true)"
dec="$(printf '%s' "$out" | grep -o '"decision": *"[^"]*"' | head -1)"
if printf '%s' "$dec" | grep -q REQUEST-CHANGES; then
  echo "debugmaster: REQUEST-CHANGES — high/critical finding on your diff. Review:"
  printf '%s\\n' "$out" | grep -A2 '"rule_id"' | head -30
  echo "Bypass with: git commit --no-verify"
  exit 1
fi
exit 0
"""


def install_hooks(repo: Path) -> dict:
    """Install a pre-commit gate that runs `review` and blocks on REQUEST-CHANGES."""
    repo = Path(repo).resolve()
    hooks = repo / ".git" / "hooks"
    if not hooks.exists():
        return {"ok": False, "reason": "no .git/hooks (not a git repo?)"}
    dst = hooks / "pre-commit"
    if dst.exists():
        dst.rename(hooks / "pre-commit.debugmaster.bak")
    dm = str((Path(__file__).resolve().parents[1] / "bin" / "debugmaster"))
    dst.write_text(PRE_COMMIT.replace("{dm}", dm))
    dst.chmod(0o755)
    return {
        "ok": True,
        "installed": str(dst),
        "backup": str(hooks / "pre-commit.debugmaster.bak")
        if (hooks / "pre-commit.debugmaster.bak").exists()
        else None,
        "note": "Commits with a high/critical finding on changed files now fail. Bypass: git commit --no-verify.",
    }


if __name__ == "__main__":
    import sys

    repo = Path(sys.argv[2] if len(sys.argv) > 2 else ".").resolve()
    mode = sys.argv[1] if len(sys.argv) > 1 else "review"
    if mode == "review":
        print(json.dumps(review(repo), indent=2))
    elif mode == "explain":
        print(json.dumps(explain(repo, sys.stdin.read()), indent=2))
