use ignore::WalkBuilder;
use std::path::{Path, PathBuf};

/// Map a file extension to a language label (None = skip).
pub fn lang_of(path: &Path) -> Option<&'static str> {
    let ext = path.extension()?.to_str()?;
    Some(match ext {
        "py" | "pyi" => "python",
        "js" | "mjs" | "cjs" | "jsx" => "javascript",
        "ts" | "tsx" | "mts" | "cts" => "typescript",
        "go" => "go",
        "rs" => "rust",
        "sh" | "bash" | "zsh" => "shell",
        "rb" => "ruby",
        "java" => "java",
        "php" => "php",
        _ => return None,
    })
}

/// Repo-relative source files, gitignore-aware, bounded.
pub fn source_files(root: &Path, limit: usize) -> Vec<(PathBuf, &'static str)> {
    let mut out = Vec::new();
    let walker = WalkBuilder::new(root)
        .hidden(false)
        .git_ignore(true)
        .git_global(true)
        .filter_entry(|e| {
            let name = e.file_name().to_string_lossy();
            !matches!(
                name.as_ref(),
                ".git"
                    | "node_modules"
                    | ".venv"
                    | "venv"
                    | "dist"
                    | "build"
                    | "target"
                    | "__pycache__"
                    | ".next"
                    | "vendor"
                    | ".debugmaster"
            )
        })
        .build();
    for entry in walker.flatten() {
        if out.len() >= limit {
            break;
        }
        let path = entry.path();
        if path.is_file()
            && let Some(lang) = lang_of(path)
        {
            out.push((path.to_path_buf(), lang));
        }
    }
    out
}

pub fn rel(root: &Path, path: &Path) -> String {
    let stripped = path.strip_prefix(root).unwrap_or(path);
    if stripped.as_os_str().is_empty() {
        // path == root (single-file scan): fall back to basename, then full path.
        path.file_name()
            .unwrap_or(path.as_os_str())
            .to_string_lossy()
            .to_string()
    } else {
        stripped.to_string_lossy().to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    #[test]
    fn rel_single_file_returns_basename() {
        let p = Path::new("/tmp/foo/bar.py");
        // When root == path (single-file scan), rel must return the basename, not "".
        let result = rel(p, p);
        assert_eq!(result, "bar.py");
        assert!(!result.is_empty());
    }

    #[test]
    fn rel_directory_scan_returns_relative_path() {
        let root = Path::new("/tmp/foo");
        let path = Path::new("/tmp/foo/src/bar.py");
        assert_eq!(rel(root, path), "src/bar.py");
    }
}
