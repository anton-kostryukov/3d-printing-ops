from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass

from .config import PrinterConfig


class PrinterCommandError(RuntimeError):
    """Raised when a bounded remote operation fails."""


@dataclass(frozen=True)
class CommandResult:
    stdout: bytes
    stderr: bytes
    returncode: int

    @property
    def text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")


class SSHTransport:
    def __init__(self, config: PrinterConfig):
        self.config = config

    def run_script(
        self,
        script: str,
        args: tuple[str, ...] = (),
        *,
        input_bytes: bytes | None = None,
        check: bool = True,
        timeout: int | None = None,
    ) -> CommandResult:
        self.config.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        remote_command = "bash -c " + shlex.quote(script) + " --"
        if args:
            remote_command += " " + " ".join(shlex.quote(argument) for argument in args)

        command = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={self.config.known_hosts_path}",
            "-o",
            f"ConnectTimeout={min(self.config.ssh_timeout, 30)}",
        ]
        env = os.environ.copy()
        if self.config.askpass_path:
            if not self.config.askpass_path.is_file() or not os.access(
                self.config.askpass_path, os.X_OK
            ):
                raise PrinterCommandError(
                    f"SSH_ASKPASS_PATH is not executable: {self.config.askpass_path}"
                )
            env.update(
                {
                    "SSH_ASKPASS": str(self.config.askpass_path),
                    "SSH_ASKPASS_REQUIRE": "force",
                    "DISPLAY": env.get("DISPLAY", "none"),
                }
            )
        else:
            command.extend(["-o", "BatchMode=yes"])
        command.extend([self.config.ssh_target, remote_command])

        try:
            completed = subprocess.run(
                command,
                input=input_bytes,
                capture_output=True,
                timeout=timeout or self.config.ssh_timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PrinterCommandError(
                f"printer operation timed out after {timeout or self.config.ssh_timeout}s"
            ) from exc

        result = CommandResult(completed.stdout, completed.stderr, completed.returncode)
        if check and completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            if not detail:
                detail = completed.stdout.decode("utf-8", errors="replace").strip()
            detail = detail[-2000:]
            raise PrinterCommandError(
                f"printer operation failed with exit {completed.returncode}: {detail}"
            )
        return result
