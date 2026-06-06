"""Per-file code metrics — features for the defect-risk model (pure stdlib).

Cheap structural proxies that correlate with defects: size, cyclomatic-style
branchiness, nesting depth, longest function, comment ratio, and unfinished
markers. No external tools; works on every language by token heuristics, with an
exact AST path for Python.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

try:
    from . import common
except ImportError:
    import common

BRANCH_RE = re.compile(
    r"\b(if|elif|for|while|case|when|catch|except)\b|&&|\|\||\?\s*[^?:\n]+:"
)
TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG|WTF|TEMP|KLUDGE)\b")
DEF_RE = {
    "python": re.compile(r"^\s*(def|async def)\s"),
    "rust": re.compile(r"^\s*(pub\s+)?(async\s+)?fn\s"),
    "go": re.compile(r"^\s*func\s"),
    "javascript": re.compile(r"\bfunction\b|=>\s*\{|^\s*\w+\s*\([^)]*\)\s*\{"),
    "typescript": re.compile(
        r"\bfunction\b|=>\s*\{|^\s*(public|private|protected)?\s*\w+\s*\([^)]*\)\s*[:{]"
    ),
}


def _indent_depth(line: str) -> int:
    stripped = line.lstrip(" \t")
    if not stripped:
        return 0
    lead = line[: len(line) - len(stripped)]
    return lead.count("\t") + (len(lead) - lead.count("\t")) // 4


def file_metrics(path: Path, lang: str) -> dict:
    text = common.read_text(path)
    lines = text.splitlines()
    loc = len(lines)
    if loc == 0:
        return {
            "loc": 0,
            "complexity": 0,
            "max_nest": 0,
            "longest_fn": 0,
            "comment_ratio": 0.0,
            "todos": 0,
            "imports": 0,
        }
    branches = 0
    comments = 0
    todos = 0
    max_nest = 0
    imports = 0
    for ln in lines:
        s = ln.strip()
        if s.startswith(("#", "//", "*", "/*", "--", '"""', "'''")):
            comments += 1
        branches += len(BRANCH_RE.findall(ln))
        if TODO_RE.search(ln):
            todos += 1
        max_nest = max(max_nest, _indent_depth(ln))
        if (
            s.startswith(("import ", "from ", "use ", "#include", "require("))
            or " require(" in s
        ):
            imports += 1

    longest_fn = _longest_function(lines, lang)
    if lang == "python":
        cc = _python_cyclomatic(text)
        if cc is not None:
            branches = cc
    return {
        "loc": loc,
        "complexity": branches,
        "max_nest": max_nest,
        "longest_fn": longest_fn,
        "comment_ratio": round(comments / loc, 3),
        "todos": todos,
        "imports": imports,
    }


def _longest_function(lines: list[str], lang: str) -> int:
    pat = DEF_RE.get(lang)
    if not pat:
        return 0
    starts = [i for i, ln in enumerate(lines) if pat.search(ln)]
    if not starts:
        return 0
    longest = 0
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        longest = max(longest, end - start)
    return longest


def _python_cyclomatic(text: str) -> int | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    count = 1
    for node in ast.walk(tree):
        if isinstance(
            node,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.ExceptHandler,
                ast.With,
                ast.AsyncWith,
                ast.Assert,
                ast.comprehension,
            ),
        ):
            count += 1
        elif isinstance(node, ast.BoolOp):
            count += len(node.values) - 1
        elif isinstance(node, ast.Try):
            count += len(node.handlers)
    return count


def risk_proxy(m: dict) -> float:
    """Normalize metrics into a 0-100 structural-risk proxy (bigger = riskier)."""
    if m["loc"] == 0:
        return 0.0
    import math

    size = min(math.log1p(m["loc"]) / math.log1p(2000), 1.0)
    cx = min(m["complexity"] / 120.0, 1.0)
    nest = min(m["max_nest"] / 8.0, 1.0)
    fn = min(m["longest_fn"] / 150.0, 1.0)
    todo = min(m["todos"] / 8.0, 1.0)
    low_comment = 1.0 - min(m["comment_ratio"] * 4, 1.0)
    score = 100.0 * (
        0.25 * cx + 0.2 * nest + 0.2 * fn + 0.15 * size + 0.1 * todo + 0.1 * low_comment
    )
    return round(score, 1)


def repo_metrics(repo: Path, *, limit: int = 6000) -> dict[str, dict]:
    out = {}
    for path, lang in common.iter_source_files(repo, limit=limit):
        m = file_metrics(path, lang)
        m["lang"] = lang
        m["risk_proxy"] = risk_proxy(m)
        out[common.rel(repo, path)] = m
    return out


def metrics_for(repo: Path, rel_files) -> dict[str, dict]:
    """Compute metrics for a specific set of repo-relative files only.

    A hunt scores file-risk only for *candidate* files (those with findings, dirty,
    or historically risky), so computing metrics for the whole repo is wasted work —
    on a 1000+ file repo that is several seconds of pure overhead. This computes the
    same per-file metrics but only for the files actually scored."""
    out = {}
    for relp in rel_files:
        path = repo / relp
        lang = common.lang_of(relp)
        if not lang or not path.is_file():
            continue
        m = file_metrics(path, lang)
        m["lang"] = lang
        m["risk_proxy"] = risk_proxy(m)
        out[relp] = m
    return out


if __name__ == "__main__":
    import json
    import sys

    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    mm = repo_metrics(repo, limit=2000)
    top = sorted(mm.items(), key=lambda kv: kv[1]["risk_proxy"], reverse=True)[:12]
    print(
        json.dumps(
            [
                {
                    "file": f,
                    **{
                        k: m[k]
                        for k in (
                            "lang",
                            "loc",
                            "complexity",
                            "max_nest",
                            "longest_fn",
                            "risk_proxy",
                        )
                    },
                }
                for f, m in top
            ],
            indent=2,
        )
    )
