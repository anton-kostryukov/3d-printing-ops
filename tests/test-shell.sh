#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export KLIPPER_OPS_CLI="${KLIPPER_OPS_CLI:-$(command -v klipper-ops || true)}"
if [[ -z "$KLIPPER_OPS_CLI" ]]; then
  export KLIPPER_OPS_CLI="$ROOT/.venv/bin/klipper-ops"
fi
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT

for script in "$ROOT"/skills/klipper-ops/scripts/*.sh; do
  bash -n "$script"
  bash "$script" --help >/dev/null
done

workspace="$TEMP_ROOT/printer workspace"
bash "$ROOT/skills/klipper-ops/scripts/init-project.sh" --host printer.local --user pi --name test-printer --with-wrappers "$workspace" >/dev/null
for wrapper in "$workspace"/scripts/*.sh; do
  bash -n "$wrapper"
  KLIPPER_OPS_SKILL_DIR="$ROOT/skills/klipper-ops" bash "$wrapper" --help >/dev/null
done

before="$(cksum "$workspace/.klipper-ops.env")"
bash "$ROOT/skills/klipper-ops/scripts/init-project.sh" --host printer.local --user pi "$workspace" >/dev/null
[[ "$(cksum "$workspace/.klipper-ops.env")" == "$before" ]]
if bash "$ROOT/skills/klipper-ops/scripts/init-project.sh" --host printer.local --user pi --name ../outside "$TEMP_ROOT/unsafe" >/dev/null 2>&1; then
  echo "unsafe printer name passed validation" >&2
  exit 1
fi
[[ ! -e "$TEMP_ROOT/unsafe" ]]
printf 'shell tests passed\n'
