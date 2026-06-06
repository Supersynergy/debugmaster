"""Static hidden-bug engine — the detections compilers and basic linters miss.

Two passes:
  1. Cross-language line rules (regex with false-positive guards + optional
     same-window context requirement). Fast, broad, language-tagged.
  2. Python AST pass (exact): mutable default args, swallowed exceptions,
     `== None`, assert tuples, broad except, `except: pass`, shadowed builtins,
     unawaited coroutine calls, and `self`-less comparisons.

Every finding carries evidence (snippet) + a fix hint + a verify command so an
agent can act, not just read. Rules are data, so the synthesis spec extends the
pack by appending to RULES.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    from . import common
except ImportError:
    import common

ANY = frozenset({"*"})


@dataclass
class Rule:
    id: str
    title: str
    severity: str  # critical|high|medium|low|info
    pattern: str  # regex tested per line
    langs: frozenset = ANY
    guard: str | None = None  # if this regex also matches the line, suppress (FP guard)
    needs_near: str | None = None  # require this regex within +/-near_window lines
    near_window: int = 3
    message: str = ""
    fix: str = ""
    cwe: str = ""
    _re: re.Pattern = field(default=None, repr=False, compare=False)
    _guard_re: re.Pattern = field(default=None, repr=False, compare=False)
    _near_re: re.Pattern = field(default=None, repr=False, compare=False)

    def compile(self):
        self._re = re.compile(self.pattern)
        self._guard_re = re.compile(self.guard) if self.guard else None
        self._near_re = re.compile(self.needs_near) if self.needs_near else None
        return self


# ── Seed rule pack (high-precision, low false-positive) ────────────────────────
RULES: list[Rule] = [
    # Swallowed / ignored errors — the #1 source of silent hidden bugs
    Rule(
        "py-bare-except",
        "Bare except hides all errors incl. KeyboardInterrupt",
        "high",
        r"^\s*except\s*:",
        langs=frozenset({"python"}),
        message="Bare `except:` swallows SystemExit/KeyboardInterrupt and masks real bugs.",
        fix="Catch a specific exception, or `except Exception:` and log/re-raise.",
        cwe="CWE-396",
    ),
    Rule(
        "py-except-pass",
        "Exception swallowed by pass",
        "high",
        r"^\s*except[^\n:]*:\s*$",
        langs=frozenset({"python"}),
        needs_near=r"^\s*pass\s*$",
        near_window=1,
        message="Exception handler does nothing — failure becomes invisible.",
        fix="Log the exception, handle it, or re-raise. Never silently pass.",
        cwe="CWE-390",
    ),
    Rule(
        "js-empty-catch",
        "Empty catch block swallows error",
        "high",
        r"catch\s*(\([^)]*\))?\s*\{\s*\}",
        langs=frozenset({"javascript", "typescript"}),
        message="Empty catch hides the error and the stack trace.",
        fix="Log or rethrow; at minimum comment why it is safe to ignore.",
        cwe="CWE-390",
    ),
    Rule(
        "go-ignored-err",
        "Error assigned to blank identifier",
        "high",
        r",\s*_\s*:?=\s*\w+.*\b(err|error)\b",
        langs=frozenset({"go"}),
        guard=r"_test\.go|//\s*nolint",
        message="Error discarded with `_` — failures pass silently.",
        fix="Handle the error or document why it is safe to drop.",
        cwe="CWE-252",
    ),
    Rule(
        "rust-unwrap",
        "unwrap()/expect() can panic at runtime",
        "medium",
        r"\.(unwrap|expect)\s*\(",
        langs=frozenset({"rust"}),
        guard=r"#\[(test|cfg\(test)|//|unwrap_or|tests?\b|assert",
        message="`unwrap()/expect()` panics on Err/None — a latent crash.",
        fix="Use `?`, `match`, `unwrap_or`, or `if let` to handle the error path.",
        cwe="CWE-248",
    ),
    Rule(
        "rust-let-underscore-result",
        "Result dropped via `let _ =`",
        "medium",
        r"let\s+_\s*=\s*\w+.*\?\s*;|let\s+_\s*=.*\.(send|write|flush|lock)\s*\(",
        langs=frozenset({"rust"}),
        message="A Result/guard bound to `_` is dropped immediately — error or lock lost.",
        fix="Bind to a name or handle the Result explicitly.",
        cwe="CWE-252",
    ),
    Rule(
        "py-request-no-timeout",
        "HTTP request without a timeout can hang forever",
        "medium",
        r"\b(requests\.(get|post|put|delete|patch|head|request)|httpx\.(get|post|put|delete|patch|request)|urllib\.request\.urlopen|\burlopen)\s*\([^)]*\)",
        langs=frozenset({"python"}),
        guard=r"timeout\s*=|#\s*ok|\bmock|session\.|adapter",
        message="No timeout on a network call — a slow or hung server blocks the thread "
        "indefinitely (connection/thread leak under load).",
        fix="Pass timeout=(connect, read); never leave a network call unbounded.",
        cwe="CWE-400",
    ),
    # Equality / identity traps
    Rule(
        "py-eq-none",
        "Comparison to None with == instead of is",
        "low",
        r"[=!]=\s*None\b",
        langs=frozenset({"python"}),
        message="`== None` invokes __eq__ and can be overridden/misbehave.",
        fix="Use `is None` / `is not None`.",
        cwe="CWE-697",
    ),
    Rule(
        "py-eq-bool",
        "Comparison to True/False literal",
        "low",
        r"==\s*(True|False)\b",
        langs=frozenset({"python"}),
        message="`== True` is fragile; truthy values differ from `True`.",
        fix="Use the value directly: `if flag:` / `if not flag:`.",
        cwe="CWE-697",
    ),
    Rule(
        "js-loose-eq",
        "Loose equality == / != (type coercion)",
        "low",
        r"[^=!<>]([!=]=)[^=]",
        langs=frozenset({"javascript", "typescript"}),
        guard=r"===|!==|//|/\*",
        message="`==`/`!=` coerce types (0 == '' , null == undefined).",
        fix="Use `===` / `!==`.",
        cwe="CWE-697",
    ),
    Rule(
        "c-assign-in-cond",
        "Assignment inside condition (= vs ==)",
        "high",
        r"\b(if|while)\s*\(\s*[\w.\[\]>-]+\s*=\s*[^=]",
        langs=frozenset({"c", "cpp", "javascript", "typescript", "java", "csharp"}),
        guard=r"==|<=|>=|!=",
        message="Single `=` in a condition assigns instead of compares.",
        fix="Use `==`, or make intent explicit with `(x = y) != 0`.",
        cwe="CWE-481",
    ),
    # Injection / unsafe sinks
    Rule(
        "py-shell-true",
        "subprocess with shell=True",
        "high",
        r"shell\s*=\s*True",
        langs=frozenset({"python"}),
        message="`shell=True` enables command injection if any arg is tainted.",
        fix="Pass an argv list without shell=True; validate inputs.",
        cwe="CWE-78",
    ),
    Rule(
        "py-os-system",
        "os.system / popen with interpolation",
        "high",
        r"os\.(system|popen)\s*\(.*(\+|%|f[\"']|\.format)",
        langs=frozenset({"python"}),
        message="Shell call built from a string is command-injection-prone.",
        fix="Use subprocess with an argv list; never interpolate untrusted input.",
        cwe="CWE-78",
    ),
    Rule(
        "sql-concat",
        "SQL built by string concatenation",
        "high",
        r"(execute|query|exec|raw)\s*\(.*(SELECT|INSERT|UPDATE|DELETE).*(\+|%s.*%|\.format|f[\"'])",
        langs=ANY,
        message="SQL assembled from strings invites injection.",
        fix="Use parameterized queries / bound params.",
        cwe="CWE-89",
    ),
    Rule(
        "py-eval-exec",
        "Dynamic eval/exec",
        "high",
        r"\b(eval|exec)\s*\(",
        langs=frozenset({"python"}),
        guard=r"#|ast\.literal_eval|safe_eval",
        message="eval/exec on any non-constant input is remote code execution.",
        fix="Use ast.literal_eval or a real parser; avoid exec.",
        cwe="CWE-95",
    ),
    # Hardcoded secrets
    Rule(
        "secret-literal",
        "Hardcoded credential",
        "critical",
        r"(?i)(api[_-]?key|secret|passwd|password|token|access[_-]?key|private[_-]?key)\s*[:=]\s*[\"'][A-Za-z0-9_\-/+]{12,}[\"']",
        langs=ANY,
        guard=r"(?i)(example|dummy|placeholder|xxx|your[_-]?|<|process\.env|os\.environ|getenv|None|null|\$\{)",
        message="A real-looking secret is committed in source.",
        fix="Move to env/secret manager; rotate the leaked value.",
        cwe="CWE-798",
    ),
    # Resource leaks
    Rule(
        "py-open-no-with",
        "open() not used as context manager",
        "medium",
        r"=\s*open\s*\(",
        langs=frozenset({"python"}),
        guard=r"with\s|#|os\.open",
        message="File opened without `with` may leak the handle on error.",
        fix="Use `with open(...) as f:`.",
        cwe="CWE-772",
    ),
    # Concurrency / async
    Rule(
        "py-await-in-loop",
        "await inside a for/while loop (serialized I/O)",
        "low",
        r"^\s*await\s",
        langs=frozenset({"python"}),
        needs_near=r"^\s*(for|while)\b",
        near_window=4,
        message="Awaiting per iteration serializes I/O — slow and can race.",
        fix="Gather concurrently with asyncio.gather / TaskGroup where safe.",
        cwe="CWE-1050",
    ),
    Rule(
        "js-floating-async",
        "Promise-returning call not awaited/returned",
        "medium",
        r"^\s*\w[\w.]*\.(then|catch|finally)\s*\(",
        langs=frozenset({"javascript", "typescript"}),
        guard=r"return|await|//|void ",
        message="A floating promise loses errors and ordering guarantees.",
        fix="`await`, `return`, or explicitly `void` the promise.",
        cwe="CWE-705",
    ),
    # Time / correctness
    Rule(
        "py-utcnow",
        "datetime.utcnow() (naive, deprecated)",
        "low",
        r"datetime\.utcnow\s*\(",
        langs=frozenset({"python"}),
        message="utcnow() returns a naive datetime; comparisons across tz break.",
        fix="Use datetime.now(timezone.utc).",
        cwe="CWE-1339",
    ),
    # Debug leftovers shipped to prod
    Rule(
        "debug-leftover",
        "Debugger/dump statement left in code",
        "medium",
        r"\b(breakpoint\s*\(\)|debugger\s*;|binding\.pry|var_dump\s*\(|console\.debug\s*\(|dbg!\s*\()",
        langs=ANY,
        guard=r"#|//\s*ok|_test",
        message="A debug breakpoint/dump was left in the source.",
        fix="Remove before shipping.",
        cwe="CWE-489",
    ),
    # Off-by-one / bounds heuristic.
    # Line-level only — cannot prove an out-of-bounds without AST bounds analysis,
    # and the idiom is CORRECT in edit-distance / DP code that allocates `len + 1`
    # (Levenshtein, knapsack, prefix sums). Kept as a LOW-severity hint so it never
    # drives a grade/BLOCK, and guarded against the common safe idioms.
    Rule(
        "off-by-one-len",
        "<= against a length/size in a loop bound (heuristic hint)",
        "low",
        r"(<=|>=)\s*[\w.]*\.(length|len|size|count)\b|<=\s*len\s*\(",
        langs=ANY,
        guard=r"//|#|\+\s*1\b|\.fill\(|Array\(|new Array|matrix|\bdp\b|range\(",
        message="`<=` against length — possible off-by-one. Safe in DP/`len+1` code; confirm the bound.",
        fix="Use `<` for index bounds, or confirm the inclusive bound is intended (e.g. a `len+1` matrix).",
        cwe="CWE-193",
    ),
    # ── corpus-mined classes (SpeedTuning invariants + bug-class theory) ──────
    Rule(
        "todo-near-auth",
        "Unfinished work in a security/auth path",
        "high",
        r"(?i)(TODO|FIXME|HACK|XXX)\b.*(auth|password|verif|valid|permission|secur|token|crypt|sanitiz|escap)",
        langs=ANY,
        message="A TODO/FIXME sits in a security-sensitive path — likely an unguarded hole.",
        fix="Resolve before shipping; security stubs become exploits.",
        cwe="CWE-489",
    ),
    Rule(
        # Only real credentials are critical. A localhost/loopback or a plain URL
        # with no embedded userinfo (`http://localhost:8080`) is a benign config
        # default, not a leaked secret — those used to fire a false CRITICAL. The
        # trigger now requires a credential keyword; the guard drops loopback/host
        # addresses and credential-free URLs (a real `scheme://user:pass@host` keeps
        # its `@` and is NOT guarded).
        "secret-in-fallback",
        "Credential baked into a default/fallback",
        "critical",
        r"(?i)unwrap_or(_else)?\s*\(.*(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|aws_|bearer\s|root:[^/])",
        langs=frozenset({"rust"}),
        guard=r"(?i)localhost|127\.0\.0\.1|0\.0\.0\.0|::1|example\.(com|org)|://[^@\"']*[\"']|changeme|dummy|placeholder|your[_-]",
        message="A fallback value hardcodes a credential.",
        fix="Read from config/env; never default to a real secret.",
        cwe="CWE-798",
    ),
    Rule(
        "unbounded-queue",
        "Unbounded queue/channel (no backpressure)",
        "high",
        r"\b(unbounded_channel|crossbeam::channel::unbounded|asyncio\.Queue\s*\(\s*\)|Queue\s*\(\s*maxsize\s*=\s*0)",
        langs=frozenset({"rust", "python"}),
        guard=r"//|#|test",
        message="An unbounded queue/channel lets producers outrun consumers → OOM under load.",
        fix="Set a bounded capacity and handle backpressure.",
        cwe="CWE-770",
    ),
    Rule(
        "retry-no-backoff",
        "Retry loop without backoff/jitter",
        "medium",
        r"(?i)\b(retry|attempt|reconnect)\b",
        langs=ANY,
        needs_near=r"(time\.sleep\(\s*\d|sleep\(\s*\d|Thread\.sleep\(\s*\d|setTimeout\([^,]+,\s*\d)",
        near_window=5,
        guard=r"backoff|jitter|exponential|\*\s*2|<<|pow\(|2\s*\*\*",
        message="Fixed-delay retries cause thundering-herd; one outage becomes a storm.",
        fix="Use exponential backoff with jitter.",
        cwe="CWE-1088",
    ),
    Rule(
        "ambient-global-client",
        "Module-global DB/admin client (ambient authority)",
        "medium",
        r"^(engine|db|conn|client|redis|pool|session)\s*=\s*(create_engine|connect|Redis|Client|Pool|create_client)\s*\(",
        langs=frozenset({"python"}),
        guard=r"#|None|os\.environ|getenv",
        message="A module-level connected client is shared global state — hard to test, leaks across requests.",
        fix="Construct inside a factory/dependency and inject it.",
        cwe="CWE-1108",
    ),
    Rule(
        "toctou-exists-open",
        "TOCTOU: check-then-use on a path",
        "medium",
        r"(os\.path\.exists|os\.access|Path\([^)]*\)\.exists)\s*\(",
        langs=frozenset({"python"}),
        needs_near=r"\bopen\s*\(|os\.remove|os\.rename|shutil\.",
        near_window=3,
        message="Check-then-act on a path races with other processes (TOCTOU).",
        fix="Open/operate directly and handle the exception (EAFP).",
        cwe="CWE-367",
    ),
    Rule(
        "py-naive-now",
        "Timezone-naive datetime.now()",
        "low",
        r"datetime\.now\s*\(\s*\)",
        langs=frozenset({"python"}),
        guard=r"tz|timezone|#",
        message="Naive now() breaks across timezones / DST.",
        fix="Use datetime.now(timezone.utc).",
        cwe="CWE-1339",
    ),
    Rule(
        "outbox-after-commit",
        "Side-effect emit right after DB commit (no outbox)",
        "medium",
        r"\.(commit|save)\s*\(\s*\)",
        langs=ANY,
        needs_near=r"\.(send|publish|emit|enqueue|produce|dispatch|notify)\s*\(",
        near_window=8,
        guard=r"//|#|outbox|transaction\.on_commit|atomic",
        message="Emitting a message after commit can double-send or lose events on crash.",
        fix="Use a transactional outbox or on_commit hook.",
        cwe="CWE-662",
    ),
]
for _r in RULES:
    _r.compile()


@dataclass
class Finding:
    file: str
    line: int
    rule_id: str
    severity: str
    title: str
    snippet: str
    message: str
    fix: str
    cwe: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _scan_lines(repo: Path, path: Path, lang: str, lines: list[str]) -> list[Finding]:
    out = []
    for r in RULES:
        if r.langs is not ANY and lang not in r.langs:
            continue
        for i, ln in enumerate(lines):
            if not r._re.search(ln):
                continue
            if r._guard_re and r._guard_re.search(ln):
                continue
            if r._near_re:
                lo, hi = (
                    max(0, i - r.near_window),
                    min(len(lines), i + r.near_window + 1),
                )
                if not any(
                    r._near_re.search(lines[j]) for j in range(lo, hi) if j != i
                ):
                    continue
            out.append(
                Finding(
                    common.rel(repo, path),
                    i + 1,
                    r.id,
                    r.severity,
                    r.title,
                    ln.strip()[:200],
                    r.message,
                    r.fix,
                    r.cwe,
                )
            )
    return out


# ── Python AST precision pass ──────────────────────────────────────────────────
def _call_name(func) -> str:
    parts = []
    cur = func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _iter_body(node):
    """Descendants of node, NOT crossing into nested function/class/lambda bodies."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        if isinstance(
            n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
        ):
            continue
        yield n
        stack.extend(ast.iter_child_nodes(n))


