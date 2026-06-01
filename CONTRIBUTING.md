# Contributing

Thanks for helping improve Debugmaster.

## Development Setup

```bash
git clone https://github.com/Supersynergy/debugmaster.git
cd debugmaster
python3 -m py_compile bin/debugmaster
./install.sh --link
debugmaster all . --timeout 60
```

## Before Opening A Pull Request

Run:

```bash
python3 -m py_compile bin/debugmaster
bash -n install.sh bin/debugmaster-scan
DEBUGMASTER_NO_GREPGOD=1 bin/debugmaster all . --out /tmp/debugmaster-pr-check --timeout 30
```

If you change JSON catalogs, run:

```bash
jq empty tools.json debugger-engines.json
```

## Contribution Guidelines

- Keep default behavior fast and fail-safe.
- Make heavy scans explicit with flags.
- Treat missing optional tools as warnings.
- Do not revert unrelated user changes.
- Add documentation for new commands or report fields.
- Prefer machine-readable JSON fields when adding report data.

## Commit Style

Use concise conventional-style commits:

```text
feat(debugmaster): add stack detector
fix(debugmaster): handle missing optional tool
docs: update quick start
```
