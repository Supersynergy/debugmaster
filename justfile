set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

setup:
    cargo fetch

doctor:
    cargo --version
    rustc --version
    cargo metadata --format-version 1 >/dev/null

test:
    cargo test

lint:
    cargo clippy --all-targets -- -D warnings

build:
    cargo build --release

check:
    cargo test
    cargo clippy --all-targets -- -D warnings
    cargo build --release
    ./target/release/debugmaster hunt . --json

ci: check

preview:
    ./target/release/debugmaster --help
    ./target/release/debugmaster hunt . -n 10
