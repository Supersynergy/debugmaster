"""LLM triage — a second opinion on the top suspects, local and optional.

Heuristic + learned-precision ranking is fast but blind to context a human reads in
a second ("that bare-except is in a best-effort cache write — fine"). This asks a
LOCAL model (Ollama) to judge each top finding REAL vs FALSE-POSITIVE with a one-line
reason, then annotates (never silently drops) so noise can be filtered with eyes-open.

Zero hard dependency: stdlib urllib to http://localhost:11434. If the daemon is down
or no model is pulled, triage is skipped and the findings pass through untouched.
Model: $DEBUGMASTER_TRIAGE_MODEL, else a small local instruct model if present.
"""

from __future__ import annotations

import contextlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

try:
    from . import common
except ImportError:
    import common

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
# preference order for an auto-picked triage model (small, fast, instruct-y)
_PREFERRED = ("dolphin3", "llama3.2", "phi4", "qwen", "mistral", "dolphin")


def available() -> tuple[bool, str | None]:
    """(is_ollama_up, chosen_model). Cheap; never raises."""
    try:
        req = urllib.request.Request(f"{OLLAMA}/api/tags")
        with urllib.request.urlopen(req, timeout=2) as r:
            tags = json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return False, None
    models = [m.get("name", "") for m in tags.get("models", [])]
    if not models:
        return False, None
    forced = os.environ.get("DEBUGMASTER_TRIAGE_MODEL")
    if forced:
        return True, forced
    for pref in _PREFERRED:
        for m in models:
            if m.startswith(pref):
                return True, m
    return True, models[0]


def _ask(model: str, prompt: str, timeout: int = 40) -> str | None:
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 60},
        }
    ).encode()
    try:
        req = urllib.request.Request(
            f"{OLLAMA}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()).get("response", "").strip()
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None


def _context(repo: Path, file: str, line: int, span: int = 5) -> str:
    if not line:
        return ""
    lines = common.read_lines(repo / file)
    lo, hi = max(0, line - 1 - span), min(len(lines), line + span)
    out = []
    for i in range(lo, hi):
        mark = ">>" if i == line - 1 else "  "
        out.append(f"{mark}{i + 1}: {lines[i]}")
    return "\n".join(out)


_PROMPT = """You are a senior engineer triaging a static-analysis finding. Decide if it is a \
REAL bug or a FALSE POSITIVE in this context.

Finding: [{rule_id}] {severity} — {message}
Location: {file}:{line}
Code:
{ctx}

Reply with EXACTLY one line, nothing else:
REAL <0..1> <reason in <=12 words>
or
FAKE <0..1> <reason in <=12 words>"""


def _parse(resp: str) -> dict | None:
    if not resp:
        return None
    first = resp.strip().splitlines()[0].strip()
    up = first.upper()
    if up.startswith("REAL"):
        real = True
    elif up.startswith("FAKE") or up.startswith("FALSE"):
        real = False
    else:
        return None
    rest = first.split(None, 2)
    conf = 0.5
    if len(rest) > 1:
        with contextlib.suppress(ValueError):
            conf = max(0.0, min(1.0, float(rest[1])))
    reason = rest[2] if len(rest) > 2 else ""
    return {"real": real, "confidence": round(conf, 2), "reason": reason[:120]}


def triage(repo: Path, findings: list[dict], *, max_n: int = 10) -> dict:
    """Annotate up to max_n findings with an LLM real/fake verdict. Returns
    {ok, model, triaged, likely_fake} — findings are mutated in place with a
    `triage` key. No-op (ok=False) when Ollama is unavailable."""
    repo = Path(repo)
    up, model = available()
    if not up:
        return {"ok": False, "reason": "ollama not available", "triaged": 0}
    triaged = 0
    likely_fake = 0
    for f in findings[:max_n]:
        ctx = _context(repo, f.get("file", ""), int(f.get("line", 0) or 0))
        prompt = _PROMPT.format(
            rule_id=f.get("rule_id", ""),
            severity=f.get("severity", ""),
            message=f.get("message", "")[:200],
            file=f.get("file", ""),
            line=f.get("line", 0),
            ctx=ctx or "(no source context)",
        )
        verdict = _parse(_ask(model, prompt))
        if verdict is not None:
            f["triage"] = verdict
            triaged += 1
            if not verdict["real"]:
                likely_fake += 1
    return {"ok": True, "model": model, "triaged": triaged, "likely_fake": likely_fake}


if __name__ == "__main__":
    print(json.dumps(dict(zip(("up", "model"), available()))))
