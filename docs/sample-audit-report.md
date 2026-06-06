<!-- Generated sample: `debugmaster audit engine` on the bundled engine.
     Shows the best-possible report shape: graded verdict, 6-dim matrix,
     must-fix, pipeline flow-trace, coverage. Regenerate: debugmaster audit <repo> -->

# Debugmaster Super-Audit — /Users/master/BASE/projects/debugmaster/engine

## Grade **A** (90/100) · Release: **FIX-FIRST**
_2 high finding(s); overall 90/100 below the C bar._  ·  1.9s · profile `fast`

| Dimension | Grade | Score | Findings | Worst |
|---|:--:|--:|--:|---|
| business logic | A | 92 | 2 | medium |
| security | A | 100 | 0 | — |
| correctness | A | 94 | 4 | low |
| reliability | A | 100 | 0 | — |
| test coverage | A | 100 | 0 | — |
| maintainability | F | 30 | 19 | high |

## Must-fix (top per dimension)

### business logic
- **MEDIUM** `lib/hunt.py:398` [biz-float-money] — A money value is divided in floating point — fractional cents accumulate rounding error.
  - fix: Use integer minor units (cents) or Decimal; round explicitly at the boundary.
  - verify: `python3 -m py_compile lib/hunt.py && ruff check lib/hunt.py`

### maintainability
- **HIGH** `./lib/hunt.py:349` [bandit:B324] — Use of weak SHA1 hash for security. Consider usedforsecurity=False
  - verify: `python3 -m py_compile ./lib/hunt.py && ruff check ./lib/hunt.py`
- **HIGH** `./lib/learn.py:75` [bandit:B324] — Use of weak SHA1 hash for security. Consider usedforsecurity=False
  - verify: `python3 -m py_compile ./lib/learn.py && ruff check ./lib/learn.py`
- **MEDIUM** `./lib/triage.py:36` [bandit:B310] — Audit url open for permitted schemes. Allowing use of file:/ or custom schemes is often unexpected.
  - verify: `python3 -m py_compile ./lib/triage.py && ruff check ./lib/triage.py`

## Pipeline flow (every stage, no hidden steps)

- `1·dirty-set (git porcelain) `     0ms  → 0 items
- `2·static + business-logic   `   212ms ██ → 45 items
- `3·tool fusion (scanners)    `   498ms ██████ → 20 items
- `4·dedupe + suppress         `     1ms  → 25 items  (−33 suppressed)
- `5·git-history mine          `     0ms  → 0 items
- `6·learned precision         `     0ms  → 13 items
- `7·risk model + reach        `  1205ms ███████████████ → 12 items
- `8·rank                      `     0ms  → 25 items
- _total pipeline: 1916ms across 8 stages_

## Coverage (no silent caps)
- scanners run: ruff(0), bandit(20), gitleaks[skip], shellcheck(0), actionlint[skip], biome[skip], oxlint[skip]
- history mined: False · dirty files: 0 · suppressed: 33
- test_coverage reflects changed files only (test-gap runs on the diff).
- All layers live — full-depth hunts available.

## Act
1. Clear BLOCK/critical first, then high.
2. Re-run `debugmaster audit --save-baseline` to lock the new bar.
3. `debugmaster fix-verify <file> <rule_id> <line>` to fix-and-teach.


