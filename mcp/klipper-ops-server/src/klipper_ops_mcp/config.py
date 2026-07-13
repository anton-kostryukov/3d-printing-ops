from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Raised when a printer workspace configuration is invalid."""


ENV_KEYS = {
    "PRINTER_NAME",
    "PRINTER_HOST",
    "PRINTER_USER",
    "PRINTER_REMOTE_HOME",
    "PRINTER_REMOTE_DATA_DIR",
    "PRINTER_REMOTE_CONFIG_DIR",
    "PRINTER_REMOTE_LOG_DIR",
    "PRINTER_SERVICES",
    "PRINTER_KLIPPER_CHECK_SCRIPT",
    "PRINTER_SYSTEMCTL_SCOPE",
    "KNOWN_HOSTS_PATH",
    "SSH_ASKPASS_PATH",
    "KLIPPER_OPS_SSH_TIMEOUT",
    "KLIPPER_OPS_PLAN_TTL_SECONDS",
}

ENV_FILES = (".env", ".klipper-ops.env", ".klipper-ops.local.env")
SERVICE_RE = re.compile(r"^[A-Za-z0-9@_.-]+$")
HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
USER_RE = re.compile(r"^[A-Za-z0-9_.-]*$")


def _parse_env_value(raw: str, path: Path, line_number: int) -> str:
    if not raw.strip():
        return ""
    lexer = shlex.shlex(raw, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        values = list(lexer)
    except ValueError as exc:
        raise ConfigError(f"{path}:{line_number}: {exc}") from exc
    if len(values) != 1:
        raise ConfigError(f"{path}:{line_number}: expected one dotenv value, got {len(values)}")
    return values[0]


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse supported dotenv assignments without evaluating shell code."""
    result: dict[str, str] = {}
    if not path.is_file():
        return result

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in ENV_KEYS:
            continue
        result[key] = _parse_env_value(raw_value, path, line_number)
    return result


def _positive_int(values: dict[str, str], key: str, default: int) -> int:
    raw = values.get(key, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer") from exc
    if value <= 0:
        raise ConfigError(f"{key} must be positive")
    return value


def _local_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


@dataclass(frozen=True)
class PrinterConfig:
    project_root: Path
    name: str
    host: str
    user: str
    remote_home: str
    remote_data_dir: str
    remote_config_dir: str
    remote_log_dir: str
    services: tuple[str, ...]
    check_script: str
    systemctl_scope: str
    known_hosts_path: Path
    askpass_path: Path | None
    ssh_timeout: int
    plan_ttl_seconds: int

    @property
    def ssh_target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    def resolve_workspace_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.project_root / path
        path = path.resolve()
        try:
            path.relative_to(self.project_root)
        except ValueError as exc:
            raise ConfigError("local paths must stay inside the printer workspace") from exc
        return path

    def require_service(self, service: str) -> str:
        if service not in self.services:
            raise ConfigError(
                f"service {service!r} is not in PRINTER_SERVICES: {' '.join(self.services)}"
            )
        return service


def load_config(project_root: str | Path | None = None) -> PrinterConfig:
    explicit_root = project_root or os.environ.get("KLIPPER_OPS_PROJECT_ROOT") or os.getcwd()
    root = Path(explicit_root).expanduser().resolve()
    values: dict[str, str] = {}
    for filename in ENV_FILES:
        values.update(parse_env_file(root / filename))
    for key in ENV_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]

    host = values.get("PRINTER_HOST", "").strip()
    if not host or not HOST_RE.fullmatch(host):
        raise ConfigError("PRINTER_HOST is required and contains unsupported characters")

    user = values.get("PRINTER_USER", "").strip()
    if not USER_RE.fullmatch(user):
        raise ConfigError("PRINTER_USER contains unsupported characters")
    name = values.get("PRINTER_NAME", root.name).strip() or root.name
    if (
        name in {".", ".."}
        or "/" in name
        or "\\" in name
        or any(ord(character) < 32 for character in name)
    ):
        raise ConfigError("PRINTER_NAME must be one safe path component")
    remote_home = values.get("PRINTER_REMOTE_HOME", f"/home/{user or 'printer'}")
    remote_data = values.get("PRINTER_REMOTE_DATA_DIR", f"{remote_home}/printer_data")
    remote_config = values.get("PRINTER_REMOTE_CONFIG_DIR", f"{remote_data}/config")
    remote_logs = values.get("PRINTER_REMOTE_LOG_DIR", f"{remote_data}/logs")
    check_script = values.get(
        "PRINTER_KLIPPER_CHECK_SCRIPT", f"{remote_home}/klipper/scripts/check_config.py"
    )
    for key, value in {
        "PRINTER_REMOTE_HOME": remote_home,
        "PRINTER_REMOTE_DATA_DIR": remote_data,
        "PRINTER_REMOTE_CONFIG_DIR": remote_config,
        "PRINTER_REMOTE_LOG_DIR": remote_logs,
        "PRINTER_KLIPPER_CHECK_SCRIPT": check_script,
    }.items():
        if not value.startswith("/") or "\n" in value or "\r" in value:
            raise ConfigError(f"{key} must be an absolute remote path")

    services = tuple(values.get("PRINTER_SERVICES", "klipper moonraker nginx crowsnest").split())
    if not services or any(not SERVICE_RE.fullmatch(service) for service in services):
        raise ConfigError("PRINTER_SERVICES contains an invalid systemd unit name")

    scope = values.get("PRINTER_SYSTEMCTL_SCOPE", "system")
    if scope not in {"system", "user"}:
        raise ConfigError("PRINTER_SYSTEMCTL_SCOPE must be 'system' or 'user'")

    known_hosts = _local_path(root, values.get("KNOWN_HOSTS_PATH", ".known_hosts"))
    askpass_value = values.get("SSH_ASKPASS_PATH", "")
    askpass = _local_path(root, askpass_value) if askpass_value else None

    return PrinterConfig(
        project_root=root,
        name=name,
        host=host,
        user=user,
        remote_home=remote_home,
        remote_data_dir=remote_data,
        remote_config_dir=remote_config,
        remote_log_dir=remote_logs,
        services=services,
        check_script=check_script,
        systemctl_scope=scope,
        known_hosts_path=known_hosts,
        askpass_path=askpass,
        ssh_timeout=_positive_int(values, "KLIPPER_OPS_SSH_TIMEOUT", 30),
        plan_ttl_seconds=_positive_int(values, "KLIPPER_OPS_PLAN_TTL_SECONDS", 3600),
    )
