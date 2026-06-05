# AGENTS.md — debugmaster

Single-binary bug hunter. Static + business-logic detectors over source files;
tree-sitter AST pass for Python, regex rules for the other languages.

## Build & verify (always before claiming done)

```bash
just check     # fmt --check + test + clippy -D warnings + release build + self-hunt
just pre-pr    # check + cargo-deny (advisories + licenses)
```

Toolchain is pinned in `rust-toolchain.toml` (Rust 1.96.0). MSRV: 1.96.
Do not bump deps/toolchain without a green `just check`.

## Layout

- `src/main.rs` — clap CLI: `hunt`, `sessions`, `legacy` (forwards unknown
  subcommands to the Python `debugmastery` binary on PATH).
- `src/walk.rs` — gitignore-aware file walk; `lang_of` maps extensions → language.
- `src/rules.rs` — regex static rules (all languages).
- `src/bizlogic.rs` — Python business-logic detectors (tree-sitter / regex).
- `src/hunt.rs` — orchestration, ranking, verdict, markdown/JSON report.
- `src/sessions.rs` — Codex/Claude JSONL transcript reader.
- `tests/cli.rs` — end-to-end CLI tests.

## Conventions

- Edition 2024. `cargo fmt` clean, `clippy -D warnings` clean — both gated in CI.
- Adding a language: extend `walk::lang_of` AND add detectors in `rules.rs`
  (and `bizlogic.rs` for deep AST). A grammar without detectors is dead weight.
- `hunt` exit codes: `0` clean/warn/no-files, `1` high/critical findings,
  `2` path not found. Never report a missing/empty path as CLEAN.
- Every meaningful change updates `CHANGELOG.md` under `[Unreleased]`.

## Remotes

`origin` → GitHub `Supersynergy/debugmaster`, `gitea` → git.marketdeck.io.
CI lives in `.github/workflows/ci.yml` (read by both GitHub and Gitea runners).
