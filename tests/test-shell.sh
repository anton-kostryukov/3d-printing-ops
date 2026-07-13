#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_LIB="$ROOT/skills/klipper-ops/scripts/lib/printer-env.sh"
INIT="$ROOT/skills/klipper-ops/scripts/init-project.sh"
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT

unsafe_project="$TEMP_ROOT/unsafe"
mkdir -p "$unsafe_project"
marker="$unsafe_project/executed"
# Literal command substitution is the test payload.
# shellcheck disable=SC2016
printf 'PRINTER_HOST=$(touch %s)\n' "$marker" > "$unsafe_project/.klipper-ops.env"
if KLIPPER_OPS_PROJECT_ROOT="$unsafe_project" bash -c 'set -e; . "$1"' _ "$ENV_LIB" 2>/dev/null; then
  echo "unsafe PRINTER_HOST unexpectedly passed validation" >&2
  exit 1
fi
[[ ! -e "$marker" ]] || {
  echo "dotenv content was executed" >&2
  exit 1
}

env_project="$TEMP_ROOT/env"
mkdir -p "$env_project"
printf '%s\n' 'PRINTER_HOST=file-host' 'PRINTER_SERVICES="klipper moonraker"' > "$env_project/.env"
printf '%s\n' 'PRINTER_HOST=local-host' > "$env_project/.klipper-ops.local.env"
loaded="$({
  KLIPPER_OPS_PROJECT_ROOT="$env_project" PRINTER_HOST=env-host \
    bash -c '. "$1"; printf "%s|%s" "$PRINTER_HOST" "$PRINTER_SERVICES"' _ "$ENV_LIB"
})"
[[ "$loaded" == "env-host|klipper moonraker" ]] || {
  echo "unexpected env precedence: $loaded" >&2
  exit 1
}

if "$INIT" --host printer.local --name ../outside "$TEMP_ROOT/unsafe-name" >/dev/null 2>&1; then
  echo "unsafe printer name unexpectedly passed validation" >&2
  exit 1
fi

workspace="$TEMP_ROOT/workspace"
"$INIT" --host printer.local --user pi --name test-printer --with-wrappers "$workspace" >/dev/null
grep -q '^PRINTER_HOST="printer.local"$' "$workspace/.klipper-ops.env"
grep -q '^PRINTER_KLIPPER_CHECK_SCRIPT="/home/pi/klipper/scripts/check_config.py"$' "$workspace/.klipper-ops.env"
for wrapper in "$workspace"/scripts/*.sh; do
  bash -n "$wrapper"
  grep -q 'KLIPPER_OPS_SKILL_DIR' "$wrapper"
done

printf 'shell tests passed\n'
