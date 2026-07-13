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

KLIPPER_OPS_ENV_KEYS=(
  PRINTER_NAME PRINTER_HOST PRINTER_USER PRINTER_REMOTE_HOME
  PRINTER_REMOTE_DATA_DIR PRINTER_REMOTE_CONFIG_DIR PRINTER_REMOTE_LOG_DIR
  PRINTER_SERVICES PRINTER_KLIPPER_CHECK_SCRIPT PRINTER_SYSTEMCTL_SCOPE
  KNOWN_HOSTS_PATH SSH_ASKPASS_PATH KLIPPER_OPS_SSH_TIMEOUT
  KLIPPER_OPS_PLAN_TTL_SECONDS
)

is_supported_env_key() {
  case "$1" in
    PRINTER_NAME|PRINTER_HOST|PRINTER_USER|PRINTER_REMOTE_HOME|\
    PRINTER_REMOTE_DATA_DIR|PRINTER_REMOTE_CONFIG_DIR|PRINTER_REMOTE_LOG_DIR|\
    PRINTER_SERVICES|PRINTER_KLIPPER_CHECK_SCRIPT|PRINTER_SYSTEMCTL_SCOPE|\
    KNOWN_HOSTS_PATH|SSH_ASKPASS_PATH|KLIPPER_OPS_SSH_TIMEOUT|\
    KLIPPER_OPS_PLAN_TTL_SECONDS) return 0 ;;
    *) return 1 ;;
  esac
}