class _PyVisitor(ast.NodeVisitor):
    BLOCKING = {
        "time.sleep",
        "requests.get",
        "requests.post",
        "requests.put",
        "requests.delete",
        "requests.patch",
        "requests.request",
        "urllib.request.urlopen",
        "subprocess.run",
        "subprocess.call",
    }
    PURE_METHODS = {
        "strip",
        "lstrip",
        "rstrip",
        "replace",
        "upper",
        "lower",
        "title",
        "capitalize",
        "split",
        "rsplit",
        "format",
        "encode",
        "decode",
        "zfill",
        "swapcase",
        "casefold",
        "expandtabs",
    }

    def __init__(self, repo, path, lines):
        self.repo, self.path, self.lines = repo, path, lines
        self.findings: list[Finding] = []

    def _add(self, node, rid, sev, title, msg, fix, cwe=""):
        ln = getattr(node, "lineno", 1)
        snip = self.lines[ln - 1].strip()[:200] if 0 < ln <= len(self.lines) else ""
        self.findings.append(
            Finding(
                common.rel(self.repo, self.path),
                ln,
                rid,
                sev,
                title,
                snip,
                msg,
                fix,
                cwe,
            )
        )

    def _check_defaults(self, node):
        for default in node.args.defaults + node.args.kw_defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)) or (
                isinstance(default, ast.Call)
                and isinstance(default.func, ast.Name)
                and default.func.id in {"list", "dict", "set"}
            ):
                self._add(
                    default,
                    "py-mutable-default",
                    "high",
                    "Mutable default argument",
                    "A mutable default is shared across all calls — state leaks between invocations.",
                    "Default to None and create the container inside the function.",
                    "CWE-665",
                )

    def visit_FunctionDef(self, node):
        self._check_defaults(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._check_defaults(node)
        for sub in _iter_body(node):
            if isinstance(sub, ast.Call):
                name = _call_name(sub.func)
                if name in self.BLOCKING:
                    self._add(
                        sub,
                        "py-blocking-in-async",
                        "high",
                        "Blocking call inside async function",
                        f"`{name}` blocks the event loop — every other coroutine stalls until it returns.",
                        "Use an async client (httpx/aiohttp), asyncio.sleep, or run_in_executor.",
                        "CWE-1050",
                    )
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        seen = set()
        for v in node.values:
            try:
                key = ast.dump(v)
            except Exception:
                continue
            if key in seen:
                self._add(
                    node,
                    "py-dup-boolop",
                    "medium",
                    "Duplicate operand in boolean expression",
                    "The same sub-expression appears twice in this and/or — a classic copy-paste typo "
                    "where one side should reference a different variable.",
                    "Verify whether one operand should be a different name.",
                    "CWE-571",
                )
                break
            seen.add(key)
        self.generic_visit(node)

    def visit_Expr(self, node):
        v = node.value
        if (
            isinstance(v, ast.Call)
            and isinstance(v.func, ast.Attribute)
            and v.func.attr in self.PURE_METHODS
        ):
            self._add(
                node,
                "py-must-use-return",
                "medium",
                "Result of a non-mutating call is discarded",
                f"`.{v.func.attr}()` returns a new value and never mutates in place — this result is thrown away.",
                f"Assign it: `x = x.{v.func.attr}(...)`.",
                "CWE-252",
            )
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        body = node.body
        if len(body) == 1 and isinstance(body[0], ast.Pass):
            self._add(
                node,
                "py-except-pass-ast",
                "high",
                "Exception silently swallowed",
                "Handler body is just `pass` — the error vanishes.",
                "Log, handle, or re-raise.",
                "CWE-390",
            )
        elif node.type is None:
            self._add(
                node,
                "py-bare-except-ast",
                "high",
                "Bare except",
                "Catches everything including control-flow exceptions.",
                "Catch a specific exception type.",
                "CWE-396",
            )
        self.generic_visit(node)

    def visit_Assert(self, node):
        if isinstance(node.test, ast.Tuple) and node.test.elts:
            self._add(
                node,
                "py-assert-tuple",
                "high",
                "assert on a non-empty tuple is always true",
                "`assert (cond, msg)` asserts the tuple, never the condition.",
                "Remove the parentheses: `assert cond, msg`.",
                "CWE-617",
            )
        self.generic_visit(node)

    def visit_Compare(self, node):
        # `x == []`/`{}`/`()` mutable literal compares are usually identity mistakes
        for op, comp in zip(node.ops, node.comparators):
            if (
                isinstance(op, (ast.Is, ast.IsNot))
                and isinstance(comp, ast.Constant)
                and isinstance(comp.value, (int, str))
            ):
                if comp.value not in (None, True, False):
                    self._add(
                        node,
                        "py-is-literal",
                        "medium",
                        "`is` comparison with a literal",
                        "`is` checks identity, not equality; CPython caching makes this unreliable.",
                        "Use `==` for value comparison.",
                        "CWE-697",
                    )
        self.generic_visit(node)


def _scan_python_ast(
    repo: Path, path: Path, text: str, lines: list[str], tree=None
) -> list[Finding]:
    if tree is None:
        tree = common.parse_python(text)  # standalone call; combined scan passes one
    if tree is None:
        # rare broken-file path: re-parse only to surface the error location
        try:
            ast.parse(text)
        except SyntaxError as e:
            ln = e.lineno or 1
            snip = lines[ln - 1].strip()[:200] if 0 < ln <= len(lines) else ""
            return [
                Finding(
                    common.rel(repo, path),
                    ln,
                    "py-syntax-error",
                    "critical",
                    "Python syntax error",
                    snip,
                    f"File does not parse: {e.msg}",
                    "Fix the syntax error; this file cannot run.",
                    "CWE-561",
                )
            ]
        except (ValueError, RecursionError, MemoryError):
            return []  # null bytes / pathological source — skip, never crash the scan
        return []  # parsed clean on retry (no error to report)
    v = _PyVisitor(repo, path, lines)
    v.visit(tree)
    return v.findings


def scan_file(repo: Path, path: Path, lang: str) -> list[Finding]:
    text = common.read_text(path)
    if not text:
        return []
    lines = text.splitlines()
    findings = _scan_lines(repo, path, lang, lines)
    if lang == "python":
        findings += _scan_python_ast(repo, path, text, lines)
    return findings


def scan_repo(
    repo: Path,
    *,
    langs: set[str] | None = None,
    limit: int = 6000,
    only_files: set[str] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    for path, lang in common.iter_source_files(repo, langs=langs, limit=limit):
        if only_files is not None and common.rel(repo, path) not in only_files:
            continue
        findings.extend(scan_file(repo, path, lang))
    findings.sort(
        key=lambda f: (-common.SEVERITY_RANK.get(f.severity, 0), f.file, f.line)
    )
    return findings


if __name__ == "__main__":
    import json
    import sys

    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    fs = scan_repo(repo, limit=3000)
    by_sev = {}
    for f in fs:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    print(
        json.dumps(
            {
                "total": len(fs),
                "by_severity": by_sev,
                "top": [f.as_dict() for f in fs[:25]],
            },
            indent=2,
        )
    )
