use crate::finding::Finding;
use regex::Regex;
use std::sync::LazyLock;

/// A line-based static rule. `lang` empty = all languages. `guard` (if present and
/// matching the same line) suppresses the finding — the false-positive escape hatch.
pub struct Rule {
    pub id: &'static str,
    pub severity: &'static str,
    pub langs: &'static [&'static str],
    pub re: Regex,
    pub guard: Option<Regex>,
    pub message: &'static str,
    pub fix: &'static str,
    pub cwe: &'static str,
}

fn rx(p: &str) -> Regex {
    Regex::new(p).expect("rule regex")
}

pub static RULES: LazyLock<Vec<Rule>> = LazyLock::new(|| {
    vec![
        Rule {
            id: "secret-literal",
            severity: "critical",
            langs: &[],
            re: rx(
                r#"(?i)(api[_-]?key|secret|token|password|passwd|access[_-]?key|private[_-]?key)\s*[:=]\s*["'][A-Za-z0-9_\-/+=.]{16,}["']"#,
            ),
            guard: Some(rx(
                r"(?i)example|dummy|test|placeholder|xxx+|your[_-]|<|getenv|os\.environ|env\[|process\.env|\$\{|format",
            )),
            message: "A real-looking secret is hardcoded in source.",
            fix: "Move it to an env var / secret manager and rotate the leaked value.",
            cwe: "CWE-798",
        },
        Rule {
            id: "sql-concat",
            severity: "high",
            langs: &[],
            re: rx(
                r#"(?i)(select|insert|update|delete)\b[^;]*("\s*\+|'\s*\+|`\s*\+|%\s*\(|\.format\(|\$\{)"#,
            ),
            guard: Some(rx(r"(?i)//\s*ok|#\s*ok|\?\s*,|:\w+\b|%s")),
            message: "SQL built by string concatenation — injection risk.",
            fix: "Use parameterized queries / bound parameters.",
            cwe: "CWE-89",
        },
        Rule {
            id: "py-shell-true",
            severity: "high",
            langs: &["python"],
            re: rx(r"shell\s*=\s*True"),
            guard: None,
            message: "`shell=True` enables command injection if any arg is tainted.",
            fix: "Pass an argv list without shell=True; validate inputs.",
            cwe: "CWE-78",
        },
        Rule {
            id: "py-eval-exec",
            severity: "high",
            langs: &["python"],
            re: rx(r"\b(eval|exec)\s*\("),
            guard: Some(rx(r"(?i)ast\.|compile\(|//\s*ok|#\s*ok")),
            message: "`eval`/`exec` on dynamic input executes arbitrary code.",
            fix: "Avoid eval/exec; use ast.literal_eval or an explicit dispatch.",
            cwe: "CWE-95",
        },
        Rule {
            id: "py-bare-except",
            severity: "high",
            langs: &["python"],
            re: rx(r"^\s*except\s*:"),
            guard: None,
            message: "Bare `except:` swallows SystemExit/KeyboardInterrupt and masks bugs.",
            fix: "Catch a specific exception, or `except Exception:` and log/re-raise.",
            cwe: "CWE-396",
        },
        Rule {
            id: "py-eq-none",
            severity: "low",
            langs: &["python"],
            re: rx(r"[=!]=\s*None\b"),
            guard: None,
            message: "`== None` invokes __eq__ and can misbehave.",
            fix: "Use `is None` / `is not None`.",
            cwe: "CWE-697",
        },
        Rule {
            id: "py-request-no-timeout",
            severity: "medium",
            langs: &["python"],
            re: rx(
                r"\b(requests\.(get|post|put|delete|patch|head|request)|httpx\.(get|post|put|delete|patch|request)|urllib\.request\.urlopen|\burlopen)\s*\([^)]*\)",
            ),
            guard: Some(rx(r"timeout\s*=|#\s*ok|\bmock|session\.|adapter")),
            message: "HTTP call with no timeout can hang the thread forever (connection/thread leak).",
            fix: "Pass timeout=(connect, read); never leave a network call unbounded.",
            cwe: "CWE-400",
        },
        Rule {
            id: "js-loose-eq",
            severity: "low",
            langs: &["javascript", "typescript"],
            re: rx(r"[^=!<>]==[^=]"),
            guard: Some(rx(r"===|!==|//\s*ok")),
            message: "Loose equality `==` does type coercion — use `===`.",
            fix: "Use strict equality `===` / `!==`.",
            cwe: "CWE-697",
        },
        Rule {
            id: "js-empty-catch",
            severity: "high",
            langs: &["javascript", "typescript"],
            re: rx(r"catch\s*(\([^)]*\))?\s*\{\s*\}"),
            guard: None,
            message: "Empty catch hides the error and the stack trace.",
            fix: "Log or rethrow; at minimum comment why it is safe to ignore.",
            cwe: "CWE-390",
        },
        Rule {
            id: "rust-unwrap",
            severity: "medium",
            langs: &["rust"],
            re: rx(r"\.(unwrap|expect)\s*\("),
            guard: Some(rx(r"(?i)#\[(test|cfg\(test)|//|unwrap_or|tests?\b|assert")),
            message: "`unwrap()/expect()` panics on Err/None — a latent crash.",
            fix: "Use `?`, `match`, `unwrap_or`, or `if let`.",
            cwe: "CWE-248",
        },
        Rule {
            id: "go-ignored-err",
            severity: "high",
            langs: &["go"],
            re: rx(r",\s*_\s*:?=\s*\w+.*\b(err|error)\b"),
            guard: Some(rx(r"_test\.go|//\s*nolint")),
            message: "Error discarded with `_` — failures pass silently.",
            fix: "Handle the error or document why it is safe to drop.",
            cwe: "CWE-252",
        },
        Rule {
            id: "debug-leftover",
            severity: "low",
            langs: &[],
            re: rx(r"(?i)(pdb\.set_trace\(\)|breakpoint\(\)|debugger;|console\.log\(|dbg!\()"),
            guard: Some(rx(r"(?i)//\s*ok|#\s*ok|logger|logging")),
            message: "Debug leftover shipped to production.",
            fix: "Remove the debug statement.",
            cwe: "CWE-489",
        },
    ]
});

