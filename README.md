# Debugmaster

Debugmaster is a fail-safe repo diagnostics CLI for engineers and AI coding agents that need fast, bounded project health reports across languages, monorepos, dirty worktrees, and CI. Unlike deep-only scanners, it starts safe and quick, then opts into heavier maps, security scans, ghmax mining, and autofix when requested.

[![Release](https://img.shields.io/github/v/release/Supersynergy/debugmaster?sort=semver)](https://github.com/Supersynergy/debugmaster/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-blue)](#install)
[![Python](https://img.shields.io/badge/python-3.x-blue)](#install)

## Why Use It

- One command writes human, JSON, and AI-handoff reports.
- Safe defaults avoid performance cliffs on unknown repos.
- 64 language/framework stack detector with official references.
- Optional Grepgod, ghmax, security, and deep-check integration.
- Batch mode scans repo folders and produces aggregate reports.
- Pull-request workflow template publishes reports as CI artifacts.

## Install

```bash
git clone https://github.com/Supersynergy/debugmaster.git
cd debugmaster
./install.sh --link
debugmaster init
```

Minimum requirements: `python3` and `git`.

Optional depth tools: `grepgod`, `ghmax`, `rg`, `jq`, `semgrep`, `gitleaks`, `osv-scanner`, `cargo`, `pytest`, `just`, `node`.

## Quick Start

Safe default:

```bash
debugmaster all . --timeout 60
```

Deep release check:

```bash
debugmaster all . --check-profile deep --security --full-map --timeout 120
```

Batch scan:

```bash
debugmaster batch --root /path/to/repos --limit 5 --random
```

Safe autofix dry-run:

```bash
debugmaster autofix .
```

Install a GitHub pull-request report workflow:

```bash
debugmaster init-ci .
```

## Outputs

`debugmaster all <repo>` writes:

```text
reports/<repo>/debugmaster-report.md
reports/<repo>/debugmaster-report.json
reports/<repo>/debugmaster-ai-brief.md
```

The JSON is for automation. The AI brief is for Codex, Claude, and other coding agents.

## Safety Model

Default mode is intentionally conservative:

- `--check-profile safe`
- no security scan unless `--security`
- no Grepgod full map unless `--full-map`
- max scanned files: `DEBUGMASTER_MAX_SCAN_FILES` or `120000`
- max shellcheck files: `DEBUGMASTER_MAX_SHELLCHECK_FILES` or `40`
- timeouts and unavailable optional tools become report warnings instead of crashes

Use `--check-profile deep` when you want slower proof from test suites and heavier checks.

## Commands

| Command | Purpose |
|---|---|
| `debugmaster init` | Check local tool availability and prepare report folder |
| `debugmaster all <repo>` | Write all-in-one Markdown, JSON, and AI reports |
| `debugmaster batch --root <dir>` | Scan many Git repos and write aggregate reports |
| `debugmaster autofix <repo>` | Dry-run safe low-risk fixes |
| `debugmaster autofix <repo> --apply` | Apply safe whitespace/formatter fixes |
| `debugmaster mine <repo>` | Use ghmax for reference repo and pattern mining |
| `debugmaster flows` | Print built-in diagnostic flows |
| `debugmaster init-ci <repo>` | Add GitHub Actions PR report workflow |
| `debugmaster catalog <query>` | Search the debugger/profiler engine catalog |

## Stack Coverage

Debugmaster detects 64 language/framework stacks, including Rust, TypeScript, JavaScript, Go, Python, Astro, Next.js, React, Vue, SvelteKit, Vite, Tailwind, Java, Kotlin, C/C++, C#/.NET, PHP, Ruby, Swift, Dart/Flutter, Elixir, Scala, R, Shell, SQL, Docker, Kubernetes, Terraform, Nix, GraphQL, Protobuf, Solidity, Zig, Haskell, OCaml, Clojure, Erlang, Lua, Perl, Julia, Nim, Crystal, D, Objective-C, Groovy/Gradle, Fortran, PowerShell, Godot, Unity, Unreal, and WebAssembly.

Each detected stack includes relevant debugging, testing, or official documentation references in the report.

## Workflow

1. Identify repo, Git state, dirty files, remotes, and branch.
2. Scan structure with bounded file limits.
3. Detect packages, language stacks, and optional debug engines.
4. Run safe checks or explicit deep checks.
5. Write Markdown, JSON, and AI handoff artifacts.
6. Rank next fixes from failing checks, security findings, and dirty impact.

## Documentation

- [CHEATSHEET.md](CHEATSHEET.md)
- [RELEASE-READINESS.md](RELEASE-READINESS.md)
- [debug-flows.md](debug-flows.md)
- [runbook.md](runbook.md)
- [CODEX.md](CODEX.md)

## GitHub Actions

To make Debugmaster reports available on pull requests:

```bash
debugmaster init-ci .
git add .github/workflows/debugmaster.yml
git commit -m "ci: add debugmaster pull request reports"
```

The workflow uploads `debugmaster-report.md`, `debugmaster-report.json`, and `debugmaster-ai-brief.md` as artifacts.

## Versioning

Debugmaster uses SemVer. The first public release is `v0.1.0`.

## License

MIT. See [LICENSE](LICENSE).
