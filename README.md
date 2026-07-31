# debugmaster

Finds the bugs a linter cannot see, because they are not syntax errors but wrong
intent: an endpoint that loads a record by id and never checks who owns it, a
charge amount read straight from the request body, a refund with no idempotency
key. One command, one repo, machine-readable output for coding agents.

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
```

Useful commands:

```bash
debugmaster hunt .              # ranked findings, human output
debugmaster hunt . --json       # machine-readable report
debugmaster hunt . -n 30        # top 30 findings
debugmaster sessions -q codex   # search Codex/Claude JSONL sessions
debugmaster doctor              # which layers (core, engine, scanners) are live
debugmaster hunt . --deep       # full pipeline: fusion, git-history, learned ranking
debugmaster audit .             # graded SHIP/FIX-FIRST/BLOCK verdict
```

## What It Finds

The business-logic detectors read intent. They run on exact tree-sitter
function and call spans, not on line heuristics.

| Rule | Catches |
|---|---|
| `biz-idor-missing-ownership` | endpoint loads a record by id with no ownership or authz check |
| `biz-mass-assignment` | `Model(**request.json)`, over-posting into privilege fields |
| `biz-webhook-no-signature` | a webhook that never verifies the sender signature, so events are forgeable |
| `biz-client-controlled-price` | charge amount taken from the request, so the price can be tampered with |
| `biz-refund-client-amount` | refund amount from the request, so refunds can be inflated |
| `biz-idempotency-missing` | a charge with no idempotency key, so a retry double-charges |
| `biz-float-money` | money cast to float, losing precision |

Every detector stays silent once the guard is present: an ownership check,
`construct_event`, explicit kwargs, a server-side amount lookup, `Decimal`.
That is what keeps the report short enough to read.

## Static Rule Pack

`secret-literal`, `sql-concat`, `py-shell-true`, `py-eval-exec`, `py-bare-except`,
`py-eq-none`, `py-request-no-timeout`, `js-loose-eq`, `js-empty-catch`,
`rust-unwrap`, `go-ignored-err`, `debug-leftover`. Languages are picked by
extension, the walk respects `.gitignore`, and `guard` regexes hold false
positives down.

## How It Is Built

A Rust front-end over a Python analysis engine, shipped as one repository.

`hunt`, `sessions` and `doctor` are native Rust: one static binary, no
interpreter, `rayon` across cores with no GIL and no process-pool overhead.
tree-sitter supplies real function and call boundaries, so the business-logic
guards see precise node text.

Everything deeper runs `engine/bin/debugmaster` on the system `python3`. The
engine is carried inside this repository, not a sibling project, so there is no
`pip install` and no second tool on your `PATH`. It is resolved from
`$DEBUGMASTER_ENGINE`, `~/.debugmaster/engine`, the source tree, or the directory
next to the binary. Run `debugmaster doctor` to see whether the engine and
`python3` are reachable.

By volume the project is mostly Python (the engine) with a Rust command layer on
top. Splitting it that way is a deliberate choice, not two code paths drifting
apart.

## Verification

```bash
cargo build --release      # → target/release/debugmaster (single binary)
cargo test                 # unit tests: detectors and false-positive guards
cargo clippy --all-targets -- -D warnings
debugmaster hunt . --json
```

## Engine Commands

`hunt --deep`, `fusion`, `learn-feedback`, `learn-stats`, `scan-bugs`, `mcp`,
`checks`, `watch`, `regress`, `profile`, `audit`, `review`, `bisect`, `explain`,
`fix-verify`, `install-hooks`, `scan`, `repo`, `top-risk`, `codex-brief`,
`catalog`, `engines`, `flows`, `init`, `engines-install`, `autofix`, `mine`,
`batch`, `init-ci`, `all`.

The Rust front-end resolves the bundled engine and runs these for you.

## Release State

Current release `v0.9.0`. The former `debugmastery` Python project is folded in
as the bundled `engine/`. Legacy backup branches:
`python-main-github-before-rust`, `python-main-gitea-before-rust`.

## License

MIT. See [LICENSE](LICENSE).
