# debugmaster-rs

> Single-binary bug hunter. Static + **business-logic** detectors over tree-sitter ASTs.
> No runtime, no Python, no install — one file, runs anywhere.

A ground-up Rust rebuild of [debugmaster](https://git.marketdeck.io/Supersynergy/debugmaster)
where **distribution is the priority**: `cargo build --release` produces a single
~2.7 MB binary that depends only on `libSystem` — drop it into any CI or machine and run.

```bash
debugmaster hunt .            # ranked findings, human output
debugmaster hunt . --json     # machine output
debugmaster hunt . -n 30      # top 30
```

## The moat: bugs linters can't see

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

## Plus a cross-language static pack

`secret-literal`, `sql-concat`, `py-shell-true`, `py-eval-exec`, `py-bare-except`,
`py-eq-none`, `py-request-no-timeout`, `js-loose-eq`, `js-empty-catch`,
`rust-unwrap`, `go-ignored-err`, `debug-leftover`. Languages by extension;
`.gitignore`-aware walk; `guard` regexes keep false positives down.

## Why Rust + tree-sitter

- **Distribution.** One static binary. No Python, no `pip`, no version drift in CI.
- **True parallelism.** The repo scan is `rayon` over cores — no GIL, no process-pool
  overhead (the Python build had to fork around the GIL).
- **Exact spans.** tree-sitter gives real function/call boundaries, so the
  business-logic guards run on precise node text, not line heuristics.

## Build

```bash
cargo build --release      # → target/release/debugmaster (single binary)
cargo test                 # unit tests (detectors + FP guards)
cargo clippy --all-targets -- -D warnings
```

## Roadmap

This is the foundation (the `hunt` engine + full moat). Porting next from the Python
original, in priority order: `audit` (graded health + release gate), `profile`
(runtime leak/bottleneck/orphan diagnostician), `mcp` (agent server), suppression
(`.debugmaster-ignore`), and multi-language AST detectors (JS/Go via their grammars).
