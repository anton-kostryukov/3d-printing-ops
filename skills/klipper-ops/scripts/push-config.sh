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
check_script="$(shell_quote "$PRINTER_KLIPPER_CHECK_SCRIPT")"

if [[ ! -d "$source_dir" ]]; then
  echo "Local config directory does not exist: $source_dir" >&2
  exit 1
fi

timestamp="$(date +%Y%m%d-%H%M%S)"
remote_parent="${PRINTER_REMOTE_CONFIG_DIR%/*}"
stage_path="$remote_parent/.klipper-ops-stage-shell-$timestamp-$$"
rollback_path="$remote_parent/.klipper-ops-rollback-shell-$timestamp-$$"
stage="$(shell_quote "$stage_path")"
rollback="$(shell_quote "$rollback_path")"
backup_path="$("$SCRIPT_DIR/backup-config.sh")"

cleanup_stage() {
  printer_ssh "rm -rf $stage" >/dev/null 2>&1 || true
}
trap cleanup_stage EXIT

printer_ssh "rm -rf $stage && mkdir -p $stage"
COPYFILE_DISABLE=1 tar --exclude='._*' --exclude='.git' -C "$source_dir" -czf - . \
  | printer_ssh "tar -C $stage -xzf -"
printer_ssh "test -f $stage/printer.cfg && test -f $check_script && python3 $check_script $stage/printer.cfg"
printer_ssh "test -d $remote_config_dir && test ! -L $remote_config_dir && test ! -e $rollback && mv $remote_config_dir $rollback && if ! mv $stage $remote_config_dir; then mv $rollback $remote_config_dir; exit 70; fi"
trap - EXIT

printf 'Uploaded %s to %s%s:%s\n' "$source_dir" "${PRINTER_USER:+$PRINTER_USER@}" "$PRINTER_HOST" "$PRINTER_REMOTE_CONFIG_DIR"
printf 'Local backup: %s\nRemote rollback: %s\n' "$backup_path" "$rollback_path"
