#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/printer-env.sh
. "$SCRIPT_DIR/lib/printer-env.sh"

timestamp="$(date +%Y%m%d-%H%M%S)"
backup_root="${1:-$PROJECT_ROOT/backups/$PRINTER_NAME/$timestamp}"
backup_config_dir="$backup_root/config"
remote_config_dir="$(shell_quote "$PRINTER_REMOTE_CONFIG_DIR")"

if [[ -z "${1:-}" && -L "$PROJECT_ROOT/backups/$PRINTER_NAME" ]]; then
  echo "Refusing to write through a symlinked printer backup directory." >&2
  exit 1
fi

mkdir -p "$backup_config_dir"

printer_ssh "tar --exclude='._*' -C $remote_config_dir -czf - ." | tar -xzf - -C "$backup_config_dir"

cat > "$backup_root/metadata.txt" <<EOF
printer_name: $PRINTER_NAME
printer_host: $PRINTER_HOST
printer_user: $PRINTER_USER
remote_config_dir: $PRINTER_REMOTE_CONFIG_DIR
backup_created_at: $timestamp
EOF

printf '%s\n' "$backup_config_dir"
