# debugmaster

Rust-first bug hunter for agents and maintainers who need a fast, portable
second opinion before code ships. One tool, one command: a native Rust core
(`hunt`, `sessions`, `doctor`) plus a deeper analysis **engine bundled inside the
tool** for everything else (`audit`, `review`, `profile`, `mcp`, `fusion`, …).
The engine runs through `python3` — there is **no second tool to install**, no
`pip`, no separate package on your `PATH`.

Repository: https://github.com/Supersynergy/debugmaster

```bash
cargo install --path .
debugmaster hunt .
```

## Quick Start

```bash
git clone https://github.com/Supersynergy/debugmaster.git
cd debugmaster
cargo build --release
./target/release/debugmaster hunt .
./target/release/debugmaster sessions -q codex
```

Useful commands:

```bash
debugmaster hunt .              # ranked findings, human output
debugmaster hunt . --json       # machine-readable report
debugmaster hunt . -n 30        # top 30 findings
debugmaster sessions -q codex   # search Codex/Claude JSONL sessions
debugmaster doctor              # native: which layers (core + engine + scanners) are live
debugmaster hunt . --deep       # full engine pipeline: fusion + git-history + learned ranking
debugmaster audit .             # graded SHIP/FIX-FIRST/BLOCK verdict (bundled engine)
```

`hunt` (native) is the fast Rust scan. `hunt --deep` and the deep commands run the
bundled engine; both ship in this one repo. The native scan and the deep pipeline
are an explicit choice, not two silently-diverging code paths.

## What It Finds

The value isn't another syntax linter — it's the **business-logic** detectors that
read *intent*, built on exact tree-sitter function/call spans + intent guards:

| Rule | Catches |
|---|---|
| `biz-idor-missing-ownership` | endpoint loads a record by id with no ownership/authz check |
| `biz-mass-assignment` | `Model(**request.json)` — over-posting / privilege fields |
| `biz-webhook-no-signature` | a webhook that never verifies the sender signature (forgeable events) |
| `biz-client-controlled-price` | charge amount taken from the request (price tampering) |
| `biz-refund-client-amount` | refund amount from the request (refund fraud) |
| `biz-idempotency-missing` | a charge with no idempotency key (double-charge on retry) |
| `biz-float-money` | money cast to float (precision loss) |

Each detector is precise: it stays **silent** when the guard is present (ownership
check, `construct_event`, explicit kwargs, server-side amount lookup, `Decimal`).

## Static Rule Pack

`secret-literal`, `sql-concat`, `py-shell-true`, `py-eval-exec`, `py-bare-except`,
`py-eq-none`, `py-request-no-timeout`, `js-loose-eq`, `js-empty-catch`,
`rust-unwrap`, `go-ignored-err`, `debug-leftover`. Languages by extension;
`.gitignore`-aware walk; `guard` regexes keep false positives down.

## Why Rust

- **Distribution.** The native core is one static binary — no interpreter for
  `hunt`/`sessions`/`doctor`. The deep engine ships *with* the tool and runs on
  the system `python3`; nothing extra to `pip install`, no second tool on `PATH`.
- **True parallelism.** The native scan is `rayon` over cores — no GIL, no
  process-pool overhead.
- **Exact spans.** tree-sitter gives real function/call boundaries, so the
  business-logic guards run on precise node text, not line heuristics.
- **Session visibility.** `debugmaster sessions` reads `~/.codex/sessions` and
  `~/.claude/projects` JSONL transcripts directly, including nested Codex rollout
  paths.
- **Bundled engine.** Deep commands run `engine/bin/debugmaster` (resolved from
  `$DEBUGMASTER_ENGINE`, `~/.debugmaster/engine`, the source tree, or next to the
  binary). The full Python pipeline — fusion, git-history, learned ranking,
  profiler, MCP server — is carried inside this one repo, not a sibling project.

## Verification

```bash
cargo build --release      # → target/release/debugmaster (single binary)
cargo test                 # unit tests (detectors + FP guards)
cargo clippy --all-targets -- -D warnings
debugmaster hunt . --json
```

## Architecture

Native Rust (no interpreter): `hunt`, `sessions`, `doctor`.

Bundled engine (`engine/`, runs on `python3`, no separate install): `hunt --deep`,
`fusion`, `learn-feedback`, `learn-stats`, `scan-bugs`, `mcp`, `checks`, `watch`,
`regress`, `profile`, `audit`, `review`, `bisect`, `explain`, `fix-verify`,
`install-hooks`, `scan`, `repo`, `top-risk`, `codex-brief`, `catalog`, `engines`,
`flows`, `init`, `engines-install`, `autofix`, `mine`, `batch`, `init-ci`, `all`.

Engine commands are not a separate binary — the Rust front-end resolves the
bundled engine and runs it for you. `debugmaster doctor` reports whether the
engine and `python3` are reachable.

## Release State

- Current release: `v0.9.0` — single tool; the former `debugmastery` Python
  project is folded in as the bundled `engine/`.
- Legacy backup branches:
  - `python-main-github-before-rust`
  - `python-main-gitea-before-rust`

## License

MIT. See [LICENSE](LICENSE).
