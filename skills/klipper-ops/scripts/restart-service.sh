#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/printer-env.sh
. "$SCRIPT_DIR/lib/printer-env.sh"

if [[ "${1:-}" != "--yes" ]]; then
  echo "Usage: $0 --yes <service-from-PRINTER_SERVICES> [--allow-unknown-print-state]" >&2
  exit 2
fi
service="${2:-}"
allow_unknown="${3:-}"

if [[ ! "$service" =~ ^[A-Za-z0-9@_.-]+$ ]] || ! service_is_allowed "$service"; then
  echo "Service must be listed in PRINTER_SERVICES." >&2
  exit 2
fi
if [[ -n "$allow_unknown" && "$allow_unknown" != "--allow-unknown-print-state" ]]; then
  echo "Unknown option: $allow_unknown" >&2
  exit 2
fi

print_state="$(printer_ssh "python3 -c 'import json,urllib.request; u=\"http://127.0.0.1:7125/printer/objects/query?print_stats\"; d=json.load(urllib.request.urlopen(u,timeout=3)); print(d.get(\"result\",{}).get(\"status\",{}).get(\"print_stats\",{}).get(\"state\",\"unknown\"))'" 2>/dev/null || printf unknown)"
case "$print_state" in
  printing|paused)
    echo "Refusing to restart $service while printer state is $print_state." >&2
    exit 1
    ;;
  unknown)
    if [[ "$allow_unknown" != "--allow-unknown-print-state" ]]; then
      echo "Printer state is unknown; retry or pass --allow-unknown-print-state explicitly." >&2
      exit 1
    fi
    ;;
esac

if [[ "$PRINTER_SYSTEMCTL_SCOPE" == "user" ]]; then
  printer_ssh "systemctl --user restart $service && systemctl --user is-active $service"
else
  printer_ssh "sudo -n systemctl restart $service && sudo -n systemctl is-active $service"
fi
