from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, load_config
from .operations import KlipperOperations
from .transport import PrinterCommandError

WRAPPERS = {
    "status": "status",
    "logs": "logs",
    "ssh": "ssh",
    "backup-config": "backup",
    "pull-config": "pull",
    "pull-config-expanded": "pull-expanded",
    "check-config": "validate",
    "prepare-config": "prepare",
    "push-config": "apply",
    "discard-config": "discard",
    "restart-service": "restart",
    "restore-backup": "restore",
    "recover-config": "recover",
}


def initialize(args: argparse.Namespace) -> dict:
    root = Path(args.project_dir).expanduser().resolve()
    values = {
        "PRINTER_HOST": args.host,
        "PRINTER_SERVICES": args.services,
        "PRINTER_SYSTEMCTL_SCOPE": args.systemctl_scope,
    }
    optional = {
        "PRINTER_USER": args.user,
        "PRINTER_NAME": args.name,
        "PRINTER_REMOTE_HOME": args.remote_home,
        "PRINTER_REMOTE_CONFIG_DIR": args.remote_config,
        "PRINTER_KLIPPER_CHECK_SCRIPT": args.check_script,
        "PRINTER_KLIPPER_DIR": args.klipper_dir,
        "PRINTER_KLIPPER_SERVICE": args.klipper_service,
        "PRINTER_MOONRAKER_URL": args.moonraker_url,
    }
    values.update({key: value for key, value in optional.items() if value is not None})
    config = load_config(root, values)
    values.setdefault("PRINTER_NAME", config.name)
    # Validate before creating anything, and preserve existing user-owned files.
    root.mkdir(parents=True, exist_ok=True)
    for directory in ("printer_data/config", "printer_data/config-expanded", "backups"):
        path = config.resolve_workspace_path(directory)
        path.mkdir(parents=True, exist_ok=True)
    env_path = root / ".klipper-ops.env"
    if not env_path.exists():
        env_path.write_text(
            "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items()),
            encoding="utf-8",
        )
        env_path.chmod(0o600)
    example = root / ".klipper-ops.local.env.example"
    if not example.exists():
        example.write_text(
            "# Optional machine-local overrides (dotenv data, no shell expansion).\n"
            '# KNOWN_HOSTS_PATH=".known_hosts"\n'
            '# SSH_ASKPASS_PATH="/absolute/path/to/askpass.sh"\n',
            encoding="utf-8",
        )
    ignore = root / ".gitignore"
    existing = ignore.read_text() if ignore.exists() else ""
    ignored = [
        ".env",
        ".klipper-ops.local.env",
        ".klipper-ops/",
        ".known_hosts",
        ".ssh_askpass*",
        "backups/",
        "printer_data/",
    ]
    missing = [entry for entry in ignored if entry not in existing.splitlines()]
    if missing:
        ignore.write_text(
            existing
            + ("\n" if existing and not existing.endswith("\n") else "")
            + "\n".join(missing)
            + "\n",
            encoding="utf-8",
        )
    if args.with_wrappers:
        scripts = root / "scripts"
        scripts.mkdir(exist_ok=True)
        installed_cli = Path(sys.executable).parent / "klipper-ops"
        for name, operation in WRAPPERS.items():
            wrapper = scripts / f"{name}.sh"
            if wrapper.exists():
                continue
            wrapper.write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\n"
                'project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n'
                'cli="${KLIPPER_OPS_CLI:-}"\n'
                'if [[ -z "$cli" ]]; then cli="$(command -v klipper-ops || true)"; fi\n'
                'if [[ -z "$cli" ]]; then cli=' + shlex.quote(str(installed_cli)) + "; fi\n"
                'export KLIPPER_OPS_PROJECT_ROOT="$project_root"\n'
                + f'exec "$cli" {operation} "$@"\n',
                encoding="utf-8",
            )
            wrapper.chmod(0o755)
    return {"workspace": str(root), "env": str(env_path), "wrappers": args.with_wrappers}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="klipper-ops")
    result.add_argument("--version", action="version", version=__version__)
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="initialize a printer workspace")
    init.add_argument("--host", required=True)
    for option in (
        "user",
        "name",
        "remote-home",
        "remote-config",
        "check-script",
        "klipper-dir",
        "klipper-service",
        "moonraker-url",
    ):
        init.add_argument("--" + option)
    init.add_argument("--services", default="klipper moonraker nginx crowsnest")
    init.add_argument("--systemctl-scope", choices=("system", "user"), default="system")
    init.add_argument("--with-wrappers", action="store_true")
    init.add_argument("project_dir", nargs="?", default=".")
    commands.add_parser("status")
    logs = commands.add_parser("logs")
    logs.add_argument("service")
    logs.add_argument("minutes", type=int, nargs="?", default=15)
    logs.add_argument("lines", type=int, nargs="?", default=120)
    commands.add_parser("backup")
    for name in ("pull", "pull-expanded"):
        command = commands.add_parser(name)
        command.add_argument("local_config_dir", nargs="?", default="printer_data/config")
        command.add_argument("--overwrite", action="store_true")
    for name in ("validate", "prepare", "diff"):
        command = commands.add_parser(name)
        command.add_argument("local_config_dir", nargs="?", default="printer_data/config")
    apply = commands.add_parser("apply")
    apply.add_argument("--plan", required=True)
    discard = commands.add_parser("discard")
    discard.add_argument("plan_hash")
    restart = commands.add_parser("restart")
    restart.add_argument("service")
    restore = commands.add_parser("restore")
    restore.add_argument("backup_id")
    recover = commands.add_parser("recover")
    for command in (apply, restart, restore, recover):
        command.add_argument("--yes", action="store_true", required=True)
        command.add_argument("--allow-unknown-print-state", action="store_true")
    raw = commands.add_parser("ssh", help="explicit raw SSH recovery escape hatch")
    raw.add_argument("remote_command")
    return result


def main() -> None:
    args = parser().parse_args()
    try:
        if args.command == "init":
            output = initialize(args)
        else:
            operations = KlipperOperations(load_config())
            command = args.command
            if command == "status":
                output = operations.get_printer_status()
            elif command == "logs":
                output = operations.get_service_logs(args.service, args.minutes, args.lines)
            elif command == "backup":
                output = operations.backup_config()
            elif command in {"pull", "pull-expanded"}:
                output = operations.pull_config(
                    args.local_config_dir, command == "pull-expanded", args.overwrite
                )
            elif command == "validate":
                output = operations.validate_config(args.local_config_dir)
            elif command == "prepare":
                output = operations.prepare_config_apply(args.local_config_dir)
            elif command == "diff":
                output = operations.diff_config(args.local_config_dir)
            elif command == "apply":
                output = operations.apply_config(
                    args.plan, args.yes, allow_unknown_print_state=args.allow_unknown_print_state
                )
            elif command == "discard":
                output = operations.discard_config_apply(args.plan_hash)
            elif command == "restart":
                output = operations.restart_service(
                    args.service, args.yes, args.allow_unknown_print_state
                )
            elif command == "restore":
                output = operations.restore_backup(
                    args.backup_id,
                    args.backup_id,
                    allow_unknown_print_state=args.allow_unknown_print_state,
                )
            elif command == "recover":
                output = operations.recover_config(args.yes, args.allow_unknown_print_state)
            else:
                print(operations.transport.raw_ssh(args.remote_command), end="")
                return
        print(json.dumps(output, indent=2))
    except (ConfigError, PrinterCommandError, ValueError, OSError) as exc:
        print(f"klipper-ops: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
