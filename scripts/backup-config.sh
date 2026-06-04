#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/printer-env.sh
. "$SCRIPT_DIR/lib/printer-env.sh"

timestamp="$(date +%Y%m%d-%H%M%S)"
backup_root="${1:-$PROJECT_ROOT/backups/$PRINTER_NAME/$timestamp}"
backup_config_dir="$backup_root/config"
remote_config_dir="$(shell_quote "$PRINTER_REMOTE_CONFIG_DIR")"

mkdir -p "$backup_config_dir"

printer_ssh "tar --exclude='._*' -C $remote_config_dir -czf - ." | tar -xzf - -C "$backup_config_dir"

cat > "$backup_root/metadata.env" <<EOF
PRINTER_NAME="$PRINTER_NAME"
PRINTER_HOST="$PRINTER_HOST"
PRINTER_USER="$PRINTER_USER"
REMOTE_CONFIG_DIR="$PRINTER_REMOTE_CONFIG_DIR"
BACKUP_CREATED_AT="$timestamp"
EOF

printf '%s\n' "$backup_config_dir"
