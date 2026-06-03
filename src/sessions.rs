use ignore::WalkBuilder;
use serde::Serialize;
use serde_json::Value;
use std::path::{Path, PathBuf};

#[derive(Debug, Serialize)]
pub struct SessionReport {
    pub roots: Vec<String>,
    pub sessions_scanned: usize,
    pub matches: usize,
    pub hits: Vec<SessionHit>,
}

#[derive(Debug, Serialize)]
pub struct SessionHit {
    pub id: String,
    pub path: String,
    pub cwd: String,
    pub first_user: String,
    pub modified: u64,
}

pub fn default_roots() -> Vec<PathBuf> {
    let home = std::env::var_os("HOME").map(PathBuf::from);
    let Some(home) = home else {
        return Vec::new();
    };
    vec![home.join(".codex/sessions"), home.join(".claude/projects")]
        .into_iter()
        .filter(|p| p.is_dir())
        .collect()
}

pub fn scan(roots: &[PathBuf], query: Option<&str>, limit: usize) -> SessionReport {
    let needle = query.map(|q| q.to_lowercase());
    let mut sessions_scanned = 0usize;
    let mut hits = Vec::new();

    for root in roots {
        for path in jsonl_files(root) {
            sessions_scanned += 1;
            if let Some(hit) = read_hit(&path, needle.as_deref()) {
                hits.push(hit);
            }
        }
    }

    hits.sort_by(|a, b| {
        b.modified
            .cmp(&a.modified)
            .then_with(|| a.path.cmp(&b.path))
    });
    let matches = hits.len();
    hits.truncate(limit);

    SessionReport {
        roots: roots.iter().map(|p| p.display().to_string()).collect(),
        sessions_scanned,
        matches,
        hits,
    }
}

pub fn markdown(report: &SessionReport) -> String {
    let mut out = String::new();
    out.push_str("# Debugmaster Sessions\n\n");
    out.push_str(&format!(
        "Scanned **{}** sessions · **{}** matches\n\n",
        report.sessions_scanned, report.matches
    ));
    if report.hits.is_empty() {
        out.push_str("- none\n");
        return out;
    }
    for hit in &report.hits {
        out.push_str(&format!(
            "- `{}` `{}` — {}\n",
            hit.id,
            hit.cwd,
            hit.first_user.replace('\n', " ")
        ));
    }
    out
}

fn jsonl_files(root: &Path) -> Vec<PathBuf> {
    WalkBuilder::new(root)
        .hidden(false)
        .git_ignore(false)
        .build()
        .flatten()
        .map(|e| e.into_path())
        .filter(|p| p.is_file() && p.extension().and_then(|e| e.to_str()) == Some("jsonl"))
        .collect()
}

fn read_hit(path: &Path, needle: Option<&str>) -> Option<SessionHit> {
    let text = std::fs::read_to_string(path).ok()?;
    let mut cwd = String::new();
    let mut first_user = String::new();
    let mut searchable = String::new();

    for line in text.lines().take(400) {
        let Ok(value) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        let record = value.get("payload").unwrap_or(&value);
        if cwd.is_empty()
            && let Some(c) = record.get("cwd").and_then(Value::as_str)
        {
            cwd = c.to_string();
            searchable.push_str(c);
            searchable.push('\n');
        }
        if is_user_record(&value)
            && let Some(content) = extract_content(record).or_else(|| extract_content(&value))
        {
            if first_user.is_empty() {
                first_user = content.chars().take(240).collect();
            }
            searchable.push_str(&content);
            searchable.push('\n');
        }
    }

    let id = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("session")
        .to_string();
    searchable.push_str(&id);

    if let Some(needle) = needle
        && !searchable.to_lowercase().contains(needle)
    {
        return None;
    }

    let modified = path
        .metadata()
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs())
        .unwrap_or_default();

    Some(SessionHit {
        id,
        path: path.display().to_string(),
        cwd,
        first_user,
        modified,
    })
}

fn is_user_record(value: &Value) -> bool {
    let record = value.get("payload").unwrap_or(value);
    value.get("type").and_then(Value::as_str) == Some("user")
        || record.get("type").and_then(Value::as_str) == Some("user")
        || record.get("type").and_then(Value::as_str) == Some("user_message")
        || value.get("role").and_then(Value::as_str) == Some("user")
        || record.get("role").and_then(Value::as_str) == Some("user")
}

fn extract_content(value: &Value) -> Option<String> {
    if let Some(s) = value.get("content").and_then(Value::as_str) {
        return Some(s.to_string());
    }
    if let Some(s) = value
        .get("message")
        .and_then(|m| m.get("content"))
        .and_then(Value::as_str)
    {
        return Some(s.to_string());
    }
    if let Some(s) = value.get("message").and_then(Value::as_str) {
        return Some(s.to_string());
    }

    let content = value
        .get("message")
        .and_then(|m| m.get("content"))
        .or_else(|| value.get("content"))?;
    let arr = content.as_array()?;
    let mut parts = Vec::new();
    for item in arr {
        if let Some(text) = item.get("text").and_then(Value::as_str) {
            parts.push(text);
        }
    }
    (!parts.is_empty()).then(|| parts.join("\n"))
}
