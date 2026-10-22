#!/bin/sh
# Pattern Vault installer (macOS and Linux).
#
#   curl -fsSL https://github.com/arunksingh16/pattern-vault/releases/latest/download/install.sh | sh
#
# The release workflow fills in the version and wheel URL below. Set PV_WHEEL_URL to a
# local wheel to test an unreleased build. --yes accepts every setup default; setup also
# does that by itself when there is no terminal to ask on (CI, Docker).
set -eu

PV_VERSION="${PV_VERSION:-@VERSION@}"
PV_WHEEL_URL="${PV_WHEEL_URL:-@WHEEL_URL@}"
RELEASES_URL="https://github.com/arunksingh16/pattern-vault/releases/latest"

say() { printf '%s\n' "$*"; }
fail() { printf '%s\n' "$*" >&2; exit 1; }

ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --yes | -y) ASSUME_YES=1 ;;
    *) fail "Unknown option: $arg (the only option is --yes)" ;;
  esac
done

case "$PV_WHEEL_URL" in
  @*) fail "This copy of install.sh isn't from a release. Use: curl -fsSL $RELEASES_URL/download/install.sh | sh" ;;
esac

say "Pattern Vault installer (v$PV_VERSION)"

case "$(uname -s)" in
  Darwin) os_name="macOS" ;;
  Linux) os_name="Linux" ;;
  *) fail "Windows and other systems are not supported yet." ;;
esac
say "  ✓ $os_name $(uname -m)"

if command -v uv >/dev/null 2>&1; then
  UV="$(command -v uv)"
elif [ -x "$HOME/.local/bin/uv" ]; then
  UV="$HOME/.local/bin/uv"
else
  say "  Installing uv (https://docs.astral.sh/uv)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
  UV="$HOME/.local/bin/uv"
  [ -x "$UV" ] || fail "uv was installed somewhere unexpected; add it to PATH and run this installer again."
fi
say "  ✓ uv found ($UV)"

"$UV" tool install --quiet --force --python 3.12 "$PV_WHEEL_URL"
PV_BIN="$("$UV" tool dir --bin)/pattern-vault"
[ -x "$PV_BIN" ] || fail "Install finished but $PV_BIN is missing."
say "  ✓ installed pattern-vault $PV_VERSION   (also provides the \`pv\` alias)"
say ""

# Only ask questions when there is a terminal to answer them on.
if [ "$ASSUME_YES" -eq 1 ] || ! (: </dev/tty) 2>/dev/null; then
  "$PV_BIN" setup --yes
else
  "$PV_BIN" setup </dev/tty
fi

if ! command -v pattern-vault >/dev/null 2>&1; then
  say ""
  say "Add $(dirname "$PV_BIN") to your PATH (run: $UV tool update-shell), then open a new terminal."
fi
