# Changelog

All notable changes to Debugmaster are documented here.

This project follows Semantic Versioning.

## [0.1.0] - 2026-06-01

### Added

- Standalone `debugmaster` CLI with `all`, `batch`, `autofix`, `mine`, `flows`, `catalog`, `scan`, `repo`, `top-risk`, `codex-brief`, and `init-ci`.
- All-in-one reports in Markdown, JSON, and AI brief formats.
- Batch report generation for folders of Git repositories.
- Safe autofix dry-run/apply mode for low-risk text cleanup.
- GitHub Actions pull-request report template.
- 64 language/framework stack detector with official references.
- 10 diagnostic flows for repo truth, dirty impact, stack verification, security, frontend, native crash, backend request trace, monorepo boundaries, AI handoff, and no-Grepgod fallback.
- Optional Grepgod health/map/security integration.
- Optional ghmax reference repo and pattern mining.

### Changed

- Default mode is fail-safe and fast: no full map, no security scan, and `--check-profile safe` unless deeper checks are explicitly requested.
- Timeouts and unavailable optional tools are warnings instead of process crashes.
- Structure scanning is bounded by `DEBUGMASTER_MAX_SCAN_FILES`.
- Shellcheck fan-out is bounded by `DEBUGMASTER_MAX_SHELLCHECK_FILES`.

### Fixed

- Minimal Ubuntu/Linux runs no longer fail when optional tools such as `shellcheck`, Grepgod, ghmax, cargo, pytest, or node are missing.
- Batch repo discovery correctly handles `.git` directories.
- Report generation avoids repeated full directory walks for structure and language detection.

### Security

- Security scans are opt-in via `--security`.
- Secret/dependency depth increases when Grepgod, Semgrep, Gitleaks, and OSV Scanner are installed.

### Breaking Changes

- None. This is the first public release.
