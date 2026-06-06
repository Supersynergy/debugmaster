mod bizlogic;
mod doctor;
mod engine;
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
Native Rust (no interpreter): hunt, sessions, doctor.
Deep commands run the engine bundled inside this tool (needs python3, no second
install): `hunt --deep`, audit, review, profile, mcp, watch, fusion, checks,
regress, bisect, explain, fix-verify, install-hooks, scan-bugs, learn-feedback,
learn-stats, scan, repo, top-risk, codex-brief, catalog, engines, flows, init,
engines-install, autofix, mine, batch, init-ci, all."
)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Find the smallest hidden bugs, ranked by severity (incl. business-logic).
    ///
    /// Default is the fast native Rust scan. `--deep` runs the bundled engine's
    /// full pipeline (tool fusion + git-history + learned precision re-ranking),
    /// which produces a richer ranking at the cost of needing python3.
    Hunt {
        /// Repo or directory to scan.
        #[arg(default_value = ".")]
        path: PathBuf,
        /// Machine-readable JSON output.
        #[arg(long)]
        json: bool,
        /// Full engine pipeline (fusion + history + learned ranking) instead of the native scan.
        #[arg(long)]
        deep: bool,
        /// Max files to scan.
        #[arg(long, default_value_t = 50000)]
        limit: usize,
        /// Max findings to show.
        #[arg(short = 'n', long, default_value_t = 50)]
        top: usize,
    },
    /// Capability self-audit: which layers (native + bundled engine + scanners) are live.
    Doctor {
        /// Machine-readable JSON (default human summary).
        #[arg(long)]
        json: bool,
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
    /// Run deep/Python-era commands through the bundled engine.
    #[command(external_subcommand)]
    Legacy(Vec<OsString>),
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    match cli.cmd {
        Cmd::Hunt {
            path,
            json,
            deep,
            limit,
            top,
        } => {
            if !path.exists() {
                eprintln!("debugmaster: path not found: {}", path.display());
                return ExitCode::from(2);
            }
            if deep {
                // Full pipeline lives in the bundled engine — one ranking, no
                // silent divergence: native = fast, --deep = rich, by choice.
                let mut args: Vec<OsString> = vec!["hunt".into(), path.into()];
                if json {
                    args.push("--json".into());
                }
                return engine::run(&args);
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
        Cmd::Doctor { json } => {
            let report = doctor::report();
            if json {
                print_json(&report);
            } else {
                print!("{}", doctor::summary(&report));
            }
            ExitCode::SUCCESS
        }
        Cmd::Legacy(args) => {
            if args.is_empty() {
                return ExitCode::SUCCESS;
            }
            engine::run(&args)
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
