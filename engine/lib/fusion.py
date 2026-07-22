"""Tool fusion — run every installed, relevant scanner; normalize to one schema.

No single linter finds everything. Fusion runs the best-in-class polyglot
scanners that are actually installed, parses their JSON into the shared Finding
shape, then dedupes against the built-in engine by (file, line, category). One
ranked queue instead of ten incompatible report formats.

profiles:
  fast : ruff, bandit, gitleaks, shellcheck, actionlint, biome, oxlint  (seconds)
  deep : + semgrep, osv-scanner, vulture, clippy, golangci-lint
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    from . import common
    from .bughunt import Finding
except ImportError:
    import common
    from bughunt import Finding

# normalize the many severity vocabularies into ours
_SEV = {
    "error": "high",
    "warning": "medium",
    "info": "low",
    "note": "low",
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "moderate": "medium",
    "blocker": "critical",
    "major": "high",
    "minor": "low",
    "convention": "info",
    "refactor": "info",
    "style": "info",
}


def _sev(s: str, default="medium") -> str:
    return _SEV.get(str(s).lower(), default)


def _rel(repo: Path, p: str) -> str:
    try:
        return str(Path(p).resolve().relative_to(repo))
    except (ValueError, OSError):
        return p


def _has_ext(repo: Path, exts: set[str]) -> bool:
    for _p, _l in common.iter_source_files(repo, limit=4000):
        if _p.suffix in exts:
            return True
    return False


# JS/TS family — biome + oxlint lint these.
_JS_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}


def _first_json_line(raw: str, needle: str) -> dict | None:
    """Tools that print a JSON object plus human summary lines (biome's unstable
    notice, golangci's '1 issues:' tail): pick the first line that parses and
    contains `needle`, else try the whole blob."""
    for ln in raw.splitlines():
        ln = ln.strip()
        if ln.startswith("{") and needle in ln:
            try:
                return json.loads(ln)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(raw.strip() or "{}")
    except json.JSONDecodeError:
        return None


# ── individual scanner adapters: (repo, timeout) -> (findings, meta) ───────────
def run_ruff(repo, timeout):
    if (
        not common.have("ruff")
        or not (repo / "pyproject.toml").exists()
        and not _has_ext(repo, {".py"})
    ):
        return [], {"tool": "ruff", "status": "skip"}
    cp = common.run(
        ["ruff", "check", "--output-format", "json", "--exit-zero", "."],
        cwd=repo,
        timeout=timeout,
    )
    out = []
    try:
        for d in json.loads(cp.stdout or "[]"):
            code = d.get("code") or "ruff"
            out.append(
                Finding(
                    _rel(repo, d.get("filename", "")),
                    d.get("location", {}).get("row", 0) or 0,
                    f"ruff:{code}",
                    _sev("warning"),
                    d.get("message", "")[:80],
                    "",
                    d.get("message", ""),
                    (d.get("fix") or {}).get("message", "") if d.get("fix") else "",
                    "",
                )
            )
    except json.JSONDecodeError:
        return [], {"tool": "ruff", "status": "parse-error"}
    return out, {"tool": "ruff", "status": "ok", "count": len(out)}


# Heavy/vendored trees that bandit's recursive walk must never descend into —
# scanning a nested `ai-sidecar/.venv` (torch/numpy/transformers = 11k .py) is what
# made the `fast` profile take ~90s. Globs (`*/x/*`) match these dirs at ANY depth;
# root-anchored `./x` paths missed nested venvs/node_modules. (90s → ~1.3s measured.)
_BANDIT_EXCLUDE = (
    "*/.venv/*,*/venv/*,*/env/*,*/site-packages/*,*/node_modules/*,"
    "*/target/*,*/dist/*,*/build/*,*/__pycache__/*,*/.git/*,*/.next/*,*/.cache/*"
)
# Bandit is one of the slowest scanners; in `fast` it must not dominate wall time.
_BANDIT_TIMEOUT_CAP = 45


def run_bandit(repo, timeout):
    if not common.have("bandit") or not _has_ext(repo, {".py"}):
        return [], {"tool": "bandit", "status": "skip"}
    cp = common.run(
        # `-x` skips vendored trees; `-ll` reports medium+ severity only (less work,
        # higher signal); the timeout is capped so a big repo can't stall the run.
        ["bandit", "-r", "-q", "-ll", "-x", _BANDIT_EXCLUDE, "-f", "json", "."],
        cwd=repo,
        timeout=min(timeout, _BANDIT_TIMEOUT_CAP),
    )
    out = []
    try:
        for d in json.loads(cp.stdout or "{}").get("results", []):
            out.append(
                Finding(
                    _rel(repo, d.get("filename", "")),
                    d.get("line_number", 0),
                    f"bandit:{d.get('test_id', '')}",
                    _sev(d.get("issue_severity", "medium")),
                    d.get("test_name", "")[:80],
                    (d.get("code", "") or "").strip()[:200],
                    d.get("issue_text", ""),
                    "",
                    d.get("issue_cwe", {}).get("id", ""),
                )
            )
    except json.JSONDecodeError:
        return [], {"tool": "bandit", "status": "parse-error"}
    return out, {"tool": "bandit", "status": "ok", "count": len(out)}


def run_gitleaks(repo, timeout):
    if not common.have("gitleaks") or not common.git_ok(repo):
        return [], {"tool": "gitleaks", "status": "skip"}
    rpt = repo / ".debugmaster" / "gitleaks.json"
    rpt.parent.mkdir(parents=True, exist_ok=True)
    common.run(
        [
            "gitleaks",
            "detect",
            "--no-banner",
            "--redact",
            "--report-format",
            "json",
            "--report-path",
            str(rpt),
        ],
        cwd=repo,
        timeout=timeout,
    )
    out = []
    if rpt.exists():
        try:
            for d in json.loads(rpt.read_text() or "[]"):
                out.append(
                    Finding(
                        d.get("File", ""),
                        d.get("StartLine", 0),
                        f"gitleaks:{d.get('RuleID', 'secret')}",
                        "critical",
                        "Leaked secret",
                        d.get("Match", "")[:120],
                        d.get("Description", "Hardcoded secret detected"),
                        "Rotate the secret and move to a secret manager.",
                        "CWE-798",
                    )
                )
        except json.JSONDecodeError:
            pass
    return out, {"tool": "gitleaks", "status": "ok", "count": len(out)}


def run_shellcheck(repo, timeout):
    if not common.have("shellcheck"):
        return [], {"tool": "shellcheck", "status": "skip"}
    files = [
        str(p) for p, _l in common.iter_source_files(repo, langs={"shell"}, limit=60)
    ]
    if not files:
        return [], {"tool": "shellcheck", "status": "skip"}
    cp = common.run(["shellcheck", "-f", "json", *files], timeout=timeout)
    out = []
    try:
        data = json.loads(cp.stdout or "[]")
        rows = data.get("comments", []) if isinstance(data, dict) else data
        for d in rows:
            out.append(
                Finding(
                    _rel(repo, d.get("file", "")),
                    d.get("line", 0),
                    f"shellcheck:SC{d.get('code', '')}",
                    _sev(d.get("level", "warning")),
                    d.get("message", "")[:80],
                    "",
                    d.get("message", ""),
                    "",
                    "",
                )
            )
    except json.JSONDecodeError:
        return [], {"tool": "shellcheck", "status": "parse-error"}
    return out, {"tool": "shellcheck", "status": "ok", "count": len(out)}


def run_actionlint(repo, timeout):
    if not common.have("actionlint") or not (repo / ".github" / "workflows").exists():
        return [], {"tool": "actionlint", "status": "skip"}
    cp = common.run(
        ["actionlint", "-format", "{{json .}}", "-no-color"], cwd=repo, timeout=timeout
    )
    out = []
    try:
        raw = (cp.stdout or "").strip() or "[]"
        try:
            data = json.loads(raw)
            rows = data if isinstance(data, list) else [data]
        except json.JSONDecodeError:  # JSONL fallback (one object per line)
            rows = [json.loads(ln) for ln in raw.splitlines() if ln.strip()]
        for d in rows:
            out.append(
                Finding(
                    d.get("filepath", ""),
                    d.get("line", 0),
                    f"actionlint:{d.get('kind', 'ci')}",
                    "medium",
                    d.get("message", "")[:80],
                    d.get("snippet", "")[:120],
                    d.get("message", ""),
                    "",
                    "",
                )
            )
    except json.JSONDecodeError:
        return [], {"tool": "actionlint", "status": "parse-error"}
    return out, {"tool": "actionlint", "status": "ok", "count": len(out)}


def run_semgrep(repo, timeout):
    if not common.have("semgrep"):
        return [], {"tool": "semgrep", "status": "skip"}
    cp = common.run(
        ["semgrep", "--quiet", "--json", "--config", "auto", "--timeout", "20", "."],
        cwd=repo,
        timeout=timeout,
    )
    out = []
    try:
        for d in json.loads(cp.stdout or "{}").get("results", []):
            ex = d.get("extra", {})
            out.append(
                Finding(
                    _rel(repo, d.get("path", "")),
                    d.get("start", {}).get("line", 0),
                    f"semgrep:{d.get('check_id', '').split('.')[-1]}",
                    _sev(ex.get("severity", "warning")),
                    (ex.get("message", "") or "")[:80],
                    (ex.get("lines", "") or "").strip()[:200],
                    ex.get("message", ""),
                    "",
                    str(ex.get("metadata", {}).get("cwe", ""))[:40],
                )
            )
    except json.JSONDecodeError:
        return [], {"tool": "semgrep", "status": "parse-error"}
    return out, {"tool": "semgrep", "status": "ok", "count": len(out)}


def run_osv(repo, timeout):
    if not common.have("osv-scanner"):
        return [], {"tool": "osv-scanner", "status": "skip"}
    cp = common.run(
        ["osv-scanner", "--format", "json", "-r", "."], cwd=repo, timeout=timeout
    )
    out = []
    try:
        for res in json.loads(cp.stdout or "{}").get("results", []):
            src = res.get("source", {}).get("path", "")
            for pkg in res.get("packages", []):
                name = pkg.get("package", {}).get("name", "")
                for v in pkg.get("vulnerabilities", []):
                    out.append(
                        Finding(
                            _rel(repo, src),
                            0,
                            f"osv:{v.get('id', '')}",
                            "high",
                            f"Vulnerable dependency {name}",
                            "",
                            (v.get("summary") or v.get("id", ""))[:200],
                            "Upgrade the dependency to a patched version.",
                            "",
                        )
                    )
    except json.JSONDecodeError:
        return [], {"tool": "osv-scanner", "status": "parse-error"}
    return out, {"tool": "osv-scanner", "status": "ok", "count": len(out)}


def run_vulture(repo, timeout):
    if not common.have("vulture") or not _has_ext(repo, {".py"}):
        return [], {"tool": "vulture", "status": "skip"}
    cp = common.run(
        ["vulture", ".", "--min-confidence", "80"], cwd=repo, timeout=timeout
    )
    out = []
    for ln in (cp.stdout or "").splitlines():
        parts = ln.split(":", 2)
        if len(parts) >= 3 and parts[1].isdigit():
            out.append(
                Finding(
                    _rel(repo, parts[0]),
                    int(parts[1]),
                    "vulture:dead-code",
                    "low",
                    "Unused code",
                    parts[2].strip()[:120],
                    parts[2].strip(),
                    "Remove if truly unused (confirm — may be public API).",
                    "",
                )
            )
    return out, {"tool": "vulture", "status": "ok", "count": len(out)}


def run_clippy(repo, timeout):
    if not common.have("cargo") or not (repo / "Cargo.toml").exists():
        return [], {"tool": "clippy", "status": "skip"}
    cp = common.run(
        ["cargo", "clippy", "--message-format=json", "--quiet"],
        cwd=repo,
        timeout=timeout,
    )
    out = []
    for line in (cp.stdout or "").splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("reason") != "compiler-message":
            continue
        m = msg.get("message", {})
        level = m.get("level", "")
        if level not in ("warning", "error"):
            continue
        spans = m.get("spans", [])
        if not spans:
            continue
        s0 = spans[0]
        out.append(
            Finding(
                _rel(repo, s0.get("file_name", "")),
                s0.get("line_start", 0),
                f"clippy:{(m.get('code') or {}).get('code', 'lint')}",
                _sev(level),
                (m.get("message", "") or "")[:80],
                "",
                m.get("message", ""),
                "",
                "",
            )
        )
    return out, {"tool": "clippy", "status": "ok", "count": len(out)}


def run_biome(repo, timeout):
    """Biome — the June-2026 best-practice JS/TS linter+formatter (Rust, fast)."""
    if not common.have("biome") or not _has_ext(repo, _JS_EXT):
        return [], {"tool": "biome", "status": "skip"}
    cp = common.run(
        ["biome", "lint", "--reporter=json", "--max-diagnostics=200", "."],
        cwd=repo,
        timeout=timeout,
    )
    data = _first_json_line(cp.stdout or "", '"diagnostics"')
    if data is None:
        return [], {"tool": "biome", "status": "parse-error"}
    out = []
    for d in data.get("diagnostics", []):
        loc = d.get("location", {}) or {}
        path = loc.get("path", "")
        if isinstance(path, dict):  # some versions nest {file:...}
            path = path.get("file") or path.get("path") or ""
        line = (loc.get("start") or {}).get("line", 0) or 0
        msg = d.get("message", "") or ""
        out.append(
            Finding(
                _rel(repo, path),
                line,
                f"biome:{d.get('category', 'lint')}",
                _sev(d.get("severity", "warning")),
                msg[:80],
                "",
                msg,
                "",
                "",
            )
        )
    return out, {"tool": "biome", "status": "ok", "count": len(out)}


def run_oxlint(repo, timeout):
    """Oxlint — ultrafast JS/TS linter. Degrades to skip when the binary on PATH
    is the IDE-only wrapper (prints a notice instead of JSON)."""
    if not common.have("oxlint") or not _has_ext(repo, _JS_EXT):
        return [], {"tool": "oxlint", "status": "skip"}
    cp = common.run(["oxlint", "--format=json", "."], cwd=repo, timeout=timeout)
    raw = (cp.stdout or "").strip()
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return [], {"tool": "oxlint", "status": "skip"}  # IDE wrapper / no JSON
    rows = data if isinstance(data, list) else data.get("diagnostics", [])
    out = []
    for d in rows:
        if isinstance(d, dict) and "messages" in d:  # ESLint-compatible shape
            fp = d.get("filePath", "")
            for m in d.get("messages", []):
                msg = m.get("message", "") or ""
                out.append(
                    Finding(
                        _rel(repo, fp),
                        m.get("line", 0) or 0,
                        f"oxlint:{m.get('ruleId', 'lint')}",
                        "high" if m.get("severity") == 2 else "medium",
                        msg[:80],
                        "",
                        msg,
                        "",
                        "",
                    )
                )
    return out, {"tool": "oxlint", "status": "ok", "count": len(out)}


# golangci linters that surface real defects (not style) → escalate severity.
_GO_HIGH = {
    "typecheck",
    "govet",
    "staticcheck",
    "errcheck",
    "gosec",
    "ineffassign",
    "bodyclose",
    "sqlclosecheck",
    "nilerr",
    "nilnesserr",
    "rowserrcheck",
}


def run_golangci(repo, timeout):
    """golangci-lint — the June-2026 best-practice Go meta-linter (bundles
    staticcheck/govet/errcheck/gosec). DEEP only — it compiles the module."""
    if not common.have("golangci-lint") or not (repo / "go.mod").exists():
        return [], {"tool": "golangci-lint", "status": "skip"}
    cp = common.run(
        ["golangci-lint", "run", "--output.json.path", "stdout"],
        cwd=repo,
        timeout=timeout,
    )
    data = _first_json_line(cp.stdout or "", '"Issues"')
    if data is None:
        return [], {"tool": "golangci-lint", "status": "parse-error"}
    out = []
    for d in data.get("Issues") or []:
        linter = d.get("FromLinter", "")
        pos = d.get("Pos", {}) or {}
        sev = d.get("Severity") or ""
        severity = _sev(sev) if sev else ("high" if linter in _GO_HIGH else "medium")
        text = (d.get("Text", "") or "").strip().replace("\n", " ")
        out.append(
            Finding(
                _rel(repo, pos.get("Filename", "")),
                pos.get("Line", 0) or 0,
                f"golangci:{linter}",
                severity,
                text[:80],
                "",
                text,
                "",
                "CWE-noted" if linter == "gosec" else "",
            )
        )
    return out, {"tool": "golangci-lint", "status": "ok", "count": len(out)}


FAST = [
    run_ruff,
    run_bandit,
    run_gitleaks,
    run_shellcheck,
    run_actionlint,
    run_biome,
    run_oxlint,
]
DEEP = FAST + [run_semgrep, run_osv, run_vulture, run_clippy, run_golangci]


def run(repo: Path, *, profile: str = "fast", timeout: int = 90, only_scanners: set[str] | None = None) -> dict:
    """Run installed scanners concurrently within a per-scanner time budget.

    Scanners are independent external processes, so they run in parallel on a thread
    pool — wall time is the SLOWEST scanner, not the sum (a gitleaks timeout no longer
    blocks bandit). To honour a ~75%-of-cores budget even though tools like ruff and
    semgrep parallelise internally, concurrency is capped and each scanner's own
    thread pool is pinned via env (`common.thread_cap_env`): roughly
    `pool_workers × per_scanner_threads ≈ 75% of cores`. Each scanner gets the full
    `timeout`; a hang/crash is caught and reported, never silently dropped.

    If `only_scanners` is given (a set of function names like {"run_ruff", "run_bandit"}),
    only those scanners run — used by `fusion --only <layer>` to scope fusion to a
    feature layer."""
    import os
    import subprocess as _sp
    from concurrent.futures import ThreadPoolExecutor

    scanners = DEEP if profile == "deep" else FAST
    if only_scanners is not None:
        scanners = [fn for fn in scanners if fn.__name__ in only_scanners]
        if not scanners:
            return {"findings": [], "scanners": [], "profile": profile, "filtered": sorted(only_scanners)}
    budget = common.worker_count()  # ~75% of cores
    # split the budget between scanner-concurrency and each scanner's own threads
    per_scanner_threads = 2 if budget >= 4 else 1
    pool = max(1, min(len(scanners), budget // per_scanner_threads))

    def _one(fn):
        name = fn.__name__.replace("run_", "")
        try:
            return fn(repo, timeout)
        except _sp.TimeoutExpired:
            return [], {"tool": name, "status": "timeout"}
        except Exception as e:  # a broken scanner must never kill the run
            return [], {"tool": name, "status": f"error:{e}"[:120]}

    findings: list[Finding] = []
    meta = []
    # cap each scanner's internal thread pool (ruff/biome/clippy use Rayon, native
    # tools OpenMP) for the duration of the parallel run, then restore — so N
    # concurrent scanners x their own threads stays within the core budget.
    cap_env = common.thread_cap_env(per_scanner_threads)
    saved = {k: os.environ.get(k) for k in cap_env}
    os.environ.update(cap_env)
    try:
        with ThreadPoolExecutor(max_workers=pool) as ex:
            for fs, m in ex.map(_one, scanners):
                findings.extend(fs)
                meta.append(m)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return {"findings": findings, "scanners": meta, "profile": profile}


def dedupe(findings: list[Finding]) -> list[Finding]:
    """Collapse same file:line near-duplicates, keeping highest severity."""
    best: dict[tuple, Finding] = {}
    for f in findings:
        key = (f.file, f.line)
        cur = best.get(key)
        if cur is None or common.SEVERITY_RANK.get(
            f.severity, 0
        ) > common.SEVERITY_RANK.get(cur.severity, 0):
            best[key] = f
    out = list(best.values())
    out.sort(key=lambda f: (-common.SEVERITY_RANK.get(f.severity, 0), f.file, f.line))
    return out


if __name__ == "__main__":
    import sys

    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    prof = sys.argv[2] if len(sys.argv) > 2 else "fast"
    res = run(repo, profile=prof)
    print(
        json.dumps(
            {
                "scanners": res["scanners"],
                "total": len(res["findings"]),
                "sample": [f.as_dict() for f in dedupe(res["findings"])[:15]],
            },
            indent=2,
        )
    )
