# Debugmaster

Debugmaster is the local index of the debugging, codegraph, search, risk-map, and repo-mining tools found while building the grepgod healthmap work.

Use this folder as the first stop when you need to scan an existing project, understand dirty files, find likely bugs, or hand an AI agent a compact project map.

## Fast Path

```bash
debugmaster/bin/debugmaster init
debugmaster/bin/debugmaster all . --timeout 60
debugmaster/bin/debugmaster scan .
debugmaster/bin/debugmaster codex-brief .
debugmaster/bin/debugmaster catalog race
grepgod --chain map .
grepgod healthmap .
grepgod ask . "risks"
grepgod debug . "<error or stacktrace>"
grepgod --chain security
ghmax --repos "code graph static analysis" --stars-min 100 -n 8 --sort stars
```

## Main Local Tools

| Tool | Purpose | Local path |
|---|---|---|
| grepgod | Search router, maps, riskmap, healthmap, debug helper | `/Users/master/.local/bin/grepgod` |
| grepgod source | Editable project repo | `/Users/master/projects/grepgod` |
| grepgod installed scripts | Runtime scripts used by PATH command | `/Users/master/.claude/bin/grepgod*` |
| ghmax | GitHub/repo/code pattern mining | `/Users/master/.local/bin/ghmax` |
| codegraph | Local code graph CLI | `/Users/master/.local/bin/codegraph` |
| synxp | Synapse recall search | `/Users/master/.local/bin/synxp` |
| synx | Synapse write/find CLI | `/Users/master/.local/bin/synx` |
| mdviewy target repo | Real test repo for maps and healthmap | `/Users/master/projects/mdviewy` |

## What Was Added To Grepgod

- `grepgod healthmap .`
- `grepgod --chain healthmap .`
- `grepgod --chain map .` now writes health data into `.grepgod/MAP.md` and `.grepgod/map-index.json`
- Dirty-tree ranking excludes generated `.grepgod/` and `.codegraph/` files
- Monorepo package detection via `package.json`, `Cargo.toml`, `pyproject.toml`, `go.mod`, `deno.json`
- Impact score from function graph fan-in/fan-out plus nearby risk findings

## Verification From Build Session

- `pytest tests/test_healthmap.py -q` passed: 2/2
- `python3 -m py_compile ...` passed
- `bash -n ...` passed
- `grepgod selftest` passed: 27/27
- `grepgod doctor` passed: 23 installed, 0 missing
- mdviewy `grepgod --chain map .` passed with 885 functions, 1276 call edges, 13 packages

## Files In This Folder

| File | Contents |
|---|---|
| `tools.json` | Machine-readable local and remote tool catalog |
| `local-paths.md` | Human-readable path index |
| `github-tools.md` | GitHub/Gitea tools and repos found |
| `runbook.md` | Practical debugging workflow |
| `CODEX.md` | Codex-specific usage rules and copy-paste prompt |
| `marketdeck-scan.md` | Results from running Debugmaster on local git.marketdeck.io repos |
| `bin/debugmaster-scan` | Repeatable healthmap scan script |
| `bin/debugmaster` | Standalone Debugmaster CLI |
| `debugger-engines.json` | 100+ debugger/profiler/observability tool feature catalog |

## Standalone CLI

```bash
debugmaster/install.sh --link
debugmaster all . --timeout 60
debugmaster/bin/debugmaster engines
debugmaster/bin/debugmaster scan /Users/master/projects/supersynergycrmpro /Users/master/projects/WINvestmentMAXIM
debugmaster/bin/debugmaster repo /Users/master/projects/supersynergycrmpro --full
debugmaster/bin/debugmaster top-risk /Users/master/projects/mdviewy -n 10
debugmaster/bin/debugmaster codex-brief .
debugmaster/bin/debugmaster catalog "race"
```

`debugmaster` uses grepgod when available. If grepgod is missing, it still reports Git dirty state, package counts, and a fallback impact score.

## All-In-One Report

```bash
debugmaster/bin/debugmaster all <repo> --timeout 120
```

Writes:

```text
debugmaster/reports/<repo>/debugmaster-report.md
debugmaster/reports/<repo>/debugmaster-report.json
debugmaster/reports/<repo>/debugmaster-ai-brief.md
```

Includes:

- repo identity and Git status
- structure: packages, file extensions, files, dirs
- detected Top-20 language/stack matrix: Rust, TypeScript, Go, JavaScript, Python, UI/Web, Mobile, Java, Kotlin, C/C++, C#/.NET, PHP, Ruby, Swift, Dart/Flutter, Elixir, Scala, R, Shell, SQL
- grepgod map data when available: functions, call edges, endpoints, tables, risks
- dirty impact ranking
- security/dependency scan via `grepgod --chain security` when available
- detected build/test/check commands
- available debug engines by stack
- clear `PASS` / `WARN` / `FAIL` verdict
- next 5 fixes for Codex/Claude

RepoVista reference: npm `repovista@0.5.1` is a read-only AI repository audit CLI for local provider CLIs. Debugmaster adapts the read-only report-artifact model, but works without Codex/Claude providers.

Implementation note: Debugmaster is not a Python-only debugger. The launcher is Python for portability, while the scanner is multi-language and detects/recommends checks/debug engines for Rust, TypeScript, Go, JavaScript, UI, mobile, JVM, .NET, PHP, Ruby, Swift, Dart/Flutter, Elixir, Scala, R, Shell, SQL, and native C/C++ repos.
