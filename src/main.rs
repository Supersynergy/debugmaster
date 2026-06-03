mod bizlogic;
mod finding;
mod hunt;
mod rules;
mod walk;

use clap::{Parser, Subcommand};
use std::path::PathBuf;
use std::process::ExitCode;

/// Single-binary bug hunter: static + business-logic detectors over tree-sitter ASTs.
#[derive(Parser)]
#[command(name = "debugmaster", version, about)]
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
            let report = hunt::hunt(&path, limit, top);
            if json {
                println!("{}", serde_json::to_string_pretty(&report).unwrap());
            } else {
                print!("{}", hunt::markdown(&report));
            }
            match report.verdict.as_str() {
                "CLEAN" | "WARN" => ExitCode::SUCCESS,
                _ => ExitCode::FAILURE,
            }
        }
    }
}
