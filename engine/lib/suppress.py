"""Finding suppression — the #1 thing developers want from any scanner: a way to
silence accepted/known findings so signal stays high. False-positive fatigue is
why teams abandon linters; an un-mutable scanner trains people to ignore it.

Two explicit, reviewable mechanisms:

  1. `.debugmaster-ignore` at the repo root — one rule per line:
       py-bare-except                 # silence a rule everywhere
       legacy/**:biz-float-money      # silence a rule under a path glob
       vendor/**                      # silence every finding under a path
       # comments and blank lines are ignored

  2. inline marker on the offending source line:
       risky_call()   # debugmaster: ignore[py-shell-true]
       risky_call()   # debugmaster: ignore            (any rule on this line)
       risky_call()   // debugmaster: ignore[js-loose-eq]

Suppression never hides a *count*: `filter_findings` returns how many were
muted, so a clean report can't be faked by over-muting — the audit prints it.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

try:
    from . import common
except ImportError:
    import common

IGNORE_FILE = ".debugmaster-ignore"
INLINE = re.compile(r"(?:#|//)\s*debugmaster:\s*ignore(?:\[([\w,\- ]+)\])?", re.I)


def load_rules(repo: Path) -> list[tuple[str, str]]:
    """Parse `.debugmaster-ignore` into (path_glob, rule_id) pairs.
    rule_id '*' = any rule; path_glob '*' = any path."""
    f = Path(repo) / IGNORE_FILE
    if not f.exists():
        return []
    rules: list[tuple[str, str]] = []
    for raw in f.read_text(errors="ignore").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" in line:
            glob, rid = line.rsplit(":", 1)
            rules.append((glob.strip() or "*", rid.strip() or "*"))
        elif "/" in line or "*" in line or "." in line:
            rules.append((line, "*"))  # bare path glob
        else:
            rules.append(("*", line))  # bare rule id
    return rules


def _glob_match(relpath: str, glob: str) -> bool:
    if glob == "*":
        return True
    # fnmatch '*' spans '/', so legacy/** and legacy/* both cover nested paths
    return fnmatch.fnmatch(relpath, glob) or fnmatch.fnmatch(
        relpath, glob.rstrip("/*") + "/*"
    )


def _file_matches(rules, relpath: str, rule_id: str) -> bool:
    for glob, rid in rules:
        if rid in ("*", rule_id) and _glob_match(relpath, glob):
            return True
    return False


def _inline_suppresses(line: str, rule_id: str) -> bool:
    m = INLINE.search(line)
    if not m:
        return False
    ids = m.group(1)
    if not ids:  # bare "ignore" -> any rule on this line
        return True
    return rule_id in {x.strip() for x in ids.split(",")}


def filter_findings(repo: Path, findings: list):
    """Return (kept, suppressed_count). Applies file-glob rules + inline markers."""
    repo = Path(repo)
    rules = load_rules(repo)
    line_cache: dict[str, list[str]] = {}
    kept, suppressed = [], 0
    for f in findings:
        if _file_matches(rules, f.file, f.rule_id):
            suppressed += 1
            continue
        if f.line and f.line > 0:
            lines = line_cache.get(f.file)
            if lines is None:
                lines = common.read_lines(repo / f.file)
                line_cache[f.file] = lines
            if 0 < f.line <= len(lines) and _inline_suppresses(
                lines[f.line - 1], f.rule_id
            ):
                suppressed += 1
                continue
        kept.append(f)
    return kept, suppressed
