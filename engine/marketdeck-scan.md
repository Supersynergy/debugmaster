# git.marketdeck.io Debugmaster Scan

Scan date: 2026-06-01

Command pattern:

```bash
grepgod healthmap <repo>
grepgod --chain map <repo>   # full map for supersynergycrmpro and WINvestmentMAXIM
```

## Summary

| Repo path | Remote | Status | Dirty files | Impact | Packages | Full map |
|---|---|---:|---:|---:|---:|---|
| `/Users/master/projects/superweb` | `git.marketdeck.io/Supersynergy/Superweb.git` | DIRTY | 2 | 8 | 7 | healthmap |
| `/Users/master/projects/mdviewy` | `git.marketdeck.io/Supersynergy/mdviewy.git` | ATTENTION | 96 | 837 | 13 | healthmap |
| `/Users/master/projects/docs/languages-2026` | `git.marketdeck.io/Supersynergy/languages-master-2026.git` | FRESH | 0 | 0 | 0 | healthmap |
| `/Users/master/projects/WINvestmentMAXIM` | `git.marketdeck.io/Supersynergy/WINvestmentMAXIM.git` | DIRTY | 1 | 4 | 15 | full map |
| `/Users/master/projects/universalui` | `git.marketdeck.io/Supersynergy/universalui.git` | FRESH | 0 | 0 | 0 | healthmap |
| `/Users/master/projects/supermax` | `git.marketdeck.io/Supersynergy/supermax.git` | ATTENTION | 31 | 151 | 21 | healthmap |
| `/Users/master/projects/ghmax` | `git.marketdeck.io/Supersynergy/ghmax.git` | ATTENTION | 3 | 88 | 0 | healthmap |
| `/Users/master/projects/4eae67f7bd524f33101a54ebc81ab43e60e5035e` | `git.marketdeck.io/Supersynergy/youtube-trends-skill.git` | ATTENTION | 2 | 15 | 0 | healthmap |
| `/Users/master/projects/primequellen-superweb` | `git.marketdeck.io/Supersynergy/Primesource-Prediction.git` | FRESH | 0 | 0 | 0 | healthmap |
| `/Users/master/projects/WINvestmentMAX` | `git.marketdeck.io/Supersynergy/WINvestmentMAX.git` | DIRTY | 1 | 4 | 1 | healthmap |
| `/Users/master/projects/awesome-languages-2026` | `git.marketdeck.io/Supersynergy/awesome-languages-2026.git` | FRESH | 0 | 0 | 0 | healthmap |
| `/Users/master/projects/grepgod` | `git.marketdeck.io/Supersynergy/grepgod.git` | ATTENTION | 18 | 196 | 0 | healthmap |
| `/Users/master/projects/supersynergycrmpro` | no marketdeck remote found locally | ATTENTION | 46 | 322 | 16 | full map |

## Full Map Results

### supersynergycrmpro

```text
Endpoints: 50
Tables: 34
Risk findings: 219
Functions: 812
Call edges: 900
Health: ATTENTION, dirty files 46, impact score 322, packages 16
Output: /Users/master/projects/supersynergycrmpro/.grepgod/MAP.md
```

### WINvestmentMAXIM

```text
Endpoints: 41
Tables: 113
Risk findings: 337
Functions: 4177
Call edges: 8851
Health: DIRTY, dirty files 1, impact score 4, packages 15
Output: /Users/master/projects/WINvestmentMAXIM/.grepgod/MAP.md
```

## Highest Attention Repos

| Repo | Reason |
|---|---|
| mdviewy | 96 dirty files, impact 837 |
| supersynergycrmpro | full map shows 219 risk findings and 46 dirty files |
| WINvestmentMAXIM | large graph: 4177 functions, 8851 edges, 337 risk findings |
| supermax | 31 dirty files, impact 151 |
| ghmax | only 3 dirty files, but impact 88 |

## Notes

- `.grepgod/` outputs were generated locally in target repos for analysis.
- These outputs are not part of the `cmux-vault` commit.
- `supersynergycrmpro` was explicitly requested and scanned, but no `git.marketdeck.io` remote was present in the local repo at scan time.
