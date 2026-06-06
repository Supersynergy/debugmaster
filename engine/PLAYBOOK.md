# Debugmaster Playbook — using it optimally

Three tools, one loop. This is how they fit together and when to reach for each.

## The three tools

| Tool | What it is | Reach for it when |
|---|---|---|
| **debugmaster** | static bug engine + runtime profiler + flows | "where are the bugs / is this safe / is it leaking" |
| **ghmax** | repo/code intelligence (GitStars, repo-lake, facets, mining) | "who else solved this / find a pattern across GitHub / discover prior art" |
| **ghgrep** | raw code grep mode (alias of ghmax) | "find this exact pattern in code, fast" |

`ghmax` and `ghgrep` are the **same binary**; the difference is mode. `ghgrep` ≈
`ghmax --fast --sources grep`. Use `ghmax` for intelligence, `ghgrep` for a fast grep.

> Perf note: raw-grep warm path is ~2 ms (≈500× the cold path). Live web sources
> (grep.app / GitHub) are rate-limited and need `gh auth`; the local cache + repo-lake
> are the fast, reliable path.

## The loop

```
assess     debugmaster audit .                 graded health + SHIP/FIX-FIRST/BLOCK
reproduce  debugmaster explain - < trace.txt   stacktrace → suspects
localize   debugmaster hunt . --dirty          ranked hidden bugs on your change
hypothesize debugmaster hunt . --triage        + local-LLM real/false-positive pass
runtime    debugmaster profile -- <cmd>        leaks / bottlenecks / orphans at runtime
prior art  ghmax "how others do X" --repos     find a reference implementation
find code  ghgrep "pattern" --fast             locate the exact code to change
verify     debugmaster fix-verify <f> <rule>   run verify cmd, re-scan, auto-learn
lock       debugmaster regress <f> <rule>      pytest that keeps the fix fixed
prevent    debugmaster install-hooks .         pre-commit gate
ship-from-agent  debugmaster mcp               expose all of the above as MCP tools
```

## Business / revenue debugging (the catalog)

`debugmaster checks` is a catalog of **200 revenue/billing failure surfaces** — the
high-value places money/billing logic breaks. It is a launchpad, not magic:

```bash
debugmaster checks --stats                 # coverage: 200 checks, by domain
debugmaster checks --domain payments       # the 23 payment checks
debugmaster checks --detected              # the 13 debugmaster ALREADY auto-finds
debugmaster checks "webhook" --json        # everything webhook-related, machine-readable
```

Each check is one of two kinds:

- **auto-detected** (🤖) — debugmaster finds it statically. Just run
  `debugmaster hunt . --class biz` / `debugmaster audit .`. These include the
  highest-impact billing bugs:
  - `biz-webhook-no-signature` — a payment webhook that never verifies the signature
    (anyone can forge `payment.succeeded`).
  - `biz-client-controlled-price` — a charge whose amount comes from the request
    (price tampering).
  - `biz-idempotency-missing` — a charge with no idempotency key (double-charge on retry).
  - `biz-float-money`, `biz-unit-mismatch`, `biz-idor-missing-ownership`, `retry-no-backoff`.
- **search + verify** — not statically decidable (needs runtime data / domain rules).
  The catalog hands you a ready `ghgrep` query to locate the code, then you verify the
  invariant by hand. Example: `debug_ledger_unbalanced_journal` →
  `ghgrep "ledger unbalanced journal" --fast --sources grep`.

### Recipe: audit a billing codebase

```bash
debugmaster audit . --profile deep          # graded health incl. the auto-detected billing bugs
debugmaster checks --domain payments        # the full payment checklist
debugmaster checks --domain webhook --detected   # what's covered vs what to grep
ghgrep "webhook constructEvent" --fast      # locate webhook handlers to verify by hand
```

## Optimal flags

- **Speed / good neighbour:** parallelism is capped at ~75% of cores. Tune with
  `DEBUGMASTER_CPU_FRACTION=0.5` or `DEBUGMASTER_WORKERS=4`.
- **Noise:** accepted findings → `.debugmaster-ignore` (`rule`, `path:rule`, `path`)
  or inline `# debugmaster: ignore[rule]`. The suppressed count is always reported.
- **CI gate:** `debugmaster audit .` exits non-zero unless `SHIP`; `review --comment`
  posts the verdict to the PR (gh/glab).
- **Agent:** wire `debugmaster mcp` once and call `hunt`/`audit`/`review`/`explain`/
  `profile` as tools from Claude Code / Codex / Cursor.

## One-liners worth memorizing

```bash
debugmaster audit .                          # is the repo shippable?
debugmaster hunt . --dirty --triage          # bugs on my change, LLM-triaged
debugmaster profile -- python3 app.py        # is it leaking / bottlenecked?
debugmaster checks --detected                # billing bugs I get for free
debugmaster review . --base main --comment   # PR verdict, posted
ghgrep "pattern" --fast                       # fast code grep
ghmax --gitstars 100 --gitstars-window 24h   # what's trending to learn from
```
