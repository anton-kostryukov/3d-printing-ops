#!/usr/bin/env python3
"""Compatibility launcher for the CLI installed with the separate MCP package."""

import os
import shutil
import sys
from pathlib import Path

if __name__ == "__main__":
    command = os.environ.get("KLIPPER_OPS_CLI") or shutil.which("klipper-ops")
    if not command:
        print(
            "Install the Klipper Ops MCP package first; see SKILL.md or README.md. "
            "Set KLIPPER_OPS_CLI if klipper-ops is outside PATH.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    os.execv(str(Path(command).expanduser().resolve()), [command, *sys.argv[1:]])
