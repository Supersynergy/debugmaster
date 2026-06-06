"""MCP (Model Context Protocol) server over stdio — exposes debugmaster's engine as
agent tools for Claude Code / Codex / Cursor / any MCP client.

The market moved into the agent: the trending debug/code-intel tools are all
MCP-native. debugmaster already has the engine (static + business-logic + history +
runtime profiling); this is the socket that puts it where agents can reach it.

Pure-stdlib, newline-delimited JSON-RPC 2.0 — no SDK dependency, matching the
zero-dep core. Wire it into Claude Code with:

    { "mcpServers": { "debugmaster": { "command": "debugmaster", "args": ["mcp"] } } }
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from . import audit, flows, hunt
    from . import profile as prof
except ImportError:
    import profile as prof

    import audit
    import flows
    import hunt

SERVER_VERSION = "0.6.0"
DEFAULT_PROTOCOL = "2025-06-18"

TOOLS = [
    {
        "name": "debugmaster_hunt",
        "description": "Find the smallest hidden bugs in a repo, ranked by severity × "
        "learned-precision × blast-radius. Includes business-logic bugs linters miss "
        "(IDOR, SSRF, mass-assignment, oversell races, money-as-float).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "repo path (default '.')"},
                "profile": {
                    "type": "string",
                    "enum": ["fast", "deep"],
                    "default": "fast",
                },
                "dirty": {"type": "boolean", "description": "only git-dirty files"},
                "fuse": {
                    "type": "boolean",
                    "default": True,
                    "description": "run external scanners",
                },
            },
        },
    },
    {
        "name": "debugmaster_audit",
        "description": "Graded whole-repo health audit: A–F per dimension (security, "
        "business-logic, correctness, reliability, maintainability, test-coverage) plus "
        "a release-readiness verdict SHIP / FIX-FIRST / BLOCK.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "profile": {
                    "type": "string",
                    "enum": ["fast", "deep"],
                    "default": "fast",
                },
                "fuse": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "debugmaster_review",
        "description": "'Is this change safe?' — hunt scoped to the diff, returned as a PR "
        "verdict (APPROVE / COMMENT / REQUEST-CHANGES) with forgotten-edit suspects.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "base": {
                    "type": "string",
                    "description": "base ref e.g. main; default = working tree",
                },
            },
        },
    },
    {
        "name": "debugmaster_explain",
        "description": "Localize a stacktrace into the repo (deepest in-repo frame first) "
        "with code context and the ranked suspects near it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": {"type": "string", "description": "the stacktrace text"},
                "repo": {"type": "string"},
            },
            "required": ["trace"],
        },
    },
    {
        "name": "debugmaster_profile",
        "description": "Runtime diagnostician: run a command (or attach to a PID), sample "
        "the process tree, and diagnose memory/fd/thread/gpu leaks, cpu bottlenecks, and "
        "orphaned processes — with a graded verdict and fix hints.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "argv to run and profile, e.g. ['python3','app.py']",
                },
                "pid": {
                    "type": "integer",
                    "description": "attach to a running pid instead",
                },
                "duration": {
                    "type": "integer",
                    "default": 20,
                    "description": "seconds (pid mode)",
                },
                "interval": {"type": "number", "default": 0.5},
            },
        },
    },
]
_TOOL_NAMES = {t["name"] for t in TOOLS}


def _call_tool(name: str, args: dict) -> str:
    repo = Path(args.get("repo", ".")).expanduser().resolve()
    fuse = args.get("fuse", True)
    if name == "debugmaster_hunt":
        rep = hunt.hunt(
            repo,
            profile=args.get("profile", "fast"),
            fuse=fuse,
            dirty_only=bool(args.get("dirty")),
        )
        return hunt.markdown(rep)
    if name == "debugmaster_audit":
        return audit.markdown(
            audit.audit(repo, profile=args.get("profile", "fast"), fuse=fuse)
        )
    if name == "debugmaster_review":
        return json.dumps(flows.review(repo, base=args.get("base") or None), indent=2)
    if name == "debugmaster_explain":
        return json.dumps(flows.explain(repo, args.get("trace", "")), indent=2)
    if name == "debugmaster_profile":
        cmd = args.get("command")
        if cmd:
            r = prof.profile_command(list(cmd), interval=args.get("interval", 0.5))
        elif args.get("pid"):
            r = prof.profile_pid(
                int(args["pid"]),
                duration=args.get("duration", 20),
                interval=args.get("interval", 0.5),
            )
        else:
            return "error: provide `command` (argv array) or `pid`"
        return prof.markdown(r)
    raise KeyError(name)


def handle(msg: dict) -> dict | None:
    """Dispatch one JSON-RPC message. Returns a response dict, or None for
    notifications (which take no reply)."""
    mid = msg.get("id")
    method = msg.get("method")

    if method == "initialize":
        pv = (msg.get("params") or {}).get("protocolVersion") or DEFAULT_PROTOCOL
        return _ok(
            mid,
            {
                "protocolVersion": pv,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "debugmaster", "version": SERVER_VERSION},
            },
        )
    if (
        method in ("notifications/initialized", "notifications/cancelled")
        or mid is None
    ):
        return None
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name not in _TOOL_NAMES:
            return _content(mid, f"unknown tool: {name}", is_error=True)
        try:
            return _content(mid, _call_tool(name, args))
        except (
            Exception
        ) as e:  # a tool failure is reported in-band, never crashes the server
            return _content(
                mid, f"debugmaster error: {type(e).__name__}: {e}", is_error=True
            )
    return _err(mid, -32601, f"method not found: {method}")


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, message):
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _content(mid, text, *, is_error=False):
    return _ok(mid, {"content": [{"type": "text", "text": text}], "isError": is_error})


def serve(stdin=None, stdout=None) -> int:
    """Read newline-delimited JSON-RPC from stdin, write responses to stdout."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp is not None:
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(serve())
