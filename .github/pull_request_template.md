## Summary

- 

## Verification

```bash
python3 -m py_compile bin/debugmaster
bash -n install.sh bin/debugmaster-scan
DEBUGMASTER_NO_GREPGOD=1 bin/debugmaster all . --out /tmp/debugmaster-pr-check --timeout 30
```

## Checklist

- [ ] Default path remains fast and fail-safe.
- [ ] Heavy checks are opt-in.
- [ ] Docs updated for new commands or report fields.
- [ ] No generated reports or local cache files committed.
