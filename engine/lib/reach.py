"""Reachability / blast-radius — turn P(bug) into EXPECTED DAMAGE.

A bug in a leaf script matters less than the same bug in a module 40 files
import. This layer answers "who depends on this?" and "is this change tested?":

  fan_in(repo, files)  : reverse import graph (precise module resolution; uses a
                         real call graph from codegraph when indexed, else the
                         import heuristic, else 0 — never fails).
  test_gaps(repo, ...)  : changed source files with no test referencing them =
                         a change shipping untested. The cheapest pre-mortem.

Expected damage = P(bug) * log1p(fan_in); test-gap multiplies the risk.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    from . import common
    from .bughunt import Finding
except ImportError:
    import common
    from bughunt import Finding

IMPORT_RE = [
    re.compile(r"^\s*import\s+([\w.]+)"),
    re.compile(r"^\s*from\s+([\w.]+)\s+import"),
    re.compile(r"""require\(\s*['"]([^'"]+)['"]"""),
    re.compile(r"""from\s+['"]([^'"]+)['"]"""),  # JS/TS es import ... from '...'
    re.compile(r"""import\s+['"]([^'"]+)['"]"""),
    re.compile(r"^\s*use\s+(?:crate::)?([\w:]+)"),  # rust
]
TEST_HINT = re.compile(
    r"(^|/)(tests?|__tests__|spec)(/|$)|(_test\.|test_|\.test\.|\.spec\.)"
)


def _module_tokens(rel: str) -> set[str]:
    """Names by which a file is likely imported: its stem and package path tail."""
    p = Path(rel)
    toks = set()
    stem = p.stem
    if stem and stem not in ("index", "mod", "__init__", "main", "lib"):
        toks.add(stem)
    # dotted python-ish module path: a/b/c.py -> c, b.c, a.b.c
    parts = [x for x in p.with_suffix("").parts if x not in ("src", "lib", "__init__")]
    if parts:
        toks.add(parts[-1])
    return {t for t in toks if len(t) >= 3}


def import_fan_in(
    repo: Path, targets: list[str], *, scan_limit: int = 8000
) -> dict[str, int]:
    """How many other files import each target file (by resolved module token)."""
    token_owner: dict[str, set[str]] = {}
    for t in targets:
        for tok in _module_tokens(t):
            token_owner.setdefault(tok, set()).add(t)
    counts = {t: 0 for t in targets}
    if not token_owner:
        return counts
    for path, _lang in common.iter_source_files(repo, limit=scan_limit):
        rel_self = common.rel(repo, path)
        imported: set[str] = set()
        for ln in common.read_lines(path):
            if (
                not (ln.lstrip()[:8] or "")
                .lower()
                .startswith(("import", "from", "use", "requir", "const", "let"))
            ):
                if "require(" not in ln and "from " not in ln:
                    continue
            for rx in IMPORT_RE:
                m = rx.search(ln)
                if m:
                    tail = re.split(r"[./:\\]", m.group(1))[-1]
                    if tail:
                        imported.add(tail)
        for tok in imported & token_owner.keys():
            for owner in token_owner[tok]:
                if owner != rel_self:
                    counts[owner] += 1
    return counts


def codegraph_fan_in(repo: Path, targets: list[str]) -> dict[str, int] | None:
    """Use the codegraph CLI for resolved fan-in when the repo is indexed.

    One `codegraph callers` subprocess per target dominates a hunt's wall-time on a
    large repo (40 × ~100ms serial ≈ 4s). The calls are independent and I/O-bound,
    so they run on a small thread pool — same result, a fraction of the latency."""
    if not common.have("codegraph") or not (repo / ".codegraph").exists():
        return None
    import json
    from concurrent.futures import ThreadPoolExecutor

    sel = targets[:40]  # bounded: only the top candidates

    def _one(t: str):
        cp = common.run(
            ["codegraph", "callers", t, "-p", str(repo), "-j"], cwd=repo, timeout=8
        )
        if cp.returncode != 0:
            return t, None
        try:
            data = json.loads(cp.stdout or "{}")
            callers = data.get("callers") or data.get("results") or []
            return t, (len(callers) if isinstance(callers, list) else 0)
        except Exception:
            return t, None

    counts = {}
    workers = max(1, min(common.worker_count(), len(sel)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for t, c in ex.map(_one, sel):
            if c is not None:
                counts[t] = c
    return counts or None


def fan_in(repo: Path, targets: list[str]) -> dict[str, int]:
    cg = codegraph_fan_in(repo, targets)
    if cg and len(cg) >= len(targets):
        return {t: cg.get(t, 0) for t in targets}
    base = import_fan_in(repo, targets)  # heuristic covers every target
    if cg:  # overlay resolved counts where codegraph had them
        for k, v in cg.items():
            base[k] = max(base.get(k, 0), v)
    return base


def test_gaps(repo: Path, changed: list[str], *, limit: int = 20) -> list[Finding]:
    """Changed non-test source files with no test that references them."""
    src_changed = [c for c in changed if common.lang_of(c) and not TEST_HINT.search(c)]
    if not src_changed:
        return []
    # collect test-file text once, capped so a huge repo cannot blow up memory
    max_bytes = 32 * 1024 * 1024
    test_blobs = []
    total = 0
    for path, _lang in common.iter_source_files(repo, limit=8000):
        if total >= max_bytes:
            break
        if TEST_HINT.search(common.rel(repo, path)):
            t = common.read_text(path)
            test_blobs.append(t)
            total += len(t)
    joined = "\n".join(test_blobs)
    out = []
    for c in src_changed:
        toks = _module_tokens(c)
        if not toks:
            continue
        if not joined or not any(tok in joined for tok in toks):
            out.append(
                Finding(
                    c,
                    0,
                    "test-gap",
                    "medium",
                    "Changed code has no covering test",
                    "",
                    f"No test file references {', '.join(sorted(toks))} — this change ships untested.",
                    "Add a test that exercises the changed behavior before merging.",
                    "CWE-1120",
                )
            )
    return out[:limit]


if __name__ == "__main__":
    import json
    import sys

    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    files = [common.rel(repo, p) for p, _l in common.iter_source_files(repo, limit=200)]
    fi = fan_in(repo, files)
    top = sorted(fi.items(), key=lambda kv: kv[1], reverse=True)[:12]
    print(
        json.dumps(
            {
                "engine": "codegraph"
                if codegraph_fan_in(repo, files[:1])
                else "import-heuristic",
                "top_fan_in": top,
            },
            indent=2,
        )
    )
