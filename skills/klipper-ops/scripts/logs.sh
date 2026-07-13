#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/printer-env.sh
. "$SCRIPT_DIR/lib/printer-env.sh"

service="${1:-}"
minutes="${2:-15}"
lines="${3:-120}"

if [[ ! "$service" =~ ^[A-Za-z0-9@_.-]+$ ]] || ! service_is_allowed "$service"; then
  echo "Usage: $0 <service-from-PRINTER_SERVICES> [minutes:1-1440] [lines:1-500]" >&2
  exit 2
fi
if [[ ! "$minutes" =~ ^[0-9]+$ ]] || ((minutes < 1 || minutes > 1440)); then
  echo "minutes must be between 1 and 1440" >&2
  exit 2
fi
if [[ ! "$lines" =~ ^[0-9]+$ ]] || ((lines < 1 || lines > 500)); then
  echo "lines must be between 1 and 500" >&2
  exit 2
fi

if [[ "$PRINTER_SYSTEMCTL_SCOPE" == "user" ]]; then
  printer_ssh "journalctl --user -u $service --since '$minutes minutes ago' -n $lines --no-pager -o short-iso"
else
  printer_ssh "journalctl -u $service --since '$minutes minutes ago' -n $lines --no-pager -o short-iso"
fi
