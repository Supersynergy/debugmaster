//! `doctor` — capability self-audit, native.
//!
//! Reports the Rust core (always live), whether the bundled engine + `python3`
//! are reachable, and which optional scanner layers are installed. When the
//! engine is present it merges the engine's own deeper layer/ML probe so a
//! single `doctor` call describes the whole tool, not just the Rust half.

use crate::engine;
use serde_json::{Value, json};

/// Scanners the tool fusion layer can consume (probed on PATH).
const SCANNERS: &[&str] = &[
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
];

pub fn report() -> Value {
    let scanners: serde_json::Map<String, Value> = SCANNERS
        .iter()
        .map(|s| (s.to_string(), Value::Bool(engine::have(s))))
        .collect();

    let python_ok = engine::have("python3") || engine::have("python");
    let engine_dir = engine::dir();
    let engine_present = engine_dir.is_some();

    // Native Rust layers — always available, no interpreter needed.
    let core = json!({
        "rust_hunt": true,          // native static + business-logic scan
        "rust_sessions": true,      // codex/claude transcript search
    });

    // Pull the engine's deep self-audit (ML libs, git-history, reach) if present.
    let engine_doctor: Option<Value> = if engine_present && python_ok {
        engine::capture(&["doctor"]).and_then(|s| serde_json::from_str(&s).ok())
    } else {
        None
    };

    let tool_fusion = ["ruff", "bandit", "semgrep", "gitleaks"]
        .iter()
        .any(|s| scanners.get(*s).and_then(Value::as_bool).unwrap_or(false));

    let mut advice: Vec<String> = Vec::new();
    if !python_ok {
        advice.push(
            "No python3 found — only native `hunt`/`sessions` work; deep commands \
             (audit/review/profile/mcp/fusion/…) need python3."
                .into(),
        );
    }
    if !engine_present {
        advice.push(
            "Bundled engine not located. Set DEBUGMASTER_ENGINE=<repo>/engine or run `just install`."
                .into(),
        );
    }
    if !tool_fusion {
        advice.push(
            "Install ruff + bandit (`uv pip install ruff bandit`) to enable tool fusion.".into(),
        );
    }
    let missing: Vec<&str> = SCANNERS
        .iter()
        .filter(|s| !scanners.get(**s).and_then(Value::as_bool).unwrap_or(false))
        .copied()
        .collect();
    if !missing.is_empty() {
        advice.push(format!(
            "Optional deeper scanners absent: {}",
            missing.join(", ")
        ));
    }
    if advice.is_empty() {
        advice.push("All layers live — full-depth hunts available.".into());
    }

    json!({
        "ok": true,
        "core": core,
        "engine": {
            "bundled": engine_present,
            "path": engine_dir.map(|d| d.display().to_string()),
            "python3": python_ok,
        },
        "tool_fusion": tool_fusion,
        "scanners": scanners,
        "engine_layers": engine_doctor,
        "advice": advice,
    })
}

/// Human-readable one-screen summary of [`report`].
pub fn summary(r: &Value) -> String {
    let mark = |b: bool| if b { "✓" } else { "·" };
    let mut s = String::from("# debugmaster doctor\n\n");

    s.push_str("Native (always on):\n");
    s.push_str("  ✓ hunt        static + business-logic scan\n");
    s.push_str("  ✓ sessions    codex/claude transcript search\n");
    s.push_str("  ✓ doctor      this report\n\n");

    let eng = &r["engine"];
    let bundled = eng["bundled"].as_bool().unwrap_or(false);
    let py = eng["python3"].as_bool().unwrap_or(false);
    s.push_str("Bundled engine (deep commands):\n");
    s.push_str(&format!(
        "  {} engine      {}\n",
        mark(bundled),
        eng["path"].as_str().unwrap_or("not found")
    ));
    s.push_str(&format!(
        "  {} python3     interpreter for the engine\n\n",
        mark(py)
    ));

    s.push_str(&format!(
        "  {} tool fusion (ruff/bandit/semgrep/gitleaks)\n",
        mark(r["tool_fusion"].as_bool().unwrap_or(false))
    ));
    if let Some(scanners) = r["scanners"].as_object() {
        let live: Vec<&str> = scanners
            .iter()
            .filter(|(_, v)| v.as_bool().unwrap_or(false))
            .map(|(k, _)| k.as_str())
            .collect();
        s.push_str(&format!(
            "    scanners live: {}\n",
            if live.is_empty() {
                "none".into()
            } else {
                live.join(", ")
            }
        ));
    }

    s.push_str("\nAdvice:\n");
    if let Some(tips) = r["advice"].as_array() {
        for t in tips {
            if let Some(t) = t.as_str() {
                s.push_str(&format!("  - {t}\n"));
            }
        }
    }
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn report_has_live_native_core() {
        let r = report();
        assert_eq!(r["ok"], serde_json::json!(true));
        assert_eq!(r["core"]["rust_hunt"], serde_json::json!(true));
        assert_eq!(r["core"]["rust_sessions"], serde_json::json!(true));
        // advice is always non-empty (at minimum the all-clear line).
        assert!(r["advice"].as_array().is_some_and(|a| !a.is_empty()));
    }

    #[test]
    fn summary_renders_without_panic() {
        let s = summary(&report());
        assert!(s.contains("debugmaster doctor"));
    }
}
