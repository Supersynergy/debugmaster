# Changelog

All notable changes to debugmaster-rs are documented here. Semantic Versioning.

## [0.1.0] - 2026-06-03

Ground-up Rust + tree-sitter rebuild. Distribution-first: a single self-contained
binary (~2.7 MB, only `libSystem`), no Python runtime.

### Added

- **`hunt`** — gitignore-aware repo walk, `rayon`-parallel scan, severity-ranked
  findings, markdown + JSON output, exit non-zero on high/critical.
- **Business-logic moat** (tree-sitter Python AST + intent guards, FP-controlled):
  `biz-idor-missing-ownership`, `biz-mass-assignment`, `biz-webhook-no-signature`,
  `biz-client-controlled-price`, `biz-refund-client-amount`, `biz-idempotency-missing`,
  `biz-float-money`.
- **Cross-language static pack** (regex, gitignore-aware): `secret-literal`,
  `sql-concat`, `py-shell-true`, `py-eval-exec`, `py-bare-except`, `py-eq-none`,
  `py-request-no-timeout`, `js-loose-eq`, `js-empty-catch`, `rust-unwrap`,
  `go-ignored-err`, `debug-leftover`.
- 10 unit tests covering each detector's true-positive and false-positive guard.

### Notes

- tree-sitter gives exact function/call node spans; the business-logic guard regexes
  are ported 1:1 from the Python engine and run on precise node text.
- `rayon` gives true multi-core parallelism (no GIL, no process-pool overhead).
