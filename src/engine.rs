//! Bundled Python engine: locate and run the analysis engine that ships *inside*
//! this tool. There is no second binary to install — `debugmaster` carries its
//! engine in `engine/` and runs it through `python3`. The only runtime
//! requirement for the deep commands is a `python3` interpreter.

use std::ffi::OsString;
use std::path::PathBuf;
use std::process::{Command, ExitCode};

/// The interpreter used for the bundled engine (override with `DEBUGMASTER_PYTHON`).
fn python() -> String {
    std::env::var("DEBUGMASTER_PYTHON").unwrap_or_else(|_| "python3".to_string())
}

/// Resolve the bundled engine root (the dir that contains `bin/debugmaster`).
///
/// Lookup order: explicit override → installed user location → dev source tree →
/// locations relative to the running executable (packaged installs).
pub fn dir() -> Option<PathBuf> {
    if let Ok(p) = std::env::var("DEBUGMASTER_ENGINE") {
        let pb = PathBuf::from(p);
        if pb.join("bin/debugmaster").exists() {
            return Some(pb);
        }
    }

    let mut cands: Vec<PathBuf> = Vec::new();
    if let Some(home) = std::env::var_os("HOME") {
        cands.push(PathBuf::from(&home).join(".debugmaster/engine"));
    }
    // Dev / `cargo run`: the engine lives next to the source tree.
    cands.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("engine"));
    if let Ok(exe) = std::env::current_exe()
        && let Some(d) = exe.parent()
    {
        cands.push(d.join("engine"));
        cands.push(d.join("../engine"));
        cands.push(d.join("../share/debugmaster/engine"));
    }

    cands
        .into_iter()
        .find(|c| c.join("bin/debugmaster").exists())
}

/// Path to the engine entry script, if the engine is present.
pub fn entry() -> Option<PathBuf> {
    dir().map(|d| d.join("bin/debugmaster"))
}

/// Run a bundled-engine command with the given args, inheriting stdio.
/// Returns the engine's exit code, or a clear error if the engine/python is absent.
pub fn run(args: &[OsString]) -> ExitCode {
    let Some(script) = entry() else {
        eprintln!(
            "debugmaster: bundled engine not found.\n\
             Looked in $DEBUGMASTER_ENGINE, ~/.debugmaster/engine, the source tree, \
             and next to the binary.\n\
             Run `just install` (dev) or `debugmaster --version` from the repo, \
             or set DEBUGMASTER_ENGINE=<repo>/engine."
        );
        return ExitCode::FAILURE;
    };

    let mut cmd = Command::new(python());
    cmd.arg(&script).args(args);
    match cmd.status() {
        Ok(status) => ExitCode::from(status.code().unwrap_or(1) as u8),
        Err(err) => {
            eprintln!(
                "debugmaster: deep command needs `{}` to run the bundled engine: {err}",
                python()
            );
            ExitCode::FAILURE
        }
    }
}

/// Capture stdout of a bundled-engine command (used by native `doctor`).
pub fn capture(args: &[&str]) -> Option<String> {
    let script = entry()?;
    let out = Command::new(python())
        .arg(&script)
        .args(args)
        .output()
        .ok()?;
    if out.status.success() {
        String::from_utf8(out.stdout).ok()
    } else {
        None
    }
}

/// Is `cmd` an executable on PATH? (No external `which` dependency.)
pub fn have(cmd: &str) -> bool {
    let Some(paths) = std::env::var_os("PATH") else {
        return false;
    };
    std::env::split_paths(&paths).any(|dir| dir.join(cmd).is_file())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn engine_is_bundled_in_source_tree() {
        // The whole point of the consolidation: the engine ships inside the repo.
        let Some(d) = dir() else {
            panic!("bundled engine must resolve in the source tree");
        };
        assert!(d.join("bin/debugmaster").exists());
        assert!(d.join("lib").is_dir());
    }

    #[test]
    fn have_reports_nonexistent_as_false() {
        assert!(!have("definitely-not-a-real-binary-xyzzy-42"));
    }
}
