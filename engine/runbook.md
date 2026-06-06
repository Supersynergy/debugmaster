# Debugmaster Runbook

Use this when entering an unfamiliar or dirty codebase.

## 1. Build The Atlas

```bash
debugmaster/bin/debugmaster init
debugmaster/bin/debugmaster all . --timeout 120
debugmaster/bin/debugmaster scan .
debugmaster/bin/debugmaster codex-brief .
grepgod --chain map .
```

Read first:

```text
debugmaster/reports/<repo>/debugmaster-report.md
debugmaster/reports/<repo>/debugmaster-ai-brief.md
.grepgod/MAP.md
.grepgod/healthmap.md
.grepgod/riskmap.md
.grepgod/map-index.json
```

## 2. Rank Current Worktree Risk

```bash
grepgod healthmap .
jq '.impact.changed_files[:20]' .grepgod/healthmap.json
```

Prioritize files with:

- high `score`
- `hub: true`
- many `nearby_risks`
- high `max_fanin`
- status `??` when the file is new and not mapped yet

## 3. Query Before Reading Whole Files

```bash
grepgod ask . "risks"
grepgod ask . "hotspots"
grepgod ask . "callers of <function>"
grepgod ask . "what does <function> call"
grepgod ask . "endpoints"
grepgod ask . "tables"
```

## 4. Debug A Concrete Error

```bash
grepgod debug . "paste stacktrace or exact error"
```

Then inspect the ranked culprit and nearby risks before editing.

## 5. Run Security/Dependency Sweep

```bash
grepgod --chain security
```

Treat these as separate classes:

- semgrep findings: code/security patterns
- gitleaks findings: secret history/current tree
- osv findings: dependency vulnerabilities

## 6. Mine Outside Patterns

```bash
ghmax --repos "code graph static analysis" --stars-min 100 -n 8 --sort stars
ghmax "<literal API or code anchor>" --lang TypeScript -n 20
```

Use `ghmax --repos` for tools and architecture.
Use literal `ghmax`/code search for concrete implementation patterns.

## 7. Use The Standalone Engine Catalog

```bash
debugmaster/bin/debugmaster engines
debugmaster/bin/debugmaster catalog "python"
debugmaster/bin/debugmaster catalog "race"
debugmaster/bin/debugmaster catalog "llm"
debugmaster/bin/debugmaster catalog "network"
```

The catalog is offline and includes debugger, profiler, tracing, browser, mobile, network, database, ML/LLM, and reverse-engineering patterns.

## 8. Verify Before Reporting

For grepgod itself:

```bash
pytest tests/test_healthmap.py -q
python3 -m py_compile bin/grepgod-mapkit.py bin/grepgod-analyze.py bin/grepgod-chain-funcmap.py
bash -n bin/grepgod bin/grepgod-chain-healthmap bin/grepgod-chain-map
grepgod selftest
grepgod doctor
```

For any target repo:

```bash
grepgod --chain map .
grepgod healthmap .
git diff --check
```
