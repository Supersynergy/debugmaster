# Debugmaster Flows

One rule: every report implies the next action, and every flow ends one step from
a *verified, regression-locked* fix. The flows below are real CLI commands mapped
to the loop developers (and agents) actually run:

> **assess → reproduce → localize → hypothesize → fix → verify → prevent**

## The loop, as commands

| Step | Command | What it does |
|---|---|---|
| assess | `debugmaster audit .` | **super-audit**: graded repo health (A–F per dimension) + release verdict **SHIP / FIX-FIRST / BLOCK** + trend vs the last baseline |
| reproduce | `debugmaster explain - < trace.txt` | parse a stacktrace → every in-repo frame localized (Python deepest = last frame), with code context + a repro hint |
| localize | `debugmaster hunt . --dirty` | rank the smallest hidden bugs on what you changed: severity × learned-precision × blast-radius |
| localize (root cause) | `debugmaster bisect --good <ref> --bad <ref> --test "<cmd>"` | automate `git bisect run` → the exact commit that introduced the bug |
| hypothesize | `debugmaster hunt .` / `scan-bugs . --class biz` | static + business-logic + history engines surface ranked suspects with evidence + fix hint |
| review | `debugmaster review . --base main` | "is this change safe?" → APPROVE / COMMENT / REQUEST-CHANGES on the diff, plus forgotten-edit suspects |
| verify | `debugmaster fix-verify <file> <rule_id> <line>` | run the finding's verify command, re-scan the file, and on a clean pass auto-record feedback so the ranker learns |
| **runtime** | `debugmaster profile -- <cmd>` | diagnose memory/fd/thread/gpu leaks, cpu bottlenecks, and orphan processes while the code RUNS (not just static) |
| triage | `debugmaster hunt --triage` | local-LLM second opinion on the top suspects (real vs false-positive) |
| prevent | `debugmaster install-hooks .` · `debugmaster regress <file> <rule>` | pre-commit gate; and a generated pytest that locks a fixed bug so it can never regress |
| watch | `debugmaster watch .` | re-scan changed files on every save (tight inner loop) |
| agent | `debugmaster mcp` | run as an MCP server — `hunt`/`audit`/`review`/`explain`/`profile` as tools for Claude Code / Codex / Cursor |

Each `hunt` finding already carries its own `verify:` command, so any suspect is
independently confirmable. Confirm or dismiss to teach the ranker:
`debugmaster learn-feedback <file> <line> <rule_id> real|fake`.

## Super-audit (`debugmaster audit`)

`hunt` finds suspects; `audit` **grades the repo** and decides whether it ships. One
full pipeline pass becomes:

- a **0–100 score + letter grade per dimension** — security, business-logic,
  correctness, reliability, maintainability, test-coverage;
- a **release-readiness verdict**: `SHIP` (clean, ≥C), `FIX-FIRST` (a high, or <C),
  `BLOCK` (any critical) — non-zero exit unless `SHIP`, so it gates CI;
- a **trend**: `--save-baseline` locks the bar; later runs show score delta and
  **regressions introduced vs findings fixed**;
- a **coverage** block (scanners run, history mined, dirty files, suppressed count)
  so a clean grade can't hide what was skipped — *no silent caps*.

## Suppression — kill false-positive fatigue

The reason teams abandon scanners is noise. Two explicit, reviewable mutes:

- `.debugmaster-ignore` at the repo root — `rule`, `path-glob:rule`, or `path-glob`;
- inline `# debugmaster: ignore[rule-id]` (or `// …`) on the offending line.

The **suppressed count is always reported** in the audit, so over-muting is visible.
This repo's own `.debugmaster-ignore` is the canonical example (it exempts the
engine's rule-pattern self-matches and test fixtures).

## What `hunt` runs (six engines, one bounded pass)

1. **static** (`bughunt`) — 29 cross-language rules + Python AST: swallowed errors, mutable defaults, blocking-in-async, copy-paste asymmetry, injection, secrets, TOCTOU, off-by-one …
2. **business-logic** (`bizlogic`) — IDOR/missing-ownership, float-money, oversell/check-then-act race, mass-assignment (over-posting), auth-no-ratelimit, idempotency-missing, pagination off-by-one, unscoped multi-tenant query. The "looks correct but is wrong" bugs, each a *suspect* with confidence + verify.
3. **fusion** — every installed scanner (ruff/bandit/gitleaks/shellcheck/actionlint, +deep semgrep/osv/trivy/vulture/clippy), normalized + deduped, total-time budgeted.
4. **suppression** (`suppress`) — drop accepted findings via `.debugmaster-ignore` + inline markers; the muted count is reported, never hidden.
5. **history** (`gitrisk`) — bug-fix density + logical co-change coupling (forgotten-edit suspects).
6. **risk model** (`riskmodel`) — P(bug) blend + optional IsolationForest.
7. **reach** — resolved/import fan-in for blast-radius + test-gap detection.

## Business-logic coverage

These are the bugs static analyzers, type checkers and security scanners
structurally cannot catch — they are about *intent and domain rules*:

- **IDOR / missing ownership** — endpoint fetches a record by id with no authz; stays silent when an ownership check or auth decorator is present.
- **float-money** — money cast to float, divided, or `==`-compared (incl. `order["amount"]`).
- **oversell / overdraw race** — `stock`/`balance`/`quota` read in a guard then written with no lock (check-then-act).
- **idempotency-missing** — a charge/order side-effect with a real gateway call and no idempotency key.
- **mass-assignment / over-posting** — the raw request body splatted into a model create/update (`Model(**request.json)`, `User.create(req.body)`); silent when fields are whitelisted.
- **auth-no-ratelimit** — a login/OTP/password-check path with no visible rate-limit, attempt counter, or lockout (brute-force exposure).
- **webhook-no-signature** — a payment/event webhook that reads the body but never verifies the signature; silent when `construct_event`/HMAC is present.
- **client-controlled-price** — a charge whose amount comes from the request (price tampering); silent on server-side lookups.
- For the full 200-surface revenue/billing checklist see `debugmaster checks` and `PLAYBOOK.md`.
- **SSRF** — an outbound HTTP request to a request-supplied URL with no host allowlist; silent when validated.
- **open-redirect** — a redirect target taken straight from the request; silent on static targets / view names.
- **pagination off-by-one**, **cents/dollars unit mismatch**, **unscoped multi-tenant query**.

## Report-section flows (used inside `hunt`/`all` reports)

`one_command_repo_truth` · `dirty_impact_debug` · `stack_specific_verification` ·
`security_dependency_triage` · `frontend_ui_regression` · `native_runtime_crash` ·
`backend_request_trace` · `monorepo_boundary_map` · `ai_handoff_compression` ·
`fallback_no_grepgod`. These structure the report; the seven loop commands above
are the primary entry points.

## Graceful degradation

`debugmaster doctor` shows which of the layers are live. Static + business-logic
engines are pure-stdlib and always on; scanners, ML, codegraph and git each add
depth when present and are skipped (not failed) when absent.
