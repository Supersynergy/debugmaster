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

# Faster test runner (10-15% speedup, binary listing 6% faster). Needs
# `cargo install cargo-nextest`. Falls back to `cargo test` if not installed.
nextest:
    #!/usr/bin/env bash
    if cargo nextest --version >/dev/null 2>&1; then
        cargo nextest run --all-features
    else
        cargo test --all-features
    fi

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
    @just _test-runner
    cargo clippy --all-targets --all-features -- -D warnings
    cargo build --release
    # Dogfood the native scanner on our own Rust code. Scan `src/` — not the repo
    # root — because the bundled `engine/` ships planted-bug test fixtures.
    ./target/release/debugmaster hunt src --json

# Internal: prefer nextest when installed, else cargo test.
_test-runner:
    #!/usr/bin/env bash
    if cargo nextest --version >/dev/null 2>&1; then
        cargo nextest run --all-features
    else
        cargo test --all-features
    fi

ci: doctor check

# Pre-PR/release gate = ci + supply-chain audit.
pre-pr: ci audit

# One-time per-clone: enable syntax-aware git merges via mergiraf 0.18.
# Needs `cargo install mergiraf`. Idempotent — safe to re-run.
mergiraf-setup:
    #!/usr/bin/env bash
    if ! command -v mergiraf >/dev/null 2>&1; then
        echo "mergiraf not installed — run: cargo install mergiraf" >&2
        exit 1
    fi
    git config merge.mergiraf.name "syntax-aware merge (mergiraf)"
    git config merge.mergiraf.driver "mergiraf merge --git %O %A %B -s %S -x %X -y %Y -l %P"
    git config merge.mergiraf.recursionlimit 100
    echo "mergiraf merge driver registered for this clone."

preview:
    ./target/release/debugmaster --help
    ./target/release/debugmaster hunt . -n 10
