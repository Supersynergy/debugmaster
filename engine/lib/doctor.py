"""doctor — capability self-audit.

The whole tool promises graceful degradation; doctor makes that promise legible.
It reports which of the four layers (static, fusion, history, ML, reach) are live
on this machine, so an agent knows the depth of a hunt before trusting it and a
user knows exactly what to install to go deeper.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

try:
    from . import common
except ImportError:
    import common

SCANNERS = [
    "ruff",
    "bandit",
    "gitleaks",
    "shellcheck",
    "actionlint",
    "semgrep",
    "osv-scanner",
    "trivy",
    "vulture",
    "cargo",
    "mypy",
    "ast-grep",
    "biome",
    "oxlint",
    "golangci-lint",
    "shfmt",
    "staticcheck",
]
# Only libraries an actual layer consumes: numpy+sklearn power the IsolationForest
# risk model; catboost/lightgbm power ml_boost. (river/shap/mlflow are not wired to
# any layer, so reporting them would be theater — they live in `engines-install ml`.)
ML_LIBS = ["numpy", "sklearn", "catboost", "lightgbm"]
GRAPH = ["grepgod", "codegraph"]


def _have_mod(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def audit(repo: Path | None = None) -> dict:
    scanners = {s: common.have(s) for s in SCANNERS}
    ml = {m: _have_mod(m) for m in ML_LIBS}
    graph = {g: common.have(g) for g in GRAPH}
    layers = {
        "static_engine": True,  # pure stdlib, always on
        "business_logic_engine": True,  # pure stdlib, always on
        "active_flows": common.have("git"),  # review/explain/bisect
        "tool_fusion": any(
            scanners[s] for s in ("ruff", "bandit", "semgrep", "gitleaks")
        ),
        "git_history": common.have("git"),
        "ml_risk_model": ml["numpy"] and ml["sklearn"],
        "ml_boost": ml["lightgbm"] or ml["catboost"],
        "reach_codegraph": graph["codegraph"],
        "reach_grepgod": graph["grepgod"],
        "synapse_writeback": common.have("synx"),
    }
    live = sum(1 for v in layers.values() if v)
    return {
        "ok": True,
        "python": _have_mod("ast") and True,
        "layers": layers,
        "depth": f"{live}/{len(layers)} layers live",
        "scanners": scanners,
        "ml_libs": ml,
        "graph": graph,
        "advice": _advice(layers, scanners, ml),
    }


def _advice(layers, scanners, ml) -> list[str]:
    tips = []
    if not layers["tool_fusion"]:
        tips.append(
            "Install ruff + bandit (`uv pip install ruff bandit`) to enable tool fusion."
        )
    if not layers["ml_risk_model"]:
        tips.append(
            "Install scikit-learn + numpy for the IsolationForest risk model (heuristic used otherwise)."
        )
    if not (layers["reach_codegraph"] or layers["reach_grepgod"]):
        tips.append(
            "Install codegraph or grepgod for resolved call-graph blast-radius (import heuristic used otherwise)."
        )
    missing = [s for s, ok in scanners.items() if not ok]
    if missing:
        tips.append("Optional deeper scanners absent: " + ", ".join(missing))
        tips.append(
            "Install the full engine stack: `debugmaster engines-install --yes`"
        )
    if not tips:
        tips.append("All layers live — full-depth hunts available.")
    return tips


if __name__ == "__main__":
    import json

    print(json.dumps(audit(), indent=2))
