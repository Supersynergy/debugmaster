# GitHub And Gitea Tools

These are the remote tools and repositories surfaced during the grepgod healthmap/debugmaster work.

## Own Repos

| Repo | URL | Why it matters |
|---|---|---|
| grepgod | `https://git.marketdeck.io/Supersynergy/grepgod.git` | Local search router, map generator, healthmap, riskmap, debug assistant |
| mdviewy | `https://git.marketdeck.io/Supersynergy/mdviewy.git` | Real validation target for dirty-tree, monorepo, map, and health checks |
| mdviewy GitHub mirror | `https://github.com/Supersynergy/mdviewy` | Public mirror found via GitHub CLI |
| MarkFlowy upstream | `https://github.com/drl990114/MarkFlowy` | Upstream project for mdviewy lineage |

## Found Codegraph / Static Analysis Repos

| Repo | Stars seen | Language | URL | Useful concept |
|---|---:|---|---|---|
| davidfraser/pyan | 712 | Python | `https://github.com/davidfraser/pyan` | Static Python call dependency graph |
| mamuz/PhpDependencyAnalysis | 574 | PHP | `https://github.com/mamuz/PhpDependencyAnalysis` | Dependency-graph violation detection |
| xnuinside/codegraph | 477 | Python | `https://github.com/xnuinside/codegraph` | Static dependency graph, interactive visualization, massive object detection |
| Trismegiste/Mondrian | 393 | PHP | `https://github.com/Trismegiste/Mondrian` | Graph-theory based static analysis |
| clay-good/OpenLore | 151 | TypeScript | `https://github.com/clay-good/OpenLore` | Architectural memory, graph preflight, drift detection |
| brandondocusen/CntxtPY | 112 | Python | `https://github.com/brandondocusen/CntxtPY` | LLM context graph and codebase compression |
| Lekssays/codebadger | 109 | Python | `https://github.com/Lekssays/codebadger` | MCP server around Joern Code Property Graph and taint analysis |

## Patterns Adapted Into Grepgod

| Source | Pattern | Debugmaster use |
|---|---|---|
| OpenLore | changed files + graph commit/working commit + staleness/impact summary | `grepgod healthmap .` ranks dirty files by graph impact and risk proximity |
| codegraph/CntxtPY | map first, then query the graph instead of re-reading repo files | `grepgod --chain map .` writes `.grepgod/MAP.md` and JSON indexes |
| codebadger/Joern style | security-oriented code property graph thinking | `grepgod --chain security` plus riskmap/high-impact files |
| pyan | simple static call graph is still high leverage | `funcmap` and `flowmap` remain dependency-light and fast |

## Discovery Commands

```bash
ghmax --repos "code graph static analysis" --stars-min 100 -n 8 --sort stars --format compact
ghmax --repos "AI coding agent codebase analysis bug fix" --stars-min 500 -n 12 --sort stars --format compact
grepgod --chain map .
grepgod ask . "hotspots"
grepgod ask . "risks"
```
