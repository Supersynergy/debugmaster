# Debugmaster Release Readiness

Date: 2026-06-01

## Current Position

Debugmaster is a standalone repo debugging and AI handoff tool.

It runs with only `python3` and `git`, then gets deeper when optional tools exist:

- Grepgod for maps, risk, health, and security.
- Ghmax for reference repo and pattern mining.
- Stack tools such as Cargo, pytest, Go, npm, shellcheck, semgrep, gitleaks, and osv-scanner when available.

## Release Features

- One-command repo report: `debugmaster all <repo>`.
- Machine-readable output: `debugmaster-report.json`.
- Human output: `debugmaster-report.md`.
- AI handoff output: `debugmaster-ai-brief.md`.
- Batch mode: `debugmaster batch --root <dir> --limit 5 --random`.
- GitHub pull request report template: `debugmaster init-ci <repo>`.
- Optional ghmax intelligence: `debugmaster mine <repo>` or `debugmaster all <repo> --ghmax`.
- Safe autofix dry-run/apply mode: `debugmaster autofix <repo> [--apply]`.
- 64 language/framework stack matrix with official references.
- 10 debug flows for repo truth, dirty impact, stack verification, security, frontend, native crash, backend trace, monorepo boundary, AI handoff, and no-grepgod fallback.
- Performance-safe defaults: no security scan unless `--security`, no Grepgod full map unless `--full-map`, and `--check-profile safe` unless deeper checks are requested.
- Bounded scanning via `DEBUGMASTER_MAX_SCAN_FILES` and bounded shellcheck file selection via `DEBUGMASTER_MAX_SHELLCHECK_FILES`.

## Linux Verification

Environment:

- Colima Docker Linux engine.
- Image: `ubuntu:26.04`.
- Installed in container: `python3`, `git`, `jq`.
- Grepgod and ghmax intentionally absent.

Command shape:

```bash
docker run --rm -v "$PWD/debugmaster:/debugmaster" -w /debugmaster ubuntu:26.04 \
  bash -lc 'apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y python3 git jq && python3 bin/debugmaster init && DEBUGMASTER_NO_GREPGOD=1 python3 bin/debugmaster all . --out /tmp/debugmaster-linux-report --no-security --no-full-map --timeout 30'
```

Result:

- `debugmaster init`: `ok=true`.
- `debugmaster all`: `PASS`.
- Detected stacks: `3`.
- Debug flows: `10`.
- Confirmed fallback works without Grepgod, ghmax, rg, node, cargo, pytest, shellcheck, semgrep, gitleaks, or osv-scanner.
- Re-verified after failsafe changes: `PASS`, profile `safe`, scan not truncated, checks `0`.

## Local Verification

Commands run:

```bash
python3 -m py_compile debugmaster/bin/debugmaster
jq empty debugmaster/tools.json debugmaster/debugger-engines.json
bash -n debugmaster/install.sh debugmaster/bin/debugmaster-scan
git diff --check -- debugmaster
debugmaster/bin/debugmaster --help
debugmaster/bin/debugmaster all --help
debugmaster/bin/debugmaster batch --help
DEBUGMASTER_NO_GREPGOD=1 debugmaster/bin/debugmaster all . --out /tmp/debugmaster-self-release --no-checks --no-security --no-full-map --timeout 20
```

Result:

- Python compile: PASS.
- JSON validation: PASS.
- Bash syntax: PASS.
- Diff whitespace: PASS.
- Help output includes `autofix`, `mine`, `batch`, `init-ci`, and `all`.
- Self fallback report: `WARN` because cmux-vault has unrelated dirty files; report generation succeeded.

## Ghmax Verification

Command:

```bash
DEBUGMASTER_NO_GREPGOD=1 debugmaster/bin/debugmaster mine . --query "debugmaster repo healthmap codegraph" -n 2 --out /tmp/debugmaster-ghmax-smoke
```

Result:

