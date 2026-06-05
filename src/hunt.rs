use crate::finding::{Finding, sev_rank};
use crate::{bizlogic, rules, walk};
use rayon::prelude::*;
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::Path;

#[derive(Serialize)]
pub struct Report {
    pub repo: String,
    pub verdict: String,
    pub total: usize,
    pub files_scanned: usize,
    pub by_severity: BTreeMap<String, usize>,
    pub findings: Vec<Finding>,
}

pub fn hunt(root: &Path, limit: usize, top: usize) -> Report {
    let files = walk::source_files(root, limit);
    // true parallelism — one OS thread per core, no GIL, no process-pool overhead.
    let mut all: Vec<Finding> = files
        .par_iter()
        .flat_map(|(path, lang)| {
            let text = std::fs::read_to_string(path).unwrap_or_default();
            if text.is_empty() {
                return Vec::new();
            }
            let rel = walk::rel(root, path);
            let mut f = rules::scan_text(&rel, lang, &text);
            if *lang == "python" {
                f.extend(bizlogic::scan_python(&rel, &text));
            }
            f
        })
        .collect();

    all.sort_by(|a, b| {
        sev_rank(&b.severity)
            .cmp(&sev_rank(&a.severity))
            .then(a.file.cmp(&b.file))
            .then(a.line.cmp(&b.line))
    });

    let mut by_severity: BTreeMap<String, usize> = BTreeMap::new();
    for f in &all {
        *by_severity.entry(f.severity.clone()).or_insert(0) += 1;
    }
    let verdict = if files.is_empty() {
        // No source files matched — distinct from CLEAN so a mistyped or
        // wrong path is never reported as a passing scan.
        "NO_FILES"
    } else if by_severity.contains_key("critical") {
        "CRITICAL"
    } else if by_severity.contains_key("high") {
        "FAIL"
    } else if !all.is_empty() {
        "WARN"
    } else {
        "CLEAN"
    }
    .to_string();

    let total = all.len();
    all.truncate(top);
    Report {
        repo: root.display().to_string(),
        verdict,
        total,
        files_scanned: files.len(),
        by_severity,
        findings: all,
    }
}

pub fn markdown(r: &Report) -> String {
    let mut s = String::new();
    s.push_str(&format!("# Debugmaster Hunt — {}\n\n", r.repo));
    s.push_str(&format!(
        "Verdict: **{}** · {} findings · {} files\n\n",
        r.verdict, r.total, r.files_scanned
    ));
    if r.verdict == "NO_FILES" {
        s.push_str(
            "No source files matched in this path. Nothing was scanned — \
             this is **not** a clean bill of health. Check the path is correct.\n",
        );
        return s;
    }
    s.push_str("## Top suspects\n\n");
    if r.findings.is_empty() {
        s.push_str("- none — clean.\n");
    }
    for (i, f) in r.findings.iter().enumerate() {
        s.push_str(&format!(
            "{}. **{}** `{}:{}` [{}] — {}\n",
            i + 1,
            f.severity.to_uppercase(),
            f.file,
            f.line,
            f.rule_id,
            f.message
        ));
        if !f.fix.is_empty() {
            s.push_str(&format!("   - fix: {}\n", f.fix));
        }
    }
    s.push('\n');
    s
}
