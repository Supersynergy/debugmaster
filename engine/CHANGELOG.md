# Changelog

All notable changes to Debugmaster are documented here.

This project follows Semantic Versioning.

## [0.7.1] - 2026-06-03

### Added — two more high-value detectors (deepening coverage)

- **`py-request-no-timeout`** — an HTTP call (`requests`/`httpx`/`urlopen`) with no
  `timeout=` hangs the thread forever on a slow server (connection/thread leak under
  load). Silent when a timeout is set. **CWE-400.** Pairs with `profile` — the static
  cause of the runtime hangs it detects.
- **`biz-refund-client-amount`** — a refund/credit issued with an amount taken straight
  from the request (refund fraud: refund more than was paid). Silent on server-side
  amount lookups. **CWE-602.**

Catalog auto-detection rises from 13 → **16 / 200** across **9** detectors
(`audit_refund_amount_limits`, `audit_refund_approval_chain`,
`inspect_payment_provider_health` now map to real detectors).

## [0.7.0] - 2026-06-03

### Added — business / revenue debugging

- **Two new billing detectors** (the highest-impact, statically-detectable revenue bugs):
  - `biz-webhook-no-signature` — a payment/event webhook handler that reads the request
    body but never verifies the sender's signature (anyone can forge `payment.succeeded`).
    Silent when `construct_event` / HMAC / signature verification is present. **CWE-345.**
  - `biz-client-controlled-price` — a charge/payment created with an amount taken straight
    from the request (price tampering). Silent on server-side lookups. **CWE-602.**
- **`debugmaster checks` — business-debug catalog.** 200 revenue/billing failure surfaces
  (100 product-level + 100 implementation primitives across payments, subscription,
  invoice, ledger, refunds, checkout, tax, pricing, webhook, fulfillment, customer)
  as an actionable checklist — **not 200 stubs.** Each entry is either 🤖 auto-detected
  by debugmaster (13 map to 7 real detectors) or carries a ready `ghgrep` search +
  verify hint. Filter by `--domain`, `--kind`, `--detected`; `--stats` for coverage.
- **`PLAYBOOK.md`** — how to use debugmaster + ghmax + ghgrep together optimally: the
  loop, when to reach for each tool, billing-audit recipes, and the flags that matter.

## [0.6.0] - 2026-06-03

### Added — watch & regress

- **`debugmaster watch`** — re-scans changed files on every save (stdlib mtime poll,
  no watchdog dependency); prints a compact finding list per change. Tight inner-loop
  feedback while you code.
