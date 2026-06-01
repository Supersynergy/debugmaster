#!/usr/bin/env bash
# Debugmaster installer/init helper. No package manager required.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local/bin}"
LINK=0

for arg in "$@"; do
  case "$arg" in
    --link) LINK=1 ;;
    --prefix=*) PREFIX="${arg#*=}" ;;
    -h|--help)
      cat <<'EOF'
Usage: debugmaster/install.sh [--link] [--prefix=DIR]

Requirements:
  required: python3, git
  optional: grepgod, rg, jq, semgrep, gitleaks, osv-scanner, cargo, pytest, just

--link      symlink debugmaster into PREFIX (default ~/.local/bin)
EOF
      exit 0
      ;;
  esac
done

"$HERE/bin/debugmaster" init

if (( LINK )); then
  mkdir -p "$PREFIX"
  ln -sf "$HERE/bin/debugmaster" "$PREFIX/debugmaster"
  echo "linked: $PREFIX/debugmaster -> $HERE/bin/debugmaster"
fi
