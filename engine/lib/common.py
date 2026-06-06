"""Shared helpers for debugmaster analysis engines (pure stdlib)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Directories that never contain first-party source worth analyzing.
SKIP_DIRS = {
    "node_modules",
    "target",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    "vendor",
    "vendors",
    "data",
    ".git",
    ".grepgod",
    ".codegraph",
    ".debugmaster",
    ".repovista",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "coverage",
    ".gradle",
    ".idea",
    ".vscode",
    "Pods",
    "DerivedData",
    ".terraform",
    "bin",
    "obj",
    ".tox",
    "site-packages",
}

# Extension -> canonical language id used across engines.
EXT_LANG = {
    ".py": "python",
    ".pyi": "python",
    ".rs": "rust",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".m": "objc",
    ".mm": "objc",
    ".rb": "ruby",
    ".php": "php",
    ".pl": "perl",
    ".pm": "perl",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".sql": "sql",
    ".lua": "lua",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".jl": "julia",
    ".r": "r",
    ".R": "r",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".clj": "clojure",
    ".sol": "solidity",
    ".zig": "zig",
    ".nim": "nim",
    ".cr": "crystal",
    ".tf": "terraform",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".vue": "vue",
    ".svelte": "svelte",
    ".astro": "astro",
}

TEXT_EXTS = set(EXT_LANG) | {
    ".md",
    ".json",
    ".toml",
    ".cfg",
    ".ini",
    ".txt",
    ".css",
    ".scss",
    ".html",
    ".xml",
    ".env",
    ".dockerfile",
    ".gradle",
    ".properties",
}

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


MAX_FILE_BYTES = _env_int("DEBUGMASTER_MAX_FILE_BYTES", 1500000)


def _augment_path() -> None:
    """Language package managers drop binaries in well-known dirs that a
    minimal/non-login shell PATH often omits: `go install` -> ~/go/bin,
    `bun add -g` -> ~/.bun/bin, `cargo install` -> ~/.cargo/bin. Append them so
    BOTH detection (have) and execution (run) find tools like staticcheck,
    golangci-lint, oxlint, and promptfoo regardless of how the caller's PATH was
    set. Append (never prepend) so it cannot shadow a tool the user put earlier."""
    home = Path.home()
    extra = [
        home / "go" / "bin",
        home / ".bun" / "bin",
        home / ".cargo" / "bin",
        home / ".local" / "bin",
    ]
    parts = os.environ.get("PATH", "").split(os.pathsep)
    add = [str(d) for d in extra if d.is_dir() and str(d) not in parts]
    if add:
        os.environ["PATH"] = os.pathsep.join(parts + add)


_augment_path()


def run(cmd, cwd=None, timeout=None, check=False, env=None):
    """Run a command, capturing text output. Never raises on non-zero unless check.
    `env` (a dict) is merged onto the current environment, not replacing it — used
    to cap a scanner's internal thread count so concurrent scanners don't oversubscribe."""
    run_env = None
    if env:
        run_env = dict(os.environ)
        run_env.update(env)
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=check,
        timeout=timeout,
        env=run_env,
    )


def worker_count(fraction: float = 0.75, *, cap: int | None = None) -> int:
    """How many workers to use for parallel work — by default ~75% of the cores, so
    a hunt leaves headroom for the editor/IDE/CI and never pins the whole machine.

    Overridable per environment:
      DEBUGMASTER_WORKERS        absolute worker count (wins if set)
      DEBUGMASTER_CPU_FRACTION   fraction of cores, e.g. 0.7 (default 0.75)
    Always clamped to [1, cpu_count]."""
    n = os.cpu_count() or 1
    forced = os.environ.get("DEBUGMASTER_WORKERS")
    if forced and forced.isdigit() and int(forced) > 0:
        w = int(forced)
    else:
        try:
            frac = float(os.environ.get("DEBUGMASTER_CPU_FRACTION", fraction))
        except (TypeError, ValueError):
            frac = fraction
        frac = min(max(frac, 0.05), 1.0)
        w = max(1, round(n * frac))
    if cap:
        w = min(w, cap)
    return max(1, min(w, n))


def thread_cap_env(threads: int) -> dict:
    """Env vars that cap the internal thread pools of common scanners (ruff/biome/
    clippy use Rayon, native tools use OpenMP). Set when launching scanners in
    parallel so N concurrent scanners × their own threads stays within budget."""
    t = str(max(1, threads))
    return {
        "RAYON_NUM_THREADS": t,
        "OMP_NUM_THREADS": t,
        "RUST_THREADS": t,
        "TOKIO_WORKER_THREADS": t,
    }


def have(name: str) -> bool:
    return shutil.which(name) is not None


def lang_of(path) -> str | None:
    return EXT_LANG.get(Path(path).suffix)


def is_skipped(rel_parts) -> bool:
    return any(part in SKIP_DIRS for part in rel_parts)


def iter_source_files(repo: Path, *, langs: set[str] | None = None, limit: int = 50000):
    """Yield (path, language) for first-party source files, skipping junk dirs."""
    count = 0
    for dp, dirnames, filenames in os.walk(repo, onerror=lambda _e: None):
        dirnames[:] = [
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            lang = EXT_LANG.get(Path(name).suffix)
            if lang is None:
                continue
            if langs and lang not in langs:
                continue
            p = Path(dp) / name
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield p, lang
            count += 1
            if count >= limit:
                return


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")
    except OSError:
        return ""


def read_lines(path: Path) -> list[str]:
    return read_text(path).splitlines()


def parse_python(text: str):
    """Safe Python parse: returns the module, or None on any parse error.

    Used by the combined static scan so a `.py` file is parsed once and the single
    tree is shared by both engines (bughunt + bizlogic) for that file, then dropped
    — no per-tree retention, so peak memory stays flat on large repos."""
    import ast

    try:
        return ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None


def rel(repo: Path, path: Path) -> str:
    try:
        return str(path.relative_to(repo))
    except ValueError:
        return str(path)


def git_ok(repo: Path) -> bool:
    return (repo / ".git").exists()


def color(s: str, code: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return s
    codes = {
        "red": "31",
        "yellow": "33",
        "green": "32",
        "cyan": "36",
        "dim": "2",
        "bold": "1",
        "mag": "35",
    }
    return f"\033[{codes.get(code, '0')}m{s}\033[0m"


def sev_mark(sev: str) -> str:
    return {
        "critical": color("CRIT", "red"),
        "high": color("HIGH", "red"),
        "medium": color("MED", "yellow"),
        "low": color("LOW", "cyan"),
        "info": color("INFO", "dim"),
    }.get(sev, sev.upper())
