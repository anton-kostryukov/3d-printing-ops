#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/printer-env.sh
. "$SCRIPT_DIR/lib/printer-env.sh"

remote_config_dir="$(shell_quote "$PRINTER_REMOTE_CONFIG_DIR")"
services="$PRINTER_SERVICES"

printer_ssh "hostname; uptime; echo; systemctl is-active $services 2>/dev/null || true; echo; for s in $services; do echo \"== \$s ==\"; systemctl show \"\$s\" --no-pager -p Id -p LoadState -p ActiveState -p SubState -p MainPID -p ExecMainStatus -p NRestarts -p FragmentPath 2>/dev/null || true; done; echo; ls -lah $remote_config_dir"