pub fn scan_text(rel: &str, lang: &str, text: &str) -> Vec<Finding> {
    let mut out = Vec::new();
    for (i, line) in text.lines().enumerate() {
        for rule in RULES.iter() {
            if !rule.langs.is_empty() && !rule.langs.contains(&lang) {
                continue;
            }
            if rule.re.is_match(line) && !rule.guard.as_ref().is_some_and(|g| g.is_match(line)) {
                out.push(Finding::new(
                    rel,
                    i + 1,
                    rule.id,
                    rule.severity,
                    rule.message,
                    rule.fix,
                    rule.cwe,
                    line.trim(),
                ));
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::scan_text;

    fn ids(lang: &str, src: &str) -> Vec<String> {
        scan_text("t", lang, src)
            .into_iter()
            .map(|f| f.rule_id)
            .collect()
    }

    #[test]
    fn secret_but_not_env() {
        assert!(
            ids("python", "API_KEY = 'sk_live_abcdef0123456789abcd'\n")
                .contains(&"secret-literal".to_string())
        );
        assert!(
            !ids("python", "API_KEY = os.environ['API_KEY']\n")
                .contains(&"secret-literal".to_string())
        );
    }

    #[test]
    fn shell_true_flagged() {
        assert!(
            ids("python", "subprocess.run(c, shell=True)\n").contains(&"py-shell-true".to_string())
        );
    }

    #[test]
    fn no_timeout_but_not_with_timeout() {
        assert!(ids("python", "requests.get(u)\n").contains(&"py-request-no-timeout".to_string()));
        assert!(
            !ids("python", "requests.get(u, timeout=5)\n")
                .contains(&"py-request-no-timeout".to_string())
        );
    }

    #[test]
    fn lang_scoping() {
        // a python rule must not fire on a rust file
        assert!(
            !ids("rust", "subprocess.run(c, shell=True)\n").contains(&"py-shell-true".to_string())
        );
    }
}
