"""super-audit — the whole-repo health verdict.

`hunt` finds and ranks suspects; `audit` grades the repo. It runs the full hunt
pipeline once, then turns the findings into a graded report a human or a release
gate can act on in one glance:

  * a 0-100 score + letter grade per DIMENSION (security, business-logic,
    correctness, reliability, maintainability, test-coverage),
  * an overall grade and a release-readiness verdict (SHIP / FIX-FIRST / BLOCK),
  * a TREND vs the last saved audit — regressions introduced vs findings fixed,
  * COVERAGE transparency: which engines ran, which were skipped, how many
    findings were suppressed (so a clean grade can't be faked by over-muting).

The grade is honest about scope: dimensions with no signal score 100 and say so.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

try:
    from . import common, doctor, hunt
except ImportError:
    import common
    import doctor
    import hunt

# Each finding maps to exactly ONE dimension. `biz-` is matched first so the
# business-logic engine stays cohesive (an IDOR is a business-logic access bug),
# then the remaining buckets by rule-id substring.
DIMENSIONS = [
    ("business_logic", ("biz-",), 1.4),
    (
        "security",
        (
            "secret",
            "sql-concat",
            "eval",
            "exec",
            "os-system",
            "shell-true",
            "injection",
            "ssrf",
            "todo-near-auth",
        ),
        1.4,
    ),
    (
        "correctness",
        (
            "off-by-one",
            "loose-eq",
            "eq-bool",
            "eq-none",
            "is-literal",
            "dup-boolop",
            "assert-tuple",
            "must-use-return",
            "assign-in-cond",
            "syntax-error",
        ),
        1.1,
    ),
    (
        "reliability",
        (
            "bare-except",
            "except-pass",
            "empty-catch",
            "floating-async",
            "blocking-in-async",
            "await-in-loop",
            "ignored-err",
            "let-underscore-result",
            "unwrap",
            "retry-no-backoff",
            "unbounded-queue",
            "outbox-after-commit",
            "toctou",
            "open-no-with",
        ),
        1.0,
    ),
    ("test_coverage", ("test-gap",), 0.6),
    (
        "maintainability",
        ("debug-leftover", "mutable-default", "naive-now", "utcnow", "ambient-global"),
        0.6,
    ),
]
PENALTY = {"critical": 45, "high": 18, "medium": 6, "low": 1.5, "info": 0.0}


def _dim_of(rule_id: str) -> str:
    for name, keys, _ in DIMENSIONS:
        if any(k in rule_id for k in keys):
            return name
    return "maintainability"  # default bucket for un-mapped rules


def _fmt_scanners(scanners) -> str:
    """Render fusion scanner entries (`{tool,status,count}` dicts) as a readable
    line; tolerate plain strings too. A `timeout`/`error` status is surfaced, not
    hidden — a scanner that didn't finish is exactly the kind of silent gap the
    audit promises to expose."""
    if not scanners:
        return "none"
    parts = []
    for s in scanners:
        if isinstance(s, dict):
            tool = s.get("tool", "?")
            status = s.get("status", "ok")
            if status == "ok":
                parts.append(f"{tool}({s.get('count', 0)})" if "count" in s else tool)
            else:
                parts.append(f"{tool}[{status}]")
        else:
            parts.append(str(s))
    return ", ".join(parts)


def _grade(score: float) -> str:
    return (
        "A"
        if score >= 90
        else "B"
        if score >= 80
        else "C"
        if score >= 70
        else "D"
        if score >= 60
        else "F"
    )


def _fingerprint(f: dict) -> str:
    # line-independent so cosmetic drift doesn't read as a new finding
    return f"{f['file']}::{f['rule_id']}"


def _baseline_path(repo: Path) -> Path:
    return repo / ".debugmaster" / "audit-baseline.json"


def audit(
    repo: Path,
    *,
    profile: str = "fast",
    fuse: bool = True,
    timeout: int = 90,
    save_baseline: bool = False,
) -> dict:
    repo = Path(repo).resolve()
    t0 = time.time()
    rep = hunt.hunt(
        repo,
        profile=profile,
        fuse=fuse,
        limit=100000,
        timeout=timeout,
        record=False,
    )
    findings = rep["top_suspects"]  # limit is huge -> this is every finding

    # bucket + score each dimension
    buckets: dict[str, list[dict]] = {name: [] for name, _, _ in DIMENSIONS}
    for f in findings:
        buckets[_dim_of(f["rule_id"])].append(f)

    dims = {}
    num, den = 0.0, 0.0
    for name, _keys, weight in DIMENSIONS:
        items = buckets[name]
        penalty = sum(PENALTY.get(f["severity"], 0) for f in items)
        score = max(0, round(100 - penalty))
        by_sev: dict[str, int] = {}
        for f in items:
            by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
        top = sorted(items, key=lambda f: f.get("priority", 0), reverse=True)[:3]
        dims[name] = {
            "score": score,
            "grade": _grade(score),
            "findings": len(items),
            "by_severity": by_sev,
            "weight": weight,
            "scope_note": "no signal — scored clean" if not items else "",
            "must_fix": [
                {
                    "file": f["file"],
                    "line": f["line"],
                    "rule_id": f["rule_id"],
                    "severity": f["severity"],
                    "message": f["message"][:160],
                    "fix": f.get("fix", ""),
                    "verify": f.get("verify", ""),
                }
                for f in top
                if f["severity"] in ("critical", "high", "medium")
            ],
        }
        num += score * weight
        den += weight

    overall = round(num / den) if den else 100
    sev_total = rep["totals"]["by_severity"]
    crit = sev_total.get("critical", 0)
    high = sev_total.get("high", 0)
    if crit:
        readiness, why = (
            "BLOCK",
            f"{crit} critical finding(s) must be fixed before release.",
        )
    elif high or overall < 70:
        readiness, why = (
            "FIX-FIRST",
            (
                f"{high} high finding(s); overall {overall}/100 below the C bar."
                if high
                else f"overall {overall}/100 is below the C bar (70)."
            ),
        )
    else:
        readiness, why = "SHIP", "no critical/high findings; overall grade C or better."

    # trend vs last saved baseline
    cur_fp = {_fingerprint(f) for f in findings}
    base = _load_baseline(repo)
    trend = None
    if base is not None:
        base_fp = set(base.get("fingerprints", []))
        new = sorted(cur_fp - base_fp)
        fixed = sorted(base_fp - cur_fp)
        trend = {
            "baseline_at": base.get("generated_at", "?"),
            "baseline_grade": base.get("grade", "?"),
            "baseline_score": base.get("score", "?"),
            "delta_score": overall - base.get("score", overall),
            "regressions": len(new),
            "fixed": len(fixed),
            "new_findings": new[:15],
            "fixed_findings": fixed[:15],
        }

    layers = doctor.audit(repo)
    out = {
        "repo": str(repo),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed_s": round(time.time() - t0, 1),
        "grade": _grade(overall),
        "score": overall,
        "release_readiness": readiness,
        "readiness_reason": why,
        "dimensions": dims,
        "totals": rep["totals"],
        "trend": trend,
        "coverage": {
            "profile": profile,
            "scanners_run": rep.get("scanners", []),
            "history_mined": rep.get("history_ok", False),
            "dirty_files": rep.get("dirty_files", 0),
            "suppressed": rep["totals"].get("suppressed", 0),
            "engine_advice": layers.get("advice", []),
            "note": "test_coverage reflects changed files only (test-gap runs on the diff).",
        },
        "risky_files": rep.get("risky_files", [])[:8],
        "cochange_suspects": rep.get("cochange_suspects", [])[:6],
    }

    if save_baseline:
        _save_baseline(repo, overall, out["grade"], cur_fp)
        out["baseline_saved"] = True
    return out


def _load_baseline(repo: Path) -> dict | None:
    f = _baseline_path(repo)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _save_baseline(repo: Path, score: int, grade: str, fingerprints: set[str]) -> None:
    try:
        d = repo / ".debugmaster"
        d.mkdir(parents=True, exist_ok=True)
        _baseline_path(repo).write_text(
            json.dumps(
                {
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "score": score,
                    "grade": grade,
                    "fingerprints": sorted(fingerprints),
                },
                indent=2,
            )
        )
    except OSError:
        pass


def markdown(a: dict) -> str:
    L = [
        f"# Debugmaster Super-Audit — {a['repo']}",
        "",
        f"## Grade **{a['grade']}** ({a['score']}/100) · Release: **{a['release_readiness']}**",
        f"_{a['readiness_reason']}_  ·  {a['elapsed_s']}s · profile `{a['coverage']['profile']}`",
        "",
        "| Dimension | Grade | Score | Findings | Worst |",
        "|---|:--:|--:|--:|---|",
    ]
    for name, dim in a["dimensions"].items():
        worst = (
            max(dim["by_severity"], key=lambda s: common.SEVERITY_RANK.get(s, 0))
            if dim["by_severity"]
            else "—"
        )
        L.append(
            f"| {name.replace('_', ' ')} | {dim['grade']} | {dim['score']} | "
            f"{dim['findings']} | {worst} |"
        )
    if a["trend"]:
        t = a["trend"]
        arrow = "▲" if t["delta_score"] > 0 else ("▼" if t["delta_score"] < 0 else "→")
        L += [
            "",
            "## Trend vs last audit",
            f"- score {arrow} {t['delta_score']:+d} (was {t['baseline_score']} {t['baseline_grade']}, {t['baseline_at']})",
            f"- **{t['regressions']} new** finding(s) · **{t['fixed']} fixed**",
        ]
        for fp in t["new_findings"]:
            L.append(f"  - new: `{fp}`")
    L += ["", "## Must-fix (top per dimension)"]
    any_mf = False
    for name, dim in a["dimensions"].items():
        if not dim["must_fix"]:
            continue
        any_mf = True
        L.append(f"\n### {name.replace('_', ' ')}")
        for m in dim["must_fix"]:
            L.append(
                f"- **{m['severity'].upper()}** `{m['file']}:{m['line']}` [{m['rule_id']}] — {m['message']}"
            )
            if m["fix"]:
                L.append(f"  - fix: {m['fix']}")
            if m["verify"]:
                L.append(f"  - verify: `{m['verify']}`")
    if not any_mf:
        L.append("- none — no critical/high/medium findings.")
    cov = a["coverage"]
    L += [
        "",
        "## Coverage (no silent caps)",
        f"- scanners run: {_fmt_scanners(cov['scanners_run'])}",
        f"- history mined: {cov['history_mined']} · dirty files: {cov['dirty_files']} · suppressed: {cov['suppressed']}",
        f"- {cov['note']}",
    ]
    for adv in cov["engine_advice"]:
        L.append(f"- {adv}")
    L += [
        "",
        "## Act",
        "1. Clear BLOCK/critical first, then high.",
        "2. Re-run `debugmaster audit --save-baseline` to lock the new bar.",
        "3. `debugmaster fix-verify <file> <rule_id> <line>` to fix-and-teach.",
        "",
    ]
    return "\n".join(L) + "\n"


def write(a: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "debugmaster-audit.json").write_text(json.dumps(a, indent=2))
    (out_dir / "debugmaster-audit.md").write_text(markdown(a))


if __name__ == "__main__":
    import sys

    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    print(markdown(audit(repo, fuse="--no-fuse" not in sys.argv)))
