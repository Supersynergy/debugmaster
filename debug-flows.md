# Debugmaster Top Flows

Debugmaster is built around one rule: every report should imply the next fix.

The CLI combines cheap static context first, then only runs deeper engines when the repo proves they are relevant. This keeps it useful on Linux servers, fresh machines, and dirty monorepos where a full toolchain may not be installed yet.

## Flow 1: One Command Repo Truth

Trigger: new repo, restored session, unknown failure, or handoff to Codex/Claude.

Steps:

1. Read Git identity, branch, remotes, and dirty state.
2. Count packages, files, directories, extensions, and detected stacks.
3. Load Grepgod maps if available.
4. Run bounded build/test/check commands.
5. Emit Markdown, JSON, and AI brief.

Output: `PASS`, `WARN`, or `FAIL` plus the next 5 concrete fixes.

## Flow 2: Dirty Impact Debug

Trigger: many local changes, broken branch, or uncertain user edits.

Steps:

1. Exclude generated folders like `.grepgod`, `.codegraph`, `.debugmaster`, and `.repovista`.
2. Score dirty files by graph impact when Grepgod exists.
3. Fall back to changed-file count when Grepgod is missing.
4. Group the highest impact files into the report.
5. Tell the agent to inspect top-impact files before broad refactors.

Output: the smallest source files likely to explain the largest failure surface.

## Flow 3: Stack-Specific Verification

Trigger: repo has recognizable stack markers such as `Cargo.toml`, `next.config.ts`, `astro.config.mjs`, `go.mod`, `Dockerfile`, `Chart.yaml`, `Move.toml`, or `flake.nix`.

Steps:

1. Detect language and framework markers.
2. Attach official debugging/testing references.
3. Select only commands whose executable exists.
4. For npm/yarn/pnpm, run only scripts that exist in `package.json`.
5. Bound execution with a timeout and store stdout/stderr tails.

Output: real checks, not imagined checks.

## Flow 4: Security And Dependency Triage

Trigger: release, dependency diff, unexplained runtime bug, or suspicious history.

Steps:

1. Run `grepgod --chain security` when available.
2. Pull Semgrep, Gitleaks, and OSV style findings into one result.
3. Mark scan failure or real findings as report `FAIL`.
4. Put security review above feature work in `Next 5 Fixes`.

Output: dependency and secret risk queue with enough evidence for an agent to start.

## Flow 5: Frontend UI Regression

Trigger: Astro, Next.js, React, Vue, SvelteKit, Angular, Remix, Vite, or Tailwind bug.

Steps:

1. Run build, test, or check script if present.
2. Use framework references in the report.
3. Recommend browser devtools, Playwright trace viewer, and framework devtools.
4. Tie component files back to dirty impact.
5. Keep visual verification as the next step when a local dev URL exists.

Output: source-linked UI diagnosis path.

## Flow 6: Native Runtime Crash

Trigger: Rust, C/C++, Swift, Zig, D, Objective-C, Fortran, or WebAssembly crash/hang.

Steps:

1. Verify compile/test first.
2. Recommend LLDB/GDB or platform debugger.
3. Recommend sanitizers, Miri, Valgrind, or wasm tooling where relevant.
4. Use profiling tools for hot paths.

Output: crash frame, memory/race/UB hypothesis, and verification command.

## Flow 7: Backend Request Trace

Trigger: API failure, slow request, database issue, or distributed-service bug.

Steps:

1. Find endpoint and package markers.
2. Reproduce with `curl`, `hurl`, or framework tests.
3. Use OpenTelemetry/log correlation when available.
4. Inspect SQL with `EXPLAIN ANALYZE` when database files or queries are present.

Output: request path and likely failing boundary.

## Flow 8: Monorepo Boundary Map

Trigger: package boundary failure, shared module regression, or workspace drift.

Steps:

1. Count package markers across the repo.
2. Load import and call edges from Grepgod when available.
3. Link failing checks to package roots.
4. Rank shared code before leaf apps.

Output: which package to fix first and what depends on it.

## Flow 9: AI Handoff Compression

Trigger: Codex/Claude needs a fast, accurate state handoff.

Steps:

1. Write `debugmaster-report.json` as source of truth.
2. Write `debugmaster-report.md` for humans.
3. Write `debugmaster-ai-brief.md` for agents.
4. Include anti-revert instruction and exact next commands.

Output: compact agent context that avoids rereading the whole repo.

## Flow 10: No-Grepgod Fallback

Trigger: Linux CI, fresh machine, remote server, or Grepgod not installed.

Steps:

1. Use Python stdlib scanning.
2. Detect stacks from markers and file extensions.
3. Run only installed safe commands.
4. Mark Grepgod-specific features as skipped, not failed.

Output: portable all-in-one report without hard dependency on Grepgod.

## Feature Priorities

1. Lowest-friction truth: one command produces all report artifacts.
2. Evidence-first debugging: every failure includes the command and output tail.
3. Stack-aware references: each detected stack points to the right official docs.
4. Dirty-file safety: user changes are ranked, not reverted.
5. Agent-ready compression: JSON for machines, Markdown for humans, brief for AI.
6. Graceful degradation: missing engines reduce depth but do not break onboarding.
7. Monorepo awareness: package markers and graph data explain cross-package impact.
8. Solution implication: reports do not just list problems; they order the next fixes.