decode_env_value() {
  local raw="$1"
  local mode="plain"
  local output=""
  local escaped=0
  local char
  local index

  raw="${raw#"${raw%%[![:space:]]*}"}"
  raw="${raw%"${raw##*[![:space:]]}"}"
  if [[ ${#raw} -ge 2 && "${raw:0:1}" == '"' && "${raw: -1}" == '"' ]]; then
    mode="double"
    raw="${raw:1:${#raw}-2}"
  elif [[ ${#raw} -ge 2 && "${raw:0:1}" == "'" && "${raw: -1}" == "'" ]]; then
    printf '%s' "${raw:1:${#raw}-2}"
    return 0
  fi

  for ((index = 0; index < ${#raw}; index++)); do
    char="${raw:index:1}"
    if [[ "$escaped" -eq 1 ]]; then
      output+="$char"
      escaped=0
    elif [[ "$char" == "\\" ]]; then
      escaped=1
    elif [[ "$mode" == "plain" && "$char" == "#" && ( "$index" -eq 0 || "${raw:index-1:1}" == " " ) ]]; then
      break
    else
      output+="$char"
    fi
  done
  if [[ "$escaped" -eq 1 ]]; then
    output+="\\"
  fi
  output="${output%"${output##*[![:space:]]}"}"
  printf '%s' "$output"
}

load_env_file() {
  local env_file="$1"
  local line
  local key
  local raw_value
  local value
  local line_number=0

  [[ -f "$env_file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line_number=$((line_number + 1))
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    if [[ "$line" == export[[:space:]]* ]]; then
      line="${line#export}"
      line="${line#"${line%%[![:space:]]*}"}"
    fi
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    key="${key%"${key##*[![:space:]]}"}"
    is_supported_env_key "$key" || continue
    raw_value="${line#*=}"
    value="$(decode_env_value "$raw_value")" || {
      echo "$env_file:$line_number: invalid value for $key" >&2
      return 2
    }
    printf -v "$key" '%s' "$value"
  done < "$env_file"
}

# Files provide increasingly local defaults; exported process variables win.
for key in "${KLIPPER_OPS_ENV_KEYS[@]}"; do
  if [[ -n "${!key+x}" ]]; then
    marker="KLIPPER_OPS_ORIGINAL_SET_$key"
    original="KLIPPER_OPS_ORIGINAL_$key"
    printf -v "$marker" '%s' 1
    printf -v "$original" '%s' "${!key}"
  fi
done

load_env_file "$PROJECT_ROOT/.env"
load_env_file "$PROJECT_ROOT/.klipper-ops.env"
load_env_file "$PROJECT_ROOT/.klipper-ops.local.env"

for key in "${KLIPPER_OPS_ENV_KEYS[@]}"; do
  marker="KLIPPER_OPS_ORIGINAL_SET_$key"
  original="KLIPPER_OPS_ORIGINAL_$key"
  if [[ -n "${!marker+x}" ]]; then
    printf -v "$key" '%s' "${!original}"
    unset "$marker" "$original"
  fi
done

: "${PRINTER_NAME:=$(basename "$PROJECT_ROOT")}"
: "${PRINTER_USER:=}"
: "${PRINTER_REMOTE_HOME:=/home/${PRINTER_USER:-printer}}"
: "${PRINTER_REMOTE_DATA_DIR:=$PRINTER_REMOTE_HOME/printer_data}"
: "${PRINTER_REMOTE_CONFIG_DIR:=$PRINTER_REMOTE_DATA_DIR/config}"
: "${PRINTER_REMOTE_LOG_DIR:=$PRINTER_REMOTE_DATA_DIR/logs}"
: "${PRINTER_SERVICES:=klipper moonraker nginx crowsnest}"
: "${PRINTER_KLIPPER_CHECK_SCRIPT:=$PRINTER_REMOTE_HOME/klipper/scripts/check_config.py}"
: "${PRINTER_SYSTEMCTL_SCOPE:=system}"
: "${KLIPPER_OPS_SSH_TIMEOUT:=30}"
: "${KNOWN_HOSTS_PATH:=$PROJECT_ROOT/.known_hosts}"

if [[ -z "${PRINTER_HOST:-}" ]]; then
  echo "PRINTER_HOST is required. Set it in .env, .klipper-ops.env, or the environment." >&2
  return 2 2>/dev/null || exit 2
fi

if [[ ! "$PRINTER_HOST" =~ ^[A-Za-z0-9_.:-]+$ ]]; then
  echo "PRINTER_HOST contains unsupported characters." >&2
  return 2 2>/dev/null || exit 2
fi

if [[ ! "$PRINTER_USER" =~ ^[A-Za-z0-9_.-]*$ ]]; then
  echo "PRINTER_USER contains unsupported characters." >&2
  return 2 2>/dev/null || exit 2
fi

if [[ -z "$PRINTER_NAME" || "$PRINTER_NAME" == "." || "$PRINTER_NAME" == ".." \
  || "$PRINTER_NAME" == */* || "$PRINTER_NAME" == *\\* \
  || "$PRINTER_NAME" == *$'\n'* || "$PRINTER_NAME" == *$'\r'* ]]; then
  echo "PRINTER_NAME must be one safe path component." >&2
  return 2 2>/dev/null || exit 2
fi

for remote_path_key in PRINTER_REMOTE_HOME PRINTER_REMOTE_DATA_DIR PRINTER_REMOTE_CONFIG_DIR PRINTER_REMOTE_LOG_DIR PRINTER_KLIPPER_CHECK_SCRIPT; do
  if [[ "${!remote_path_key}" != /* ]]; then
    echo "$remote_path_key must be an absolute remote path." >&2
    return 2 2>/dev/null || exit 2
  fi
done

if [[ ! "$PRINTER_SERVICES" =~ ^[A-Za-z0-9@_.[:space:]-]+$ ]]; then
  echo "PRINTER_SERVICES contains unsupported characters." >&2
  return 2 2>/dev/null || exit 2
fi

if [[ "$PRINTER_SYSTEMCTL_SCOPE" != "system" && "$PRINTER_SYSTEMCTL_SCOPE" != "user" ]]; then
  echo "PRINTER_SYSTEMCTL_SCOPE must be system or user." >&2
  return 2 2>/dev/null || exit 2
fi

if [[ ! "$KLIPPER_OPS_SSH_TIMEOUT" =~ ^[1-9][0-9]*$ ]]; then
  echo "KLIPPER_OPS_SSH_TIMEOUT must be a positive integer." >&2
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
  -o ConnectTimeout="$KLIPPER_OPS_SSH_TIMEOUT"
)

printer_ssh_prefix=()
if [[ -n "${SSH_ASKPASS_PATH:-}" && -x "$SSH_ASKPASS_PATH" ]]; then
  printer_ssh_prefix=(
    env
    "SSH_ASKPASS=$SSH_ASKPASS_PATH"
    "SSH_ASKPASS_REQUIRE=force"
    "DISPLAY=${DISPLAY:-none}"
  )
else
  SSH_BASE_OPTS+=( -o BatchMode=yes )
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

service_is_allowed() {
  local requested="$1"
  case " $PRINTER_SERVICES " in
    *" $requested "*) return 0 ;;
    *) return 1 ;;
  esac
}
