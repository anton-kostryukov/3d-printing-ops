#!/usr/bin/env bash

if [[ -n "${KLIPPER_OPS_ENV_LOADED:-}" ]]; then
  return 0
fi
KLIPPER_OPS_ENV_LOADED=1

KLIPPER_OPS_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "${KLIPPER_OPS_PROJECT_ROOT:-}" ]]; then
  PROJECT_ROOT="$KLIPPER_OPS_PROJECT_ROOT"
elif [[ "$(basename "$KLIPPER_OPS_SCRIPT_DIR")" == "scripts" ]] \
  && [[ -d "$(dirname "$KLIPPER_OPS_SCRIPT_DIR")/printer_data" || -f "$(dirname "$KLIPPER_OPS_SCRIPT_DIR")/.env" ]]; then
  PROJECT_ROOT="$(dirname "$KLIPPER_OPS_SCRIPT_DIR")"
else
  PROJECT_ROOT="$(pwd)"
fi

load_env_file() {
  local env_file="$1"
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "$env_file"
    set +a
  fi
}

load_env_file "$PROJECT_ROOT/.env"
load_env_file "$PROJECT_ROOT/.klipper-ops.env"
load_env_file "$PROJECT_ROOT/.klipper-ops.local.env"

: "${PRINTER_NAME:=$(basename "$PROJECT_ROOT")}"
: "${PRINTER_USER:=}"
: "${PRINTER_REMOTE_HOME:=/home/${PRINTER_USER:-printer}}"
: "${PRINTER_REMOTE_DATA_DIR:=$PRINTER_REMOTE_HOME/printer_data}"
: "${PRINTER_REMOTE_CONFIG_DIR:=$PRINTER_REMOTE_DATA_DIR/config}"
: "${PRINTER_REMOTE_LOG_DIR:=$PRINTER_REMOTE_DATA_DIR/logs}"
: "${PRINTER_SERVICES:=klipper moonraker nginx crowsnest}"
: "${KNOWN_HOSTS_PATH:=$PROJECT_ROOT/.known_hosts}"

if [[ -z "${PRINTER_HOST:-}" ]]; then
  echo "PRINTER_HOST is required. Set it in .env, .klipper-ops.env, or the environment." >&2
  return 2 2>/dev/null || exit 2
fi

if [[ ! "$PRINTER_SERVICES" =~ ^[A-Za-z0-9@_.[:space:]-]+$ ]]; then
  echo "PRINTER_SERVICES contains unsupported characters." >&2
  return 2 2>/dev/null || exit 2
fi

if [[ -z "${SSH_ASKPASS_PATH:-}" ]]; then
  if [[ -x "$PROJECT_ROOT/.ssh_askpass_printer.sh" ]]; then
    SSH_ASKPASS_PATH="$PROJECT_ROOT/.ssh_askpass_printer.sh"
  fi
fi

SSH_BASE_OPTS=(
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile="$KNOWN_HOSTS_PATH"
)

printer_ssh_prefix=()
if [[ -n "${SSH_ASKPASS_PATH:-}" && -x "$SSH_ASKPASS_PATH" ]]; then
  printer_ssh_prefix=(
    env
    "SSH_ASKPASS=$SSH_ASKPASS_PATH"
    "SSH_ASKPASS_REQUIRE=force"
    "DISPLAY=${DISPLAY:-none}"
  )
fi

shell_quote() {
  printf "%q" "$1"
}

printer_ssh() {
  local ssh_target="$PRINTER_HOST"
  if [[ -n "$PRINTER_USER" ]]; then
    ssh_target="$PRINTER_USER@$PRINTER_HOST"
  fi
  "${printer_ssh_prefix[@]}" ssh "${SSH_BASE_OPTS[@]}" "$ssh_target" "$@"
}

printer_scp() {
  "${printer_ssh_prefix[@]}" scp "${SSH_BASE_OPTS[@]}" "$@"
}