- Overall: `ok=true`.
- Pattern mining: PASS via `ghmax --peek --export`.
- Artifact: `/tmp/debugmaster-ghmax-smoke/debugmaster-ghmax-patterns.md`.
- Repo mining reported `gh CLI missing` from ghmax in this environment; Debugmaster kept the successful pattern artifact and did not block local reports.

## Machine Learning 5-Repo Batch

Command:

```bash
DEBUGMASTER_NO_GREPGOD=1 debugmaster/bin/debugmaster batch \
  --root /Users/master/machinelearning \
  --limit 5 \
  --random \
  --out /tmp/debugmaster-machinelearning-5 \
  --no-security \
  --no-full-map \
  --timeout 20
```

Aggregate output:

- Reports written: `/tmp/debugmaster-machinelearning-5`.
- Repos scanned: `5`.
- FAIL: `5`.
- WARN: `0`.
- Dirty files: `0` in all 5.

Repos:

| verdict | repo | checks | first issue |
|---|---|---:|---|
| FAIL | `rust-ml__linfa` | 2/5 | `cargo check --workspace --all-targets` timeout |
| FAIL | `nnaisense__evotorch` | 2/3 | `pytest -q` returncode 4 |
| FAIL | `MathisWellmann__go_ehlers_indicators` | 1/3 | `go test ./...` returncode 1 |
| FAIL | `TulipCharts__tulipindicators` | 1/4 | `pytest -q` returncode 5 |
| FAIL | `axolotl-ai-cloud__axolotl` | 3/5 | `pytest -q` returncode 4 and shellcheck returncode 1 |

Interpretation:

Debugmaster correctly generated actionable reports for random real repositories. The FAIL verdicts are repo/test-environment findings, not Debugmaster crashes.

## Machine Learning 5-Repo Safe Batch

Command:

```bash
DEBUGMASTER_NO_GREPGOD=1 debugmaster/bin/debugmaster batch \
  --root /Users/master/machinelearning \
  --limit 5 \
  --random \
  --out /tmp/debugmaster-machinelearning-5-safe \
  --timeout 10
```

Aggregate output:

- Reports written: `/tmp/debugmaster-machinelearning-5-safe`.
- Repos scanned: `5`.
- PASS: `5`.
- FAIL: `0`.
- WARN: `0`.

Repos:

| verdict | repo | checks | dirty |
|---|---|---:|---:|
| PASS | `m-bain__whisperX` | 1/1 | 0 |
| PASS | `ml-explore__mlx-swift` | 1/1 | 0 |
| PASS | `QuantConnect__Lean` | 1/1 | 0 |
| PASS | `modelscope__ms-swift` | 1/1 | 0 |
| PASS | `kserve__kserve` | 1/1 | 0 |

Interpretation:

The default safe profile avoids expensive deep test suites and uses cheap repo-health checks. Deep failures remain available with `--check-profile deep`, but the default no longer causes performance cliffs on random large repositories.

## Release Caveats

- `debugmaster init-ci` assumes the target repository contains the `debugmaster/` folder. Repos that consume Debugmaster as a separate binary should adjust the workflow command path.
- `autofix --apply` is intentionally conservative. It trims trailing whitespace in already-dirty text files and can run known formatter commands. It does not revert files.
- Security scans are opt-in via `--security` and are deeper when Grepgod, Semgrep, Gitleaks, and OSV Scanner are installed.
- Ghmax repo search depends on ghmax's configured GitHub CLI path; pattern mining can still work without that repo-search path.
- Deep build/test verification is opt-in via `--check-profile deep`; default `safe` avoids expensive test suites and marks timeouts/unavailable tools as warnings.
- Timeouts and unavailable optional tools produce `WARN` instead of crashing the process.

## Go-To Commands

```bash
debugmaster init
debugmaster all . --timeout 120
debugmaster all . --check-profile deep --security --full-map --timeout 120
debugmaster autofix .
debugmaster mine . --query "<stack> <failure> debugging"
debugmaster batch --root /path/to/repos --limit 5 --random
debugmaster init-ci .
```
