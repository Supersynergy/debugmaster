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

# Build, install the binary on PATH, and stage the bundled engine where the
# binary finds it at runtime (~/.debugmaster/engine). One tool, no pip.
install: build
    mkdir -p ~/.debugmaster
    rsync -a --delete --exclude '__pycache__' --exclude 'reports' engine/ ~/.debugmaster/engine/
    mkdir -p ~/.local/bin
    ln -sf "$(pwd)/target/release/debugmaster" ~/.local/bin/debugmaster
    ~/.local/bin/debugmaster doctor

# Supply-chain / license / advisory gate (needs `cargo install cargo-deny`).
audit:
    cargo deny check

check:
    cargo fmt --all --check
    cargo test
    cargo clippy --all-targets --all-features -- -D warnings
    cargo build --release
    # Dogfood the native scanner on our own Rust code. Scan `src/` — not the repo
    # root — because the bundled `engine/` ships planted-bug test fixtures.
    ./target/release/debugmaster hunt src --json

ci: doctor check

# Pre-PR/release gate = ci + supply-chain audit.
pre-pr: ci audit

preview:
    ./target/release/debugmaster --help
    ./target/release/debugmaster hunt . -n 10