- **`debugmaster regress <file> <rule_id>`** — generates a runnable pytest that locks
  a confirmed finding as fixed: it re-invokes `debugmaster scan-bugs` on the file and
  asserts the rule no longer appears. Red while the bug is present, green once fixed,
  a permanent regression guard after that (skips cleanly if debugmaster isn't on PATH).

### Added — LLM triage (`hunt --triage`)

`hunt --triage` asks a **local** model (Ollama) for a second opinion on the top
suspects — REAL vs FALSE-POSITIVE with a one-line reason — and annotates each finding
(🤖, never silently dropped) so noise can be filtered eyes-open. Zero hard dependency:
stdlib urllib to `localhost:11434`; if the daemon is down it's a graceful no-op. Model
auto-picked (small instruct) or set via `DEBUGMASTER_TRIAGE_MODEL`. Closes the
LLM-triage gap (Gito/Chronos) while staying fully local.

### Added — PR-comment posting (`review --comment`)

`debugmaster review --comment` now posts the verdict + findings as a PR/MR comment
via `gh` (GitHub) or `glab` (GitLab) — closing the reviewdog gap so review results
land where the team sees them. `--pr <n>` targets a specific PR (default: the current
branch's). No CLI present, or not in a PR? The comment body is printed to stderr
instead — never a hard failure.

### Added — MCP server (`debugmaster mcp`)

debugmaster now runs as an **MCP server** so agents (Claude Code / Codex / Cursor)
can call it directly — the engine where the demand is. Pure-stdlib, newline-delimited
JSON-RPC 2.0 over stdio, no SDK dependency. Exposes five tools: `debugmaster_hunt`,
`debugmaster_audit`, `debugmaster_review`, `debugmaster_explain`, `debugmaster_profile`.
Wire it in:

```json
{ "mcpServers": { "debugmaster": { "command": "debugmaster", "args": ["mcp"] } } }
```

Tool failures are reported in-band (`isError`) and never crash the server.

### Added — runtime diagnostician (`debugmaster profile`)

`hunt` finds the bug in the source; **`profile` finds it while the code runs.** It
wraps a command (`debugmaster profile -- python3 app.py`) or attaches to a PID
(`--pid N`), samples the whole process tree, and — unlike a passive sampler such as
rescope — it *diagnoses* with a graded verdict (CLEAN / WARN / PROBLEM):

- **memory leak** — RSS fitted by least-squares; flagged on a sustained, *still-
  climbing* slope (reports MB/min + R² + growth×), not a one-off delta. Degenerate
  teardown samples are dropped so an exiting process can't mask a real leak.
- **fd / handle leak** and **thread leak** — descriptor/thread count trending up.
- **cpu bottleneck** — distinguishes *one process pinned ~1 core while the rest sit
  idle* (a parallelization opportunity) from healthy multi-core saturation.
- **gpu pressure** — utilization peak + VRAM-growth leak (NVIDIA via `nvidia-smi`,
  Apple Silicon via `ioreg` PerformanceStatistics).
- **orphan / zombie leak** — child processes still alive *after the command exits*,
  a post-run reconciliation no live sampler performs.

Each finding carries evidence + a fix hint. psutil drives full sampling; without it
the profiler degrades to a ps-based RSS/CPU view and says so. Output is md + json.

## [0.5.0] - 2026-06-02

### Performance — parallel, but never the whole machine

The static scan was single-core CPU-bound (rescope: one core at 99.7%). It now fans
out, with a deliberate core budget so a hunt never pins the box.

- **`common.worker_count()`** — one knob for all parallelism: ~**75% of cores** by
  default (16-core → 12 workers), so the editor/IDE/CI keep room. Overridable with
  `DEBUGMASTER_WORKERS=<n>` or `DEBUGMASTER_CPU_FRACTION=<0..1>`.
- **Parallel static scan.** `hunt._combined_static` fans bughunt+bizlogic across a
  **process pool** (fork; the GIL makes threads useless for AST work), sized to
  `worker_count`. Chunked for load balance; falls back to serial if a pool can't
  start. Output is byte-identical to serial (asserted by a test).
  → hunt on a 1192-file repo: **10.5s → ~5.8s** (warm); **16.4s → 5.8s vs the
  original**, peak RSS still flat (~280 MB).
- **Parallel scanner fusion.** `fusion.run` now runs scanners concurrently (wall =
  slowest scanner, not the sum — a gitleaks timeout no longer blocks bandit), with
  concurrency **and** each scanner's own thread pool capped (`RAYON_NUM_THREADS`/
  `OMP_NUM_THREADS` via `common.thread_cap_env`) so `pool × per-scanner-threads`
  stays within the core budget.
- **`reach.codegraph_fan_in`** thread pool now sized to `worker_count` (was a fixed 8).

`common.run` gained an `env` parameter (merged onto the environment) to support the
scanner thread caps.

## [0.4.0] - 2026-06-02

### Performance

Profiled with `rescope` (process/CPU/RAM) + cProfile on a 1192-file repo; **hunt
wall-time −36% (16.4s → 10.5s), peak RSS flat (~300 MB), findings byte-identical**:

- **Single-pass static scan.** bughunt + bizlogic now share one file walk: each file
  is read once and each Python file parsed once, with both AST visitors run on the
  same tree (`hunt._combined_static`). Previously every file was walked, read, and
  parsed twice. A test asserts the combined output equals running both separately.
- **Metrics scoped to candidates.** `metrics.metrics_for` computes complexity metrics
  only for the files actually risk-scored (findings/dirty/historically-risky) instead
  of the whole repo — several seconds saved on large repos.
- **Parallel codegraph fan-in.** `reach.codegraph_fan_in` ran one subprocess per
  target serially (≈4s of the hunt); the independent, I/O-bound calls now run on a
  thread pool.

### Added

- **Two new business-logic security detectors** (FP-controlled, AST + JS regex):
  - `biz-ssrf-user-url` — an outbound HTTP request whose URL comes from the inbound
    request with no host allowlist/validation (SSRF). Silent when validated.
  - `biz-open-redirect` — a redirect target taken straight from the request with no
    allowlist. Silent on static targets / view names (`redirect('home')`).

### Fixed

- **`audit` crashed on any run with scanners** (`--profile fast/deep` without
  `--no-fuse`): `coverage.scanners_run` is a list of `{tool,status,count}` dicts, but
  the markdown renderer joined them as strings (`TypeError`). The v0.3.0 audit was
  only exercised with `--no-fuse`. Now rendered as `ruff(1641), bandit[timeout], …`,
  which also surfaces scanner timeouts/skips — extending the "no silent caps" promise.

## [0.3.0] - 2026-06-02

### Added

- **`debugmaster audit` — super-audit.** A graded whole-repo health verdict on top
  of the full hunt pipeline: a 0-100 score + letter grade per dimension (security,
  business-logic, correctness, reliability, maintainability, test-coverage), an
  overall grade, and a **release-readiness verdict (SHIP / FIX-FIRST / BLOCK)**.
  Emits `debugmaster-audit.{md,json}`; exits non-zero unless `SHIP`.
- **Audit trend.** `--save-baseline` stores a fingerprinted baseline; later audits
  show score delta, **regressions introduced vs findings fixed**.
- **Finding suppression** (the #1 anti-fatigue feature): a `.debugmaster-ignore`
  file (`rule`, `path-glob:rule`, or `path-glob`) plus inline
  `# debugmaster: ignore[rule]` markers. The suppressed **count is always reported**
  in audit coverage, so a clean grade can't be faked by over-muting. Wired into
  `hunt` so every flow benefits.
- **Two new business-logic detectors**, both FP-controlled:
  - `biz-mass-assignment` (over-posting): the raw request body splatted into a
    model create/update (`Model(**request.json)`, `User.create(req.body)`) — Python
    AST + JS regex, silent when fields are whitelisted (`pick`/explicit kwargs).
  - `biz-auth-no-ratelimit`: a credential-check path (login/OTP/password) with no
    visible rate-limit, attempt counter, or lockout — brute-force exposure.
- Audit coverage block reports which scanners ran, history-mine status, dirty
  files, suppressed count, and engine advice — **no silent caps**.

### Changed

- Dogfood `.debugmaster-ignore` ships in this repo: it exempts the engine's own
  rule-pattern self-matches, test fixtures, deliberate best-effort IO swallows, and
  correct inclusive bounds — so `debugmaster audit .` self-grades **A / SHIP**
  (21 reviewed self-matches suppressed) instead of tripping on its own source.

## [0.2.0] - 2026-06-02

### Added

- `debugmaster engines-install` + `install-engines.sh`: one-command onboarding of
  the optional best-in-class engine stack (idempotent, `--dry-run`, `--list`,
  `--only <groups>`). Groups: fusion, js, go, rust, python-debug, native, llm, ml.
- Tool fusion now runs the June-2026 best-practice polyglot linters:
  **Biome** + **oxlint** (JS/TS), **golangci-lint** (Go, bundles
  staticcheck/govet/errcheck/gosec). Each is gated by availability and degrades to
  skip when absent (oxlint also skips the IDE-only wrapper safely).
- `doctor` reports the new scanners and points at `engines-install` when any are missing.
- Stack matrix surfaces Biome/oxlint (JS/TS) and golangci-lint/staticcheck (Go) as recommended engines.
- Release polish: premium public README with hero image, original "Codex" bug-hunter
  mascot (`docs/assets/`), and a `.gitleaks.toml` that allowlists test-fixture secrets
  so the secret gate stays green without weakening real-secret detection.

### Fixed

- `common`: PATH now includes language package-manager bin dirs (~/go/bin, ~/.bun/bin,
  ~/.cargo/bin, ~/.local/bin), so tools like staticcheck/golangci-lint/promptfoo are
  detected and runnable regardless of the caller's shell PATH.
- `doctor`: ML library report trimmed to libraries an actual layer consumes.

### Changed

- Fusion `fast` profile adds biome+oxlint; `deep` adds golangci-lint.

## [0.1.0] - 2026-06-01

### Added

- Standalone `debugmaster` CLI with `all`, `batch`, `autofix`, `mine`, `flows`, `catalog`, `scan`, `repo`, `top-risk`, `codex-brief`, and `init-ci`.
- All-in-one reports in Markdown, JSON, and AI brief formats.
- Batch report generation for folders of Git repositories.
- Safe autofix dry-run/apply mode for low-risk text cleanup.
- GitHub Actions pull-request report template.
- 64 language/framework stack detector with official references.
- 10 diagnostic flows for repo truth, dirty impact, stack verification, security, frontend, native crash, backend request trace, monorepo boundaries, AI handoff, and no-Grepgod fallback.
- Optional Grepgod health/map/security integration.
- Optional ghmax reference repo and pattern mining.

### Changed

- Default mode is fail-safe and fast: no full map, no security scan, and `--check-profile safe` unless deeper checks are explicitly requested.
- Timeouts and unavailable optional tools are warnings instead of process crashes.
- Structure scanning is bounded by `DEBUGMASTER_MAX_SCAN_FILES`.
- Shellcheck fan-out is bounded by `DEBUGMASTER_MAX_SHELLCHECK_FILES`.

### Fixed

- Minimal Ubuntu/Linux runs no longer fail when optional tools such as `shellcheck`, Grepgod, ghmax, cargo, pytest, or node are missing.
- Batch repo discovery correctly handles `.git` directories.
- Report generation avoids repeated full directory walks for structure and language detection.

### Security

- Security scans are opt-in via `--security`.
- Secret/dependency depth increases when Grepgod, Semgrep, Gitleaks, and OSV Scanner are installed.

### Breaking Changes

- None. This is the first public release.
