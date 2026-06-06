# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| `0.1.x` | Yes |

## Reporting A Vulnerability

Please report vulnerabilities privately through GitHub Security Advisories for this repository when available.

If advisories are unavailable, contact the repository owner through the Supersynergy GitHub organization.

Do not open public issues for exploitable vulnerabilities, real credentials, or private tokens.

## Scope

Security-sensitive areas include:

- command execution and timeout handling
- report generation paths
- GitHub Actions templates
- handling of dirty worktrees
- optional integration with Grepgod, ghmax, Semgrep, Gitleaks, and OSV Scanner

## Design Notes

Debugmaster defaults to bounded, fail-safe behavior:

- optional tools are not required
- missing tools are warnings, not crashes
- security scans are opt-in with `--security`
- deep checks are opt-in with `--check-profile deep`
- generated reports do not intentionally include environment variables
