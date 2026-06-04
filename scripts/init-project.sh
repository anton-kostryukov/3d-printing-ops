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

mkdir -p "$project_dir/printer_data/config" "$project_dir/printer_data/config-expanded" "$project_dir/backups"
project_dir="$(cd "$project_dir" && pwd)"

if [[ -z "$printer_name" ]]; then
  printer_name="$(basename "$project_dir")"
fi

if [[ -z "$remote_config_dir" && -n "$printer_user" ]]; then
  remote_config_dir="/home/$printer_user/printer_data/config"
fi

env_file="$project_dir/.klipper-ops.env"
if [[ -e "$env_file" ]]; then
  echo "Keeping existing $env_file" >&2
else
  {
    printf 'PRINTER_NAME=%q\n' "$printer_name"
    printf 'PRINTER_HOST=%q\n' "$printer_host"
    if [[ -n "$printer_user" ]]; then
      printf 'PRINTER_USER=%q\n' "$printer_user"
    fi
    if [[ -n "$remote_config_dir" ]]; then
      printf 'PRINTER_REMOTE_CONFIG_DIR=%q\n' "$remote_config_dir"
    fi
    printf 'PRINTER_SERVICES=%q\n' "$printer_services"
  } > "$env_file"
fi

local_env_example="$project_dir/.klipper-ops.local.env.example"
if [[ ! -e "$local_env_example" ]]; then
  cat > "$local_env_example" <<'EOF'
# Optional machine-local overrides. Copy to .klipper-ops.local.env when needed.
# SSH_ASKPASS_PATH=/absolute/path/to/askpass.sh
# KNOWN_HOSTS_PATH=.known_hosts
EOF
fi

if [[ "$with_wrappers" -eq 1 ]]; then
  mkdir -p "$project_dir/scripts"
  for script in status ssh backup-config pull-config pull-config-expanded push-config check-config; do
    wrapper="$project_dir/scripts/$script.sh"
    if [[ -e "$wrapper" ]]; then
      echo "Keeping existing $wrapper" >&2
      continue
    fi
    cat > "$wrapper" <<EOF
#!/usr/bin/env bash
set -euo pipefail
KLIPPER_OPS_PROJECT_ROOT="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)" exec "$SCRIPT_DIR/$script.sh" "\$@"
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
