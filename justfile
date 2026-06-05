set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

setup:
    cargo fetch

doctor:
    cargo --version
    rustc --version
    cargo metadata --format-version 1 >/dev/null

fmt:
    cargo fmt --all

test:
    cargo test

lint:
    cargo clippy --all-targets --all-features -- -D warnings

build:
    cargo build --release

# Supply-chain / license / advisory gate (needs `cargo install cargo-deny`).
audit:
    cargo deny check

check:
    cargo fmt --all --check
    cargo test
    cargo clippy --all-targets --all-features -- -D warnings
    cargo build --release
    ./target/release/debugmaster hunt . --json

ci: doctor check

# Pre-PR/release gate = ci + supply-chain audit.
pre-pr: ci audit

preview:
    ./target/release/debugmaster --help
    ./target/release/debugmaster hunt . -n 10
