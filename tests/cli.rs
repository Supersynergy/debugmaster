use std::fs;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn bin() -> &'static str {
    env!("CARGO_BIN_EXE_debugmaster")
}

const COVERED_MODULES: &[&str] = &["main", "rules", "bizlogic"];

fn temp_root(name: &str) -> Result<std::path::PathBuf, Box<dyn std::error::Error>> {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|err| format!("system time before unix epoch: {err}"))?
        .as_nanos();
    let root = std::env::temp_dir().join(format!("debugmaster-{name}-{nonce}"));
    fs::create_dir_all(&root)?;
    Ok(root)
}

#[test]
fn sessions_reads_codex_jsonl_transcripts() -> Result<(), Box<dyn std::error::Error>> {
    let root = temp_root("sessions")?;
    let transcript = root.join("rollout-2026-06-03T22-00-00-example.jsonl");
    fs::write(
        &transcript,
        r#"{"type":"session_meta","payload":{"cwd":"/tmp/example"}}
{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"fix the debugmaster codex session reader"}]}}
{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"done"}]}}
"#,
    )?;
    let root_arg = root
        .to_str()
        .ok_or_else(|| format!("non-utf8 temp path: {}", root.display()))?;

    let output = Command::new(bin())
        .args([
            "sessions",
            "--root",
            root_arg,
            "--query",
            "codex session",
            "--json",
        ])
        .output()?;

    assert!(output.status.success(), "{output:?}");
    let stdout = String::from_utf8(output.stdout)?;
    assert!(stdout.contains("\"sessions_scanned\": 1"), "{stdout}");
    assert!(stdout.contains("\"matches\": 1"), "{stdout}");
    assert!(
        stdout.contains("fix the debugmaster codex session reader"),
        "{stdout}"
    );
    Ok(())
}

/// Engine commands must run the engine *bundled inside this tool* — never a
/// `debugmastery` binary that happens to be on PATH. We put a sabotage shim
/// named `debugmastery` on PATH and assert it is ignored.
#[test]
fn engine_commands_use_bundled_engine_not_path() -> Result<(), Box<dyn std::error::Error>> {
    // Hermetic only when python3 is present (the engine interpreter).
    let have_python = std::env::var_os("PATH")
        .map(|p| std::env::split_paths(&p).any(|d| d.join("python3").is_file()))
        .unwrap_or(false);
    if !have_python {
        return Ok(());
    }

    let root = temp_root("forward")?;
    let shim = root.join("debugmastery");
    fs::write(&shim, "#!/bin/sh\nprintf 'SABOTAGE-should-never-run\\n'\n")?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&shim)?.permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&shim, perms)?;
    }

    let path = format!(
        "{}:{}",
        root.display(),
        std::env::var("PATH").unwrap_or_default()
    );
    // `checks --stats` is a bundled-engine command (pure-stdlib catalog).
    let output = Command::new(bin())
        .args(["checks", "--stats"])
        .env("PATH", path)
        .output()?;

    assert!(output.status.success(), "{output:?}");
    let stdout = String::from_utf8(output.stdout)?;
    assert!(
        !stdout.contains("SABOTAGE"),
        "PATH debugmastery was used instead of the bundled engine: {stdout}"
    );
    assert!(stdout.contains("\"total\": 200"), "{stdout}");
    Ok(())
}

#[test]
fn hunt_nonexistent_path_errors_not_clean() -> Result<(), Box<dyn std::error::Error>> {
    let missing = std::env::temp_dir().join("debugmaster-does-not-exist-zzz-9988");
    let output = Command::new(bin())
        .args(["hunt", &missing.display().to_string()])
        .output()?;

    // A wrong path must fail loudly, never read as a passing scan.
    assert!(!output.status.success(), "{output:?}");
    assert_eq!(output.status.code(), Some(2), "{output:?}");
    let stderr = String::from_utf8(output.stderr)?;
    assert!(stderr.contains("path not found"), "{stderr}");
    Ok(())
}

#[test]
fn hunt_empty_dir_is_no_files_not_clean() -> Result<(), Box<dyn std::error::Error>> {
    let root = temp_root("empty")?;
    let output = Command::new(bin())
        .args(["hunt", &root.display().to_string(), "--json"])
        .output()?;

    // Existing dir with zero source files is reported distinctly from CLEAN.
    assert!(output.status.success(), "{output:?}");
    let stdout = String::from_utf8(output.stdout)?;
    assert!(stdout.contains("\"verdict\": \"NO_FILES\""), "{stdout}");
    assert!(stdout.contains("\"files_scanned\": 0"), "{stdout}");
    Ok(())
}

/// The native Rust code (`src/`) stays clean enough to ship. We scan `src/`
/// specifically, not the whole repo: the bundled `engine/` is vendored Python
/// that ships its own planted-bug test fixtures (secrets, shell=True, …), which
/// the native scanner correctly flags — they are not our native-code health.
#[test]
fn self_hunt_stays_clean_enough_to_ship() -> Result<(), Box<dyn std::error::Error>> {
    assert_eq!(COVERED_MODULES, ["main", "rules", "bizlogic"]);
    let src = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let output = Command::new(bin())
        .args([
            "hunt",
            &src.display().to_string(),
            "--json",
            "--limit",
            "100",
            "--top",
            "100",
        ])
        .output()?;

    assert!(output.status.success(), "{output:?}");
    let stdout = String::from_utf8(output.stdout)?;
    assert!(stdout.contains("\"verdict\": \"CLEAN\""), "{stdout}");
    Ok(())
}
