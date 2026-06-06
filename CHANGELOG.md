# Changelog

All notable changes to debugmaster are documented here. Semantic Versioning.

## [0.9.0] — 2026-06-06

One tool, one folder. The former sibling `debugmastery` Python project is folded
in as the bundled `engine/` — there is no longer a second tool to install or keep
on `PATH`.

### Added

- **Bundled engine (`engine/`).** The full Python analysis engine (18 modules:
  hunt pipeline, fusion, audit, profile, mcp, learn, gitrisk, …) now ships inside
  this repo. `src/engine.rs` resolves it from `$DEBUGMASTER_ENGINE`,
  `~/.debugmaster/engine`, the source tree, or next to the binary, and runs it via
  `python3`. No `pip`, no second package on `PATH`.
- **Native `doctor`** (`src/doctor.rs`) — capability self-audit covering the Rust
  core, the bundled engine + `python3`, and the scanner fusion layer in one report;
  merges the engine's deeper layer/ML probe when present. Previously forwarded.
- **`hunt --deep`** — routes to the bundled engine's full pipeline (tool fusion +
  git-history + learned-precision ranking). Native `hunt` stays the fast Rust scan;
  the two are now an explicit choice, not two silently-diverging code paths.
- **`just install`** — builds, links the binary on `PATH`, and stages the engine to
  `~/.debugmaster/engine` so the installed binary is self-contained.
- Tests: bundled-engine resolution + "engine command ignores a PATH `debugmastery`
  sabotage shim" + native-`src/` self-hunt stays CLEAN.

### Changed

- **Parity bridge** no longer shells out to a `debugmastery` binary on `PATH`;
  unknown/deep subcommands run the bundled engine entry (`engine/bin/debugmaster`)
  through `python3`.
- README/`--help` rewritten: honest "native core + bundled engine, no second
  install" framing replaces the inaccurate "single binary, no Python" claim.
- Version `0.8.0` → `0.9.0`.

### Removed

- Sibling `debugmastery` project dependency. The standalone project is archived
  (`~/BASE/archive/debugmastery-folded-into-debugmaster-2026-06-06`); the stale
  `~/.local/bin/debugmastery` symlink is gone.

## [Unreleased]

### Added

- **CI** — `.github/workflows/ci.yml` (read by both GitHub and Gitea runners):
  fmt-check, clippy `-D warnings`, tests, release build, self-hunt dogfood, plus a
  `cargo-deny` job (advisories + licenses).
- **`rust-toolchain.toml`** pins the toolchain to Rust 1.96.0 (rustfmt + clippy);
  `rust-version = "1.96"` declares the MSRV.
- **`deny.toml`** — supply-chain gate (RUSTSEC advisories, license allow-list,
  source pinning). Run via `just audit` / `just pre-pr`.
- **`AGENTS.md`** — build/verify/layout/convention guide for agents and contributors.
- `justfile`: new `fmt`, `audit`, and `pre-pr` recipes; `ci` now runs
  `doctor` + full `check` (fmt + test + clippy + build + self-hunt).

### Changed

- Bumped to Rust 1.96.0 toolchain (edition 2024 unchanged). Verified: `cargo clippy
  --release --all-targets --all-features -- -D warnings` clean, 15/15 tests pass.
- Dependency updates: `tree-sitter` 0.25 → 0.26.9, `tree-sitter-python` 0.23 → 0.25.0
  (both major bumps, no API breaks), `ignore` 0.4.25 → 0.4.26. Cargo 1.96 also
  resolves CVE-2026-5222 / CVE-2026-5223.

### Fixed

- `hunt` no longer reports a missing or empty path as `CLEAN` (false-negative for a
  security tool). A non-existent path now errors to stderr and exits `2`; an existing
  path with zero source files reports the distinct `NO_FILES` verdict (exit `0`).
  Covered by two new end-to-end tests.
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
