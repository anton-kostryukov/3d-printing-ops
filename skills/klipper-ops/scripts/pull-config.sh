#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/printer-env.sh
. "$SCRIPT_DIR/lib/printer-env.sh"

target_dir="${1:-$PROJECT_ROOT/printer_data/config}"
remote_config_dir="$(shell_quote "$PRINTER_REMOTE_CONFIG_DIR")"
target_parent="$(dirname "$target_dir")"
target_name="$(basename "$target_dir")"

if [[ -e "$target_dir" && ! -d "$target_dir" ]]; then
  echo "Local target exists and is not a directory: $target_dir" >&2
  exit 1
fi

mkdir -p "$target_parent"
temp_dir="$(mktemp -d "$target_parent/.$target_name.pull.XXXXXX")"
old_dir=""
cleanup() {
  [[ ! -d "$temp_dir" ]] || rm -rf "$temp_dir"
  if [[ -n "$old_dir" && -d "$old_dir" && ! -e "$target_dir" ]]; then
    mv "$old_dir" "$target_dir"
  fi
}
trap cleanup EXIT

printer_ssh "tar --exclude='._*' -C $remote_config_dir -czf - ." | tar -xzf - -C "$temp_dir"
if [[ -e "$target_dir" ]]; then
  old_dir="$target_parent/.$target_name.old.$$"
  mv "$target_dir" "$old_dir"
fi
mv "$temp_dir" "$target_dir"
if [[ -n "$old_dir" ]]; then
  rm -rf "$old_dir"
  old_dir=""
fi
trap - EXIT

printf '%s\n' "$target_dir"
