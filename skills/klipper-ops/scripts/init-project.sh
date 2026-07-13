#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: init-project.sh --host HOST [options] [project_dir]

Options:
  --host HOST              Printer SSH host or IP address. Required.
  --user USER              SSH user. Optional if your SSH config supplies one.
  --name NAME              Printer/project name. Defaults to project directory name.
  --remote-config DIR      Remote Klipper config dir. Default: /home/<user>/printer_data/config.
  --services "LIST"        Space-separated systemd services to monitor.
  --check-script PATH      Remote Klipper check_config.py path.
  --systemctl-scope SCOPE  system (default) or user.
  --with-wrappers          Create local scripts/ wrappers that call this skill's scripts.
  -h, --help               Show this help.
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="."
printer_host=""
printer_user=""
printer_name=""
remote_config_dir=""
printer_services="klipper moonraker nginx crowsnest"
check_script=""
systemctl_scope="system"
with_wrappers=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      printer_host="${2:-}"
      shift 2
      ;;
    --user)
      printer_user="${2:-}"
      shift 2
      ;;
    --name)
      printer_name="${2:-}"
      shift 2
      ;;
    --remote-config)
      remote_config_dir="${2:-}"
      shift 2
      ;;
    --services)
      printer_services="${2:-}"
      shift 2
      ;;
    --check-script)
      check_script="${2:-}"
      shift 2
      ;;
    --systemctl-scope)
      systemctl_scope="${2:-}"
      shift 2
      ;;
    --with-wrappers)
      with_wrappers=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
    *)
      project_dir="$1"
      shift
      ;;
  esac
done

if [[ -z "$printer_host" ]]; then
  echo "--host is required." >&2
  usage
  exit 2
fi

if [[ ! "$printer_host" =~ ^[A-Za-z0-9_.:-]+$ ]]; then
  echo "--host contains unsupported characters." >&2
  exit 2
fi

if [[ ! "$printer_user" =~ ^[A-Za-z0-9_.-]*$ ]]; then
  echo "--user contains unsupported characters." >&2
  exit 2
fi

if [[ ! "$printer_services" =~ ^[A-Za-z0-9@_.[:space:]-]+$ ]]; then
  echo "--services contains unsupported characters." >&2
  exit 2
fi

if [[ "$systemctl_scope" != "system" && "$systemctl_scope" != "user" ]]; then
  echo "--systemctl-scope must be system or user." >&2
  exit 2
fi

mkdir -p "$project_dir/printer_data/config" "$project_dir/printer_data/config-expanded" "$project_dir/backups"
project_dir="$(cd "$project_dir" && pwd)"

if [[ -z "$printer_name" ]]; then
  printer_name="$(basename "$project_dir")"
fi

if [[ -z "$printer_name" || "$printer_name" == "." || "$printer_name" == ".." \
  || "$printer_name" == */* || "$printer_name" == *\\* \
  || "$printer_name" == *$'\n'* || "$printer_name" == *$'\r'* ]]; then
  echo "--name must be one safe path component." >&2
  exit 2
fi

if [[ -z "$remote_config_dir" && -n "$printer_user" ]]; then
  remote_config_dir="/home/$printer_user/printer_data/config"
fi

if [[ -z "$check_script" && -n "$printer_user" ]]; then
  check_script="/home/$printer_user/klipper/scripts/check_config.py"
fi

if [[ -n "$remote_config_dir" && "$remote_config_dir" != /* ]]; then
  echo "--remote-config must be an absolute remote path." >&2
  exit 2
fi

if [[ -n "$check_script" && "$check_script" != /* ]]; then
  echo "--check-script must be an absolute remote path." >&2
  exit 2
fi

write_env_assignment() {
  local key="$1"
  local value="$2"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s="%s"\n' "$key" "$value"
}

env_file="$project_dir/.klipper-ops.env"
if [[ -e "$env_file" ]]; then
  echo "Keeping existing $env_file" >&2
else
  {
    write_env_assignment PRINTER_NAME "$printer_name"
    write_env_assignment PRINTER_HOST "$printer_host"
    if [[ -n "$printer_user" ]]; then
      write_env_assignment PRINTER_USER "$printer_user"
    fi
    if [[ -n "$remote_config_dir" ]]; then
      write_env_assignment PRINTER_REMOTE_CONFIG_DIR "$remote_config_dir"
    fi
    if [[ -n "$check_script" ]]; then
      write_env_assignment PRINTER_KLIPPER_CHECK_SCRIPT "$check_script"
    fi
    write_env_assignment PRINTER_SERVICES "$printer_services"
    write_env_assignment PRINTER_SYSTEMCTL_SCOPE "$systemctl_scope"
  } > "$env_file"
fi

local_env_example="$project_dir/.klipper-ops.local.env.example"
if [[ ! -e "$local_env_example" ]]; then
  cat > "$local_env_example" <<'EOF'
# Optional machine-local overrides. Copy to .klipper-ops.local.env when needed.
# SSH_ASKPASS_PATH=/absolute/path/to/askpass.sh
# KNOWN_HOSTS_PATH=.known_hosts
# KLIPPER_OPS_SSH_TIMEOUT=30
# Export KLIPPER_OPS_SKILL_DIR when generated wrappers must use a nonstandard install path.
EOF
fi

if [[ "$with_wrappers" -eq 1 ]]; then
  mkdir -p "$project_dir/scripts"
  skill_root="$(cd "$SCRIPT_DIR/.." && pwd)"
  for script in status logs ssh backup-config pull-config pull-config-expanded push-config check-config restart-service; do
    wrapper="$project_dir/scripts/$script.sh"
    if [[ -e "$wrapper" ]]; then
      echo "Keeping existing $wrapper" >&2
      continue
    fi
    cat > "$wrapper" <<EOF
#!/usr/bin/env bash
set -euo pipefail
project_root="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
for skill_dir in "\${KLIPPER_OPS_SKILL_DIR:-}" "\${CODEX_HOME:-\$HOME/.codex}/skills/klipper-ops" "$skill_root"; do
  if [[ -n "\$skill_dir" && -x "\$skill_dir/scripts/$script.sh" ]]; then
    KLIPPER_OPS_PROJECT_ROOT="\$project_root" exec "\$skill_dir/scripts/$script.sh" "\$@"
  fi
done
echo "Cannot locate klipper-ops; export KLIPPER_OPS_SKILL_DIR." >&2
exit 1
EOF
    chmod +x "$wrapper"
  done
fi

cat <<EOF
Initialized $project_dir

Next checks:
  $SCRIPT_DIR/status.sh
  $SCRIPT_DIR/pull-config.sh
EOF
