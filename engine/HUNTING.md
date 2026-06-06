# Debugmaster Hunt — finding the smallest hidden bugs

`debugmaster hunt` is the flagship. It exists to surface the bugs that compilers
and single linters miss, ranked so the top of the list is *the bug that probably
exists AND probably matters*. Five engines, one bounded pass, graceful
degradation everywhere.

```bash
debugmaster hunt <repo> [--dirty] [--deep] [-n 25] [--timeout 90] [--json]
```

## The five engines

| Engine | File | What it finds |
|---|---|---|
| Static bug engine | `lib/bughunt.py` | 29 cross-language regex rules + a Python-AST pass: swallowed errors, mutable defaults, `assert (cond, msg)`, blocking-in-async, copy-paste asymmetry (`a.x and a.x`), discarded `.strip()`, injection sinks, hardcoded secrets, TOCTOU, unbounded queues, retry-without-backoff, off-by-one, `== None`, secret-in-fallback, TODO-near-auth … |
| Tool fusion | `lib/fusion.py` | runs every installed best-in-class scanner (ruff, bandit, gitleaks, shellcheck, actionlint, +deep: semgrep, osv-scanner, trivy, vulture, clippy), normalizes all output to one schema, dedupes against the static engine. Total-time budgeted so a slow scanner can't hang the run. |
| History mine | `lib/gitrisk.py` | bug-fix density per file (recency-weighted), churn, author spread, and **logical co-change coupling** — if a dirty file historically changes together with a clean file at high confidence, the clean file is a *forgotten-edit suspect*: a bug no linter can see. |
| Risk model | `lib/riskmodel.py` | blends history + structure (complexity/nesting/size) + finding mass + dirty + blast-radius into per-file P(bug). Optional unsupervised IsolationForest anomaly bonus when scikit-learn is present; pure-python heuristic otherwise. |
| Business-logic | `lib/bizlogic.py` | the "looks correct but is wrong" bugs no linter catches: **IDOR / missing-ownership** (endpoint fetches a record by id with no authz check — and correctly stays quiet when the check is present), **float-money** (money as float / divided / `==`), pagination off-by-one, cents/dollars unit mismatch, missing idempotency on charge/order, unscoped multi-tenant queries. Every finding is a *suspect* with a confidence + "verify with X" (business-logic detection is FP-prone, so it never accuses). |
| Reach | `lib/reach.py` | resolved fan-in (codegraph when indexed, else import-graph) so ranking is *expected damage* = P(bug) × blast-radius; plus **test-gap** findings for changed source with no covering test. |

## Active flows (`lib/flows.py`)

Beyond scanning — the loops developers actually run:

```bash
debugmaster review <repo> --base main   # is this change safe? hunt scoped to the diff → APPROVE / COMMENT / REQUEST-CHANGES + forgotten-edit suspects
debugmaster explain - < trace.txt        # paste a stacktrace → every in-repo frame localized with code context + suspects
debugmaster bisect --good <ref> --bad <ref> --test "<cmd>"   # automate git bisect run → the exact commit that introduced the bug
```

`review` is built for 2026: reviewing AI-generated diffs. It limits findings to
what changed, flags business-logic and security suspects on those lines, and adds
*forgotten-edit suspects* — files that historically change together with the diff
but were left untouched.

## Ranking

```
priority = severity_rank × learned_precision × (1 + 0.6·file_risk + dirty_boost)
```

- **severity_rank** — critical=4 … info=0
- **learned_precision** — Beta posterior per rule from your confirm/dismiss feedback (`lib/learn.py`), seeded by curated priors so there is no cold start
- **file_risk** — the risk-model score for the file the finding sits in
- **dirty_boost** — +0.5 if the file is in your working diff

## The compounding loop (this is the moat)

Every run records its findings to `<repo>/.debugmaster/learn.db`. When you confirm
or dismiss one:

```bash
debugmaster learn-feedback path/to/file.py 42 py-shell-true real   # or: fake
```

the rule's Beta(α, β) precision updates, and every future run ranks that rule
higher or lower accordingly. Each run on a repo is sharper than the last —
per-repo debugging memory no generic linter has.

```bash
debugmaster learn-stats        # see learned per-rule precision
```

## Graceful degradation

`debugmaster doctor` shows which layers are live. Nothing is mandatory:

- no scanners → static engine only (still pure-stdlib, still finds the core classes)
- no scikit-learn → heuristic risk model instead of IsolationForest
- no codegraph/grepgod → import-graph blast-radius instead of a resolved call graph
- no git → no history/co-change, everything else runs
- huge repo → fusion stays inside its time budget and logs which scanners it skipped (never silent)

## Output

```text
<repo>/.debugmaster/debugmaster-hunt.json     # source of truth (machine)
<repo>/.debugmaster/debugmaster-hunt.md        # ranked report (human)
<repo>/.debugmaster/debugmaster-hunt-ai-brief.md   # <180-line agent handoff
```

Clean-HEAD runs are cached: a second run on the same commit with a clean tree
returns instantly (`--no-cache` to force).

## Tests

```bash
python3 -m unittest discover -s tests -v
```
