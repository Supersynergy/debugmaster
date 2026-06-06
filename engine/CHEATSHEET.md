# Debugmaster Cheatsheet

## Hunt Hidden Bugs (flagship)

```bash
debugmaster hunt .                  # ranked hidden bugs: severity × precision × blast-radius
debugmaster hunt . --dirty          # only files in your working diff
debugmaster hunt . --deep --json    # + semgrep/osv/trivy/clippy, machine output
debugmaster audit .                 # SUPER-AUDIT: graded repo health + SHIP/FIX-FIRST/BLOCK
debugmaster audit . --save-baseline # lock the bar; later audits show regressions vs fixed
debugmaster profile -- python3 app.py  # RUNTIME: mem/fd/gpu leaks, cpu bottleneck, orphans
debugmaster profile --pid 4123 --duration 30   # attach to a live process
debugmaster mcp                     # MCP server (agent tools over stdio)
debugmaster watch .                 # re-scan changed files on save
debugmaster hunt . --triage         # + local-LLM real/false-positive second opinion
debugmaster regress app.py py-shell-true   # gen pytest that locks the fix forever
debugmaster review . --base main --comment # PR verdict posted to the PR (gh/glab)
debugmaster checks --domain payments  # business-debug catalog (200 revenue/billing surfaces)
debugmaster checks --detected         # the 13 billing bugs hunt auto-detects
debugmaster scan-bugs . --dirty --lang python,rust   # fast static engine only
debugmaster scan-bugs . --class biz # business-logic only (IDOR, money, idempotency, mass-assign, auth-ratelimit…)
debugmaster review . --base main    # is this change safe? PR verdict on the diff
debugmaster explain - < trace.txt   # localize a stacktrace → suspects
debugmaster bisect --good v1 --bad HEAD --test "pytest -x"   # auto root-cause → first bad commit
debugmaster fix-verify file.py biz-idor-missing-ownership 12   # run verify cmd, re-scan, auto-learn on pass
debugmaster install-hooks .         # pre-commit gate: block commits with high/critical on the diff
debugmaster fusion . --profile deep # run + normalize every installed scanner
debugmaster doctor                  # which detection layers are live
debugmaster learn-feedback file.py 42 py-shell-true real   # confirm → ranker learns
debugmaster learn-feedback file.py 7 js-loose-eq fake      # dismiss → ranker learns
debugmaster learn-stats             # learned per-rule precision
```

Outputs (under `<repo>/.debugmaster/`): `debugmaster-hunt.{json,md}` + `-ai-brief.md`.
Clean-HEAD runs are cached (instant re-run); `--no-cache` forces. Full reference: `HUNTING.md`.

## Install

```bash
debugmaster/install.sh --link
debugmaster init
```

Minimum tools: `python3` and `git`.

Optional depth tools: `grepgod`, `ghmax`, `rg`, `jq`, `semgrep`, `gitleaks`, `osv-scanner`, `cargo`, `pytest`, `node`, `just`.

## One Repo

```bash
debugmaster all . --timeout 60
```

Outputs:

- `debugmaster-report.md`
- `debugmaster-report.json`
- `debugmaster-ai-brief.md`

Use the JSON for automation and the AI brief for Codex/Claude handoff.

## Batch Repos

Safe default:

```bash
debugmaster batch --root /Users/master/machinelearning --limit 5 --random
```

Deep mode:

```bash
debugmaster batch --root /Users/master/machinelearning --limit 5 --random --check-profile deep --security --full-map --timeout 120
```

Outputs:

- `debugmaster-batch-report.md`
- `debugmaster-batch-report.json`
- per-repo report folders

## Pull Request Reports

```bash
debugmaster init-ci .
```

This writes `.github/workflows/debugmaster.yml`.

The workflow uploads Debugmaster reports as GitHub Actions artifacts for pull requests.

## Ghmax Intelligence

```bash
debugmaster mine . --query "repo healthmap codegraph debugging" -n 8
debugmaster all . --ghmax --ghmax-query "python ml debugging tests"
```

This adds:

- reference repo search via `ghmax --repos`
- pattern mining via `ghmax --peek --export`

## Autofix

Dry-run first:

```bash
debugmaster autofix .
```

Apply safe fixes:

```bash
debugmaster autofix . --apply
```

Current safe fixes:

- trim trailing whitespace in already-dirty text files
- run known formatter commands only when `--apply` is explicit

It does not revert files.

## Linux Smoke Test

```bash
docker run --rm -v "$PWD/debugmaster:/debugmaster" -w /debugmaster ubuntu:26.04 \
  bash -lc 'apt-get update && apt-get install -y python3 git jq && python3 bin/debugmaster init && python3 bin/debugmaster all . --timeout 30'
```

## Fast Agent Loop

```bash
debugmaster all . --timeout 60
sed -n '1,180p' debugmaster/reports/$(basename "$PWD")/debugmaster-ai-brief.md
debugmaster autofix .
debugmaster flows
```

Fix order:

1. failing checks
2. security/dependency scan failures
3. high-impact dirty files
4. stack-specific references
5. monorepo boundary issues

## Performance Safety

Default mode is conservative:

- `--check-profile safe`
- no security scan unless `--security`
- no Grepgod full map unless `--full-map`
- max scanned files: `DEBUGMASTER_MAX_SCAN_FILES` or `120000`
- max shellcheck files: `DEBUGMASTER_MAX_SHELLCHECK_FILES` or `40`

Use deep mode only when you want slower proof:

```bash
debugmaster all . --check-profile deep --security --full-map --timeout 120
```
