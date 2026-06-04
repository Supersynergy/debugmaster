# debugmaster

Rust-first bug hunter for agents and maintainers who need a fast, portable
second opinion before code ships. `debugmaster` is a single binary that combines
static rules, business-logic detectors, and Codex/Claude session search; the
old Python command surface remains available through `debugmastery`.

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
debugmaster doctor              # forwarded to debugmastery while being ported
```

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

- **Distribution.** One static binary. No Python, no `pip`, no version drift in CI.
- **True parallelism.** The repo scan is `rayon` over cores — no GIL, no process-pool
  overhead (the Python build had to fork around the GIL).
- **Exact spans.** tree-sitter gives real function/call boundaries, so the
  business-logic guards run on precise node text, not line heuristics.
- **Session visibility.** `debugmaster sessions` reads `~/.codex/sessions` and
  `~/.claude/projects` JSONL transcripts directly, including nested Codex rollout
  paths.
- **Parity bridge.** Python-era commands are still usable through the Rust binary:
  unknown subcommands are forwarded to `debugmastery` with the same arguments.

## Verification

```bash
cargo build --release      # → target/release/debugmaster (single binary)
cargo test                 # unit tests (detectors + FP guards)
cargo clippy --all-targets -- -D warnings
debugmaster hunt . --json
```

## Parity

Native Rust today: `hunt`, `sessions`.

Forwarded through `debugmastery` today: `fusion`, `learn-feedback`, `learn-stats`,
`scan-bugs`, `doctor`, `mcp`, `checks`, `watch`, `regress`, `profile`, `audit`,
`review`, `bisect`, `explain`, `fix-verify`, `install-hooks`, `scan`, `repo`,
`top-risk`, `codex-brief`, `catalog`, `engines`, `flows`, `init`,
`engines-install`, `autofix`, `mine`, `batch`, `init-ci`, and `all`.

## Release State

- Current Rust release: `v0.8.0`
- Previous Python line: preserved as `debugmastery`
- Legacy backup branches:
  - `python-main-github-before-rust`
  - `python-main-gitea-before-rust`

## License

MIT. See [LICENSE](LICENSE).
