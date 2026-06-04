#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/printer-env.sh
. "$SCRIPT_DIR/lib/printer-env.sh"

target_dir="${1:-$PROJECT_ROOT/printer_data/config}"
remote_config_dir="$(shell_quote "$PRINTER_REMOTE_CONFIG_DIR")"

mkdir -p "$target_dir"

printer_ssh "tar --exclude='._*' -C $remote_config_dir -czf - ." | tar -xzf - -C "$target_dir"

printf '%s\n' "$target_dir"
