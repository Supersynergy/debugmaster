mod bizlogic;
mod finding;
mod hunt;
mod rules;
mod sessions;
mod walk;

use clap::{Parser, Subcommand};
use std::ffi::OsString;
use std::path::PathBuf;
use std::process::ExitCode;

/// Single-binary bug hunter: static + business-logic detectors over tree-sitter ASTs.
#[derive(Parser)]
#[command(
    name = "debugmaster",
    version,
    about,
    after_help = "\
Native Rust: hunt, sessions.
Legacy parity: unknown commands are forwarded to `debugmastery` with the same args.
Python legacy command surface: fusion, learn-feedback, learn-stats, scan-bugs, doctor, mcp,
checks, watch, regress, profile, audit, review, bisect, explain, fix-verify,
install-hooks, scan, repo, top-risk, codex-brief, catalog, engines, flows, init,
engines-install, autofix, mine, batch, init-ci, all."
)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Find the smallest hidden bugs, ranked by severity (incl. business-logic).
    Hunt {
        /// Repo or directory to scan.
        #[arg(default_value = ".")]
        path: PathBuf,
        /// Machine-readable JSON output.
        #[arg(long)]
        json: bool,
        /// Max files to scan.
        #[arg(long, default_value_t = 50000)]
        limit: usize,
        /// Max findings to show.
        #[arg(short = 'n', long, default_value_t = 50)]
        top: usize,
    },
    /// Read Codex/Claude JSONL sessions and search their user prompts.
    Sessions {
        /// Session root to scan. Defaults to ~/.codex/sessions and ~/.claude/projects.
        #[arg(long)]
        root: Vec<PathBuf>,
        /// Case-insensitive query over session id, cwd, and user text.
        #[arg(short, long)]
        query: Option<String>,
        /// Machine-readable JSON output.
        #[arg(long)]
        json: bool,
        /// Max matching sessions to show.
        #[arg(short = 'n', long, default_value_t = 20)]
        limit: usize,
    },
    /// Forward Python-era commands to `debugmastery`.
    #[command(external_subcommand)]
    Legacy(Vec<OsString>),
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    match cli.cmd {
        Cmd::Hunt {
            path,
            json,
            limit,
            top,
        } => {
            if !path.exists() {
                eprintln!("debugmaster: path not found: {}", path.display());
                return ExitCode::from(2);
            }
            let report = hunt::hunt(&path, limit, top);
            if json {
                print_json(&report);
            } else {
                print!("{}", hunt::markdown(&report));
            }
            match report.verdict.as_str() {
                "CLEAN" | "WARN" | "NO_FILES" => ExitCode::SUCCESS,
                _ => ExitCode::FAILURE,
            }
        }
        Cmd::Sessions {
            root,
            query,
            json,
            limit,
        } => {
            let roots = if root.is_empty() {
                sessions::default_roots()
            } else {
                root
            };
            let report = sessions::scan(&roots, query.as_deref(), limit);
            if json {
                print_json(&report);
            } else {
                print!("{}", sessions::markdown(&report));
            }
            ExitCode::SUCCESS
        }
        Cmd::Legacy(args) => forward_legacy(args),
    }
}

fn forward_legacy(args: Vec<OsString>) -> ExitCode {
    if args.is_empty() {
        return ExitCode::SUCCESS;
    }
    let mut cmd = std::process::Command::new("debugmastery");
    cmd.args(args);
    match cmd.status() {
        Ok(status) => ExitCode::from(status.code().unwrap_or(1) as u8),
        Err(err) => {
            eprintln!(
                "debugmaster: legacy command needs `debugmastery` on PATH: {}",
                err
            );
            ExitCode::FAILURE
        }
    }
}

fn print_json<T: serde::Serialize>(value: &T) {
    match serde_json::to_string_pretty(value) {
        Ok(json) => println!("{json}"),
        Err(err) => {
            eprintln!("debugmaster: failed to serialize JSON output: {err}");
            std::process::exit(1);
        }
    }
}
