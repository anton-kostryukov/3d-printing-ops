from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .config import PrinterConfig
from .files import MAX_ARCHIVE_BYTES


class PrinterCommandError(RuntimeError):
    """A bounded printer operation failed; writes must not be retried blindly."""


class SSHTransport:
    def __init__(self, config: PrinterConfig):
        self.config = config

    def request(self, action: str, **arguments: Any) -> dict[str, Any]:
        config = self.config
        return {
            "action": action,
            "config_dir": config.remote_config_dir,
            "klipper_dir": config.klipper_dir or f"{config.remote_home}/klipper",
            "check_script": config.check_script,
            "klipper_service": config.klipper_service,
            "moonraker_url": config.moonraker_url,
            "health_timeout": config.health_timeout,
            "scope": config.systemctl_scope,
            "services": list(config.services),
            "plan_ttl": config.plan_ttl_seconds,
            **arguments,
        }

    @staticmethod
    def worker_source() -> str:
        directory = Path(__file__).parent
        common = (directory / "files.py").read_text(encoding="utf-8")
        worker = (directory / "remote.py").read_text(encoding="utf-8")
        return (
            "import sys, types\n"
            "shared = types.ModuleType('klipper_ops_files')\n"
            "sys.modules['klipper_ops_files'] = shared\n"
            f"exec(compile({common!r}, 'klipper_ops_files', 'exec'), shared.__dict__)\n"
            f"exec(compile({worker!r}, 'klipper_ops_worker', 'exec'))\n"
        )

    def _execute(self, remote_command: str, payload: bytes | None, timeout: int) -> bytes:
        config = self.config
        config.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ssh",
            "-T",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={config.known_hosts_path}",
            "-o",
            f"ConnectTimeout={min(config.ssh_timeout, 30)}",
            "-o",
            "ServerAliveInterval=10",
            "-o",
            "ServerAliveCountMax=3",
        ]
        env = os.environ.copy()
        if config.askpass_path:
            if not config.askpass_path.is_file() or not os.access(config.askpass_path, os.X_OK):
                raise PrinterCommandError("SSH_ASKPASS_PATH is not executable")
            env.update(
                {
                    "SSH_ASKPASS": str(config.askpass_path),
                    "SSH_ASKPASS_REQUIRE": "force",
                    "DISPLAY": env.get("DISPLAY", "none"),
                }
            )
        else:
            command.extend(["-o", "BatchMode=yes"])
        command.extend(["--", config.ssh_target, remote_command])
        try:
            result = subprocess.run(
                command,
                input=payload,
                capture_output=True,
                env=env,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PrinterCommandError(
                f"printer operation timed out after {timeout}s; a write may have completed; "
                "inspect status and transaction state before retrying"
            ) from exc
        except OSError as exc:
            raise PrinterCommandError(f"unable to start SSH: {exc}") from exc
        if result.returncode:
            raise PrinterCommandError(
                result.stderr.decode(errors="replace")[-4000:] or f"SSH exited {result.returncode}"
            )
        if len(result.stdout) > MAX_ARCHIVE_BYTES:
            raise PrinterCommandError("printer response exceeds the 32 MiB limit")
        return result.stdout

    def run(self, action: str, *, payload: bytes | None = None, **arguments: Any) -> Any:
        request = self.request(action, **arguments)
        command = shlex.join(["python3", "-c", self.worker_source(), json.dumps(request)])
        timeout = max(self.config.ssh_timeout, 90)
        if action in {"apply", "recover", "restart"}:
            timeout = max(timeout, 2 * self.config.health_timeout + 240)
        output = self._execute(command, payload, timeout)
        if action == "archive":
            return output
        try:
            result = json.loads(output)
        except (ValueError, UnicodeDecodeError) as exc:
            raise PrinterCommandError("printer returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise PrinterCommandError("printer response must be a JSON object")
        return result

    def raw_ssh(self, command: str) -> str:
        return self._execute(command, None, self.config.ssh_timeout).decode(errors="replace")
