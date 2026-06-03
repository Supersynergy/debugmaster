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
    assert!(stdout.contains("fix the debugmaster codex session reader"), "{stdout}");
    Ok(())
}

#[test]
fn legacy_commands_forward_to_debugmastery() -> Result<(), Box<dyn std::error::Error>> {
    let root = temp_root("forward")?;
    let shim = root.join("debugmastery");
    fs::write(
        &shim,
        "#!/bin/sh\nprintf 'debugmastery-called:%s:%s\\n' \"$1\" \"$2\"\n",
    )?;
    let mut perms = fs::metadata(&shim)?.permissions();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        perms.set_mode(0o755);
        fs::set_permissions(&shim, perms)?;
    }

    let path = format!("{}:{}", root.display(), std::env::var("PATH").unwrap_or_default());
    let output = Command::new(bin())
        .args(["doctor", "--json"])
        .env("PATH", path)
        .output()?;

    assert!(output.status.success(), "{output:?}");
    let stdout = String::from_utf8(output.stdout)?;
    assert_eq!(stdout, "debugmastery-called:doctor:--json\n");
    Ok(())
}

#[test]
fn self_hunt_stays_clean_enough_to_ship() -> Result<(), Box<dyn std::error::Error>> {
    assert_eq!(COVERED_MODULES, ["main", "rules", "bizlogic"]);
    let output = Command::new(bin())
        .args([
            "hunt",
            env!("CARGO_MANIFEST_DIR"),
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
