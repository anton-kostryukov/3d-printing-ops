#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/printer-env.sh
. "$SCRIPT_DIR/lib/printer-env.sh"

if [[ "${1:-}" != "--yes" ]]; then
  echo "Usage: $0 --yes [local_config_dir]" >&2
  echo "This uploads local config files to ${PRINTER_USER:+$PRINTER_USER@}$PRINTER_HOST:$PRINTER_REMOTE_CONFIG_DIR." >&2
  exit 2
fi

source_dir="${2:-$PROJECT_ROOT/printer_data/config}"
remote_config_dir="$(shell_quote "$PRINTER_REMOTE_CONFIG_DIR")"

if [[ ! -d "$source_dir" ]]; then
  echo "Local config directory does not exist: $source_dir" >&2
  exit 1
fi

printer_ssh "mkdir -p $remote_config_dir"
COPYFILE_DISABLE=1 tar --exclude='._*' -C "$source_dir" -czf - . | printer_ssh "tar -C $remote_config_dir -xzf -"

printf 'Uploaded %s to %s%s:%s\n' "$source_dir" "${PRINTER_USER:+$PRINTER_USER@}" "$PRINTER_HOST" "$PRINTER_REMOTE_CONFIG_DIR"
