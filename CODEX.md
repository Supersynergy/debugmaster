# Debugmaster For Codex

Use this file when Codex enters a repo and needs fast orientation before editing.

## Default Codex Debug Loop

```bash
grepgod --chain map .
grepgod healthmap .
grepgod ask . "risks"
grepgod ask . "hotspots"
git status --short --branch
```

If there is a concrete failure:

```bash
grepgod debug . "<paste exact error or stacktrace>"
```

If the repo is security/dependency sensitive:

```bash
grepgod --chain security
```

## Codex Rules

- Read `.grepgod/MAP.md` before broad file reading.
- Use `.grepgod/healthmap.json` to identify dirty high-impact files.
- Do not commit `.grepgod/` or `.codegraph/` generated output unless explicitly requested.
- Do not revert dirty files from the user.
- Commit only the scoped files requested by the user.
- For big repos, run `grepgod healthmap .` first; run full `grepgod --chain map .` only when the result will be used.

## Copy-Paste Prompt

```text
Use Debugmaster: run grepgod healthmap and map first, read .grepgod/MAP.md, rank dirty files by impact score, inspect risks/hotspots with grepgod ask, then make the smallest scoped fix. Verify with the repo's real checks and commit only the intended files.
```

## Codex Commit Pattern

```bash
git status --short --branch
git diff --check
git add <scoped files>
git commit -m "docs(debugmaster): add codex debug toolkit"
```
