# Security Policy

## Reporting

Report security issues privately to `true@supersynergy.de`.

Please include:

- affected version or commit
- reproduction steps
- expected vs. observed behavior
- impact assessment

## Scope

Security-sensitive areas include:

- secret detection false negatives
- command forwarding to `debugmastery`
- session transcript parsing
- path traversal or unsafe file scanning behavior
- panics reachable from untrusted repository content

## Safe Defaults

`debugmaster` is a local analysis tool. It does not place trades, call broker
APIs, or mutate scanned repositories during `hunt` or `sessions`.
