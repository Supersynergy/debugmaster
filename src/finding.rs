use serde::Serialize;

/// A single suspected bug: file:line, the rule that fired, and how to act.
#[derive(Clone, Debug, Serialize)]
pub struct Finding {
    pub file: String,
    pub line: usize,
    pub rule_id: String,
    pub severity: String,
    pub message: String,
    pub fix: String,
    pub cwe: String,
    pub snippet: String,
}

impl Finding {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        file: &str,
        line: usize,
        rule_id: &str,
        severity: &str,
        message: &str,
        fix: &str,
        cwe: &str,
        snippet: &str,
    ) -> Self {
        Finding {
            file: file.to_string(),
            line,
            rule_id: rule_id.to_string(),
            severity: severity.to_string(),
            message: message.to_string(),
            fix: fix.to_string(),
            cwe: cwe.to_string(),
            snippet: snippet.chars().take(160).collect(),
        }
    }
}

pub fn sev_rank(s: &str) -> u8 {
    match s {
        "critical" => 4,
        "high" => 3,
        "medium" => 2,
        "low" => 1,
        _ => 0,
    }
}
