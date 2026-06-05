# Changelog

All notable changes to debugmaster are documented here. Semantic Versioning.

## [Unreleased]

### Changed

- Bumped to Rust 1.96.0 toolchain (edition 2024 unchanged). Verified: `cargo clippy
  --release --all-targets --all-features -- -D warnings` clean, 15/15 tests pass.
- Dependency updates: `tree-sitter` 0.25 → 0.26.9, `tree-sitter-python` 0.23 → 0.25.0
  (both major bumps, no API breaks), `ignore` 0.4.25 → 0.4.26. Cargo 1.96 also
  resolves CVE-2026-5222 / CVE-2026-5223.

### Fixed

- `hunt` single-file scan: `walk::rel` now returns the file's basename instead of
  an empty string when the scanned path equals the root (single-file input). Every
  finding's `file` field is now non-empty regardless of invocation mode.

### Removed

- Dropped unused `anyhow` dependency (0 references in `src/`, confirmed via
  `cargo machete`; gone from `Cargo.lock` entirely, not even transitive). Applied
  `cargo fmt`. Verified: `cargo check`, `cargo clippy --all-targets --all-features
  -- -D warnings` clean, 15/15 tests pass.

## [0.8.0] - 2026-06-03

Rust becomes the primary `debugmaster` command. The previous Python CLI is kept
as `debugmastery` and remains available as a legacy fallback.

### Added

- **`sessions`** — native Rust reader for Codex and Claude JSONL transcripts.
  Defaults to `~/.codex/sessions` and `~/.claude/projects`, supports query,
  JSON output, custom roots, and newest-first result ordering.
- **Legacy parity bridge** — unknown Python-era subcommands are forwarded to
  `debugmastery` with the same arguments. This keeps `doctor`, `audit`,
  `review`, `profile`, `codex-brief`, `mcp`, and the rest of the Python surface
  usable while native Rust ports continue.
- Integration tests for Codex-style session JSONL parsing and `debugmastery`
  forwarding.
- Self-hunt regression test that requires the Rust crate to scan cleanly before
  shipping.

### Changed

- Package renamed from `debugmaster-rs` to `debugmaster`.
- Version bumped to `0.8.0`, above the Python `debugmastery` line at `0.7.1`.
- Regex initialization and JSON output paths no longer use `unwrap()`/`expect()`.
- Rule fixtures and debug-pattern definitions no longer trigger their own
  scanner rules.
- Local scanner outputs (`.debugmaster`, `.grepgod`, `.repovista`) are ignored.
- Repository release polish: MIT license, contributing guide, security policy,
  code of conduct, Just recipes, Cargo metadata, and social-preview brief.

### Verification

- `cargo test`
- `cargo clippy --all-targets -- -D warnings`
- `cargo build --release`
- `debugmaster hunt /Users/master/projects/debugmaster --json -n 100`
- `debugmastery hunt /Users/master/projects/debugmaster --profile fast --no-fuse --json -n 100 --timeout 20`
- `just check`

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
