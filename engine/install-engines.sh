#!/usr/bin/env bash
# debugmaster engine onboarding — install every optional best-in-class engine.
#
# install.sh only symlinks the binary and reports what is missing. This script
# closes the loop: it installs the polyglot scanner/debugger/profiler stack that
# the fusion + stack-check layers light up when present. It is idempotent
# (skips anything already on PATH), reversible (only adds tools), and honest
# (prints exactly what it ran and what it skipped).
#
# Usage:
#   ./install-engines.sh                 # install all groups (asks once)
#   ./install-engines.sh --yes           # no prompt
#   ./install-engines.sh --dry-run       # print plan, install nothing
#   ./install-engines.sh --only js,go    # only named groups
#   ./install-engines.sh --list          # list groups + tools, then exit
#
# Groups: fusion js go rust python-debug native llm ml
set -uo pipefail

DRY=0; YES=0; ONLY=""; LIST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --yes|-y) YES=1 ;;
    --only=*) ONLY="${1#*=}" ;;
    --only) shift; ONLY="${1:-}" ;;
    --list) LIST=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

# ── platform + package-manager detection ──────────────────────────────────────
OS="$(uname -s)"
have() { command -v "$1" >/dev/null 2>&1; }
BREW=0; have brew && BREW=1
UV=0;   have uv && UV=1
BUN=0;  have bun && BUN=1
NPM=0;  have npm && NPM=1
CARGO=0; have cargo && CARGO=1
GO=0;   have go && GO=1
RUSTUP=0; have rustup && RUSTUP=1

c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_red=$'\033[31m'; c_dim=$'\033[2m'; c_rst=$'\033[0m'
[ -t 1 ] || { c_grn=""; c_yel=""; c_red=""; c_dim=""; c_rst=""; }

INSTALLED=(); SKIPPED=(); FAILED=(); NOPLAN=()

# is a python module importable by the python3 debugmaster runs on?
pymod() { python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$1') else 1)" 2>/dev/null; }

# pick the first install command whose package manager exists; echo it
plan() {
  # args: list of "MGR:command" candidates in priority order
  local cand mgr cmd
  for cand in "$@"; do
    mgr="${cand%%:*}"; cmd="${cand#*:}"
    case "$mgr" in
      brew)   [ "$BREW" = 1 ] && { echo "$cmd"; return 0; } ;;
      uv)     [ "$UV" = 1 ]   && { echo "$cmd"; return 0; } ;;
      bun)    [ "$BUN" = 1 ]  && { echo "$cmd"; return 0; } ;;
      npm)    [ "$NPM" = 1 ]  && { echo "$cmd"; return 0; } ;;
      cargo)  [ "$CARGO" = 1 ] && { echo "$cmd"; return 0; } ;;
      go)     [ "$GO" = 1 ]   && { echo "$cmd"; return 0; } ;;
      rustup) [ "$RUSTUP" = 1 ] && { echo "$cmd"; return 0; } ;;
    esac
  done
  return 1
}

# install one tool: name | group | check(binary-or-mod:NAME) | candidates...
ensure() {
  local name="$1" group="$2" check="$3"; shift 3
  # group filter
  if [ -n "$ONLY" ] && [[ ",$ONLY," != *",$group,"* ]]; then return 0; fi
  # ml libs aren't wired to any layer yet — opt-in only, never in a default run
  if [ "$group" = "ml" ] && [[ ",$ONLY," != *",ml,"* ]]; then return 0; fi
  # already present?
  if [[ "$check" == mod:* ]]; then
    pymod "${check#mod:}" && { SKIPPED+=("$name"); return 0; }
  else
    have "${check#bin:}" && { SKIPPED+=("$name"); return 0; }
  fi
  local cmd
  if ! cmd="$(plan "$@")"; then
    NOPLAN+=("$name"); return 0
  fi
  if [ "$LIST" = 1 ]; then printf "  %-16s %s%s%s\n" "$name" "$c_dim" "$cmd" "$c_rst"; return 0; fi
  printf "→ %-16s %s%s%s\n" "$name" "$c_dim" "$cmd" "$c_rst"
  if [ "$DRY" = 1 ]; then return 0; fi
  if eval "$cmd" >"/tmp/dm-install-$name.log" 2>&1; then
    INSTALLED+=("$name")
  else
    FAILED+=("$name")
    printf "  %s✗ failed%s (see /tmp/dm-install-%s.log)\n" "$c_red" "$c_rst" "$name"
  fi
}

