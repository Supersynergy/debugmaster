"""Defect-risk model — rank files by P(bug) from fused signals.

Combines four cheap, independent oracles into one score in [0, 100]:
  history  : how often this file was fixed (gitrisk)
  structure: complexity / nesting / size (metrics)
  findings : severity x learned-precision of static + fused findings in the file
  context  : dirty-now + blast-radius (how many files depend on it)

Pure-python weighted blend by default. If scikit-learn + numpy are present, an
unsupervised IsolationForest adds an anomaly bonus (needs no labels — it flags
files whose metric vector is an outlier vs the repo). Everything degrades: no ML
libs -> heuristic only; no git -> structure+findings only.
"""

from __future__ import annotations


try:
    from . import common
except ImportError:
    import common

# Tunable blend; learn.py can persist overrides later.
WEIGHTS = {"history": 0.30, "structure": 0.18, "findings": 0.32, "context": 0.20}


def _norm(x, hi):
    return min(max(x, 0.0) / hi, 1.0) if hi else 0.0


def score_files(signals: dict, weights: dict | None = None) -> dict[str, dict]:
    """signals[file] = {history, structure, finding_weight, dirty, fan_in}.
    Returns file -> {score, factors}."""
    w = weights or WEIGHTS
    if not signals:
        return {}
    max_fw = (
        max((s.get("finding_weight", 0.0) for s in signals.values()), default=0.0)
        or 1.0
    )
    max_fan = max((s.get("fan_in", 0) for s in signals.values()), default=0) or 1
    anomaly = _isolation_bonus(signals)
    out = {}
    for f, s in signals.items():
        history = _norm(s.get("history", 0.0), 100.0)
        structure = _norm(s.get("structure", 0.0), 100.0)
        findings = _norm(s.get("finding_weight", 0.0), max_fw)
        context = 0.6 * (1.0 if s.get("dirty") else 0.0) + 0.4 * _norm(
            s.get("fan_in", 0), max_fan
        )
        base = (
            w["history"] * history
            + w["structure"] * structure
            + w["findings"] * findings
            + w["context"] * context
        )
        score = 100.0 * base * (1.0 + 0.25 * anomaly.get(f, 0.0))
        out[f] = {
            "score": round(min(score, 100.0), 1),
            "factors": {
                "history": round(history, 2),
                "structure": round(structure, 2),
                "findings": round(findings, 2),
                "context": round(context, 2),
                "anomaly": round(anomaly.get(f, 0.0), 2),
            },
        }
    return out


def _isolation_bonus(signals: dict) -> dict[str, float]:
    """Unsupervised outlier score per file in [0,1]; 0 everywhere if no ML libs."""
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest
    except Exception:
        return {}
    files = list(signals)
    if len(files) < 12:
        return {}
    X = np.array(
        [
            [
                s.get("history", 0.0),
                s.get("structure", 0.0),
                s.get("finding_weight", 0.0),
                float(s.get("fan_in", 0)),
            ]
            for s in (signals[f] for f in files)
        ],
        dtype=float,
    )
    try:
        clf = IsolationForest(n_estimators=80, contamination="auto", random_state=0)
        clf.fit(X)
        raw = -clf.score_samples(X)  # higher = more anomalous
        lo, hi = raw.min(), raw.max()
        span = (hi - lo) or 1.0
        return {f: float((raw[i] - lo) / span) for i, f in enumerate(files)}
    except Exception:
        return {}


def finding_weight(
    findings, precision_map: dict[str, float] | None = None
) -> dict[str, float]:
    """Per-file weighted finding mass = Σ severity_rank * learned_precision."""
    pm = precision_map or {}
    agg: dict[str, float] = {}
    for f in findings:
        d = f.as_dict() if hasattr(f, "as_dict") else f
        sev = common.SEVERITY_RANK.get(d.get("severity", "medium"), 2)
        prec = pm.get(d.get("rule_id", ""), 0.6)
        agg[d["file"]] = agg.get(d["file"], 0.0) + sev * prec
    return agg


def blast_radius(repo, files) -> dict[str, int]:
    """Heuristic fan-in: how many other source files import each file's module/name.
    Cheap and language-agnostic via basename matching; refined by grepgod/codegraph
    when the hunt orchestrator supplies a real call graph."""
    from pathlib import Path

    stems = {}
    for rel in files:
        stem = Path(rel).stem
        if stem and stem not in ("index", "mod", "__init__", "main"):
            stems.setdefault(stem, []).append(rel)
    counts = {rel: 0 for rel in files}
    if not stems:
        return counts
    for path, _lang in common.iter_source_files(Path(repo), limit=6000):
        text = common.read_text(path)
        rel_self = common.rel(Path(repo), path)
        for stem, owners in stems.items():
            if stem in text:
                for owner in owners:
                    if owner != rel_self:
                        counts[owner] += 1
    return counts


if __name__ == "__main__":
    import json

    demo = {
        "a.py": {
            "history": 80,
            "structure": 60,
            "finding_weight": 9,
            "dirty": True,
            "fan_in": 12,
        },
        "b.py": {
            "history": 10,
            "structure": 20,
            "finding_weight": 1,
            "dirty": False,
            "fan_in": 1,
        },
    }
    print(json.dumps(score_files(demo), indent=2))
