#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/printer-env.sh
. "$SCRIPT_DIR/lib/printer-env.sh"

remote_printer_cfg="${1:-$PRINTER_REMOTE_CONFIG_DIR/printer.cfg}"
remote_printer_cfg="$(shell_quote "$remote_printer_cfg")"
check_script="$(shell_quote "$PRINTER_KLIPPER_CHECK_SCRIPT")"

printer_ssh "python3 $check_script $remote_printer_cfg"