# ── the engine matrix ─────────────────────────────────────────────────────────
run_matrix() {
  # ── fusion scanners (Python + polyglot security/dead-code) ──
  ensure ruff        fusion bin:ruff        "uv:uv tool install ruff"        "brew:brew install ruff"
  ensure bandit      fusion bin:bandit      "uv:uv tool install bandit"
  ensure mypy        fusion bin:mypy        "uv:uv tool install mypy"
  ensure vulture     fusion bin:vulture     "uv:uv tool install vulture"
  ensure semgrep     fusion bin:semgrep     "brew:brew install semgrep"      "uv:uv tool install semgrep"
  ensure gitleaks    fusion bin:gitleaks    "brew:brew install gitleaks"
  ensure trivy       fusion bin:trivy       "brew:brew install trivy"
  ensure osv-scanner fusion bin:osv-scanner "brew:brew install osv-scanner"
  ensure shellcheck  fusion bin:shellcheck  "brew:brew install shellcheck"
  ensure shfmt       fusion bin:shfmt       "brew:brew install shfmt"        "go:go install mvdan.cc/sh/v3/cmd/shfmt@latest"
  ensure actionlint  fusion bin:actionlint  "brew:brew install actionlint"
  ensure ast-grep    fusion bin:ast-grep    "brew:brew install ast-grep"     "cargo:cargo install ast-grep --locked"

  # ── JS / TS (the June-2026 best-practice linters) ──
  ensure biome       js     bin:biome       "brew:brew install biome"        "bun:bun add -g @biomejs/biome"  "npm:npm i -g @biomejs/biome"
  ensure oxlint      js     bin:oxlint      "bun:bun add -g oxlint"          "npm:npm i -g oxlint"            "cargo:cargo install oxlint --locked"

  # ── Go ──
  ensure golangci-lint go   bin:golangci-lint "brew:brew install golangci-lint" "go:go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@latest"
  ensure staticcheck   go   bin:staticcheck   "go:go install honnef.co/go/tools/cmd/staticcheck@latest" "brew:brew install staticcheck"

  # ── Rust deep-debug ──
  ensure tokio-console rust bin:tokio-console "cargo:cargo install --locked tokio-console"
  ensure cargo-nextest rust bin:cargo-nextest "cargo:cargo binstall -y cargo-nextest" "cargo:cargo install cargo-nextest --locked"
  ensure flamegraph    rust bin:flamegraph    "cargo:cargo install flamegraph --locked"

  # ── Python runtime debug / profile ──
  ensure py-spy   python-debug bin:py-spy   "uv:uv tool install py-spy"   "brew:brew install py-spy"
  ensure scalene  python-debug bin:scalene  "uv:uv tool install scalene"
  ensure austin   python-debug bin:austin   "brew:brew install austin"

  # ── native crash / runtime ──
  ensure delve  native bin:dlv  "brew:brew install delve"
  ensure gdb    native bin:gdb  "brew:brew install gdb"

  # ── LLM-app debug ──
  ensure promptfoo llm bin:promptfoo "bun:bun add -g promptfoo" "npm:npm i -g promptfoo"

  # ── ML boost libs (reported by doctor; best-effort into user site) ──
  ensure river  ml mod:river  "uv:uv pip install --python $(command -v python3) --break-system-packages river"
  ensure shap   ml mod:shap   "uv:uv pip install --python $(command -v python3) --break-system-packages shap"
  ensure mlflow ml mod:mlflow "uv:uv pip install --python $(command -v python3) --break-system-packages mlflow"
}

# rustup miri needs nightly — handled separately so it never blocks the batch
ensure_miri() {
  [ -n "$ONLY" ] && [[ ",$ONLY," != *",rust,"* ]] && return 0
  [ "$RUSTUP" = 1 ] || { NOPLAN+=("miri"); return 0; }
  if rustup +nightly component list --installed 2>/dev/null | grep -q '^miri'; then
    SKIPPED+=("miri"); return 0
  fi
  local cmd="rustup toolchain install nightly --component miri"
  if [ "$LIST" = 1 ]; then printf "  %-16s %s%s%s\n" "miri" "$c_dim" "$cmd" "$c_rst"; return 0; fi
  printf "→ %-16s %s%s%s\n" "miri" "$c_dim" "$cmd" "$c_rst"
  [ "$DRY" = 1 ] && return 0
  if eval "$cmd" >/tmp/dm-install-miri.log 2>&1; then INSTALLED+=("miri"); else FAILED+=("miri"); fi
}

# ── run ───────────────────────────────────────────────────────────────────────
echo "${c_grn}debugmaster engine onboarding${c_rst}  (os=$OS brew=$BREW uv=$UV bun=$BUN cargo=$CARGO go=$GO)"
[ -n "$ONLY" ] && echo "${c_dim}groups: $ONLY${c_rst}"

if [ "$LIST" = 1 ]; then
  echo "Planned installs (already-present tools omitted at run time):"
  run_matrix; ensure_miri; exit 0
fi

if [ "$DRY" = 0 ] && [ "$YES" = 0 ]; then
  printf "Install missing engines now? [y/N] "; read -r ans
  case "$ans" in y|Y|yes) ;; *) echo "aborted."; exit 0 ;; esac
fi

run_matrix
ensure_miri

# ── summary ─────────────────────────────────────────────────────────────────
echo
echo "${c_grn}── summary ──${c_rst}"
echo "installed (${#INSTALLED[@]}): ${INSTALLED[*]:-none}"
echo "${c_dim}already-present (${#SKIPPED[@]}): ${SKIPPED[*]:-none}${c_rst}"
[ "${#NOPLAN[@]}" -gt 0 ] && echo "${c_yel}no installer on this machine (${#NOPLAN[@]}): ${NOPLAN[*]}${c_rst}"
[ "${#FAILED[@]}" -gt 0 ] && echo "${c_red}failed (${#FAILED[@]}): ${FAILED[*]}${c_rst}"
echo
echo "Verify depth:  debugmaster doctor"
[ "${#FAILED[@]}" -gt 0 ] && exit 1 || exit 0
