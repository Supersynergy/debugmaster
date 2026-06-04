# Contributing

`debugmaster` is a Rust-first bug hunter. Contributions should keep the tool
portable, fast, and useful as a single binary.

## Local Checks

Run the full gate before sending changes:

```bash
cargo test
cargo clippy --all-targets -- -D warnings
cargo build --release
./target/release/debugmaster hunt . --json
```

## Detector Changes

- Add a true-positive test and at least one false-positive guard test.
- Keep detector messages actionable: file, line, why it matters, and a fix.
- Avoid rule strings or fixtures that trigger the scanner on its own source.
- Prefer precise guards over broad suppressions.

## Pull Requests

- Keep each PR focused on one behavior or detector family.
- Update `CHANGELOG.md` for user-visible commands, detector changes, or releases.
- Include the verification commands you ran.
