from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .operations import KlipperOperations

INSTRUCTIONS = """Use these tools for bounded Klipper printer host operations.
Read status, logs, manifests, and diffs before writes. For config changes, call
prepare_config_apply first, show its diff and backup to the user, and call
apply_config only after explicit confirmation. Never bypass an active-print or
unknown-print-state refusal without telling the user why state is unavailable.
"""


def _operations() -> KlipperOperations:
    return KlipperOperations(load_config())


def create_server() -> FastMCP:
    mcp = FastMCP("Klipper Ops", instructions=INSTRUCTIONS, json_response=True)

    @mcp.tool()
    def get_printer_status() -> dict[str, Any]:
        """Return compact host, print, config, and allowlisted service state."""
        return _operations().get_printer_status()

    @mcp.tool()
    def get_service_logs(service: str, minutes: int = 15, lines: int = 120) -> dict[str, Any]:
        """Return bounded recent logs for one service in PRINTER_SERVICES."""
        return _operations().get_service_logs(service, minutes, lines)

    @mcp.tool()
    def get_config_manifest(max_entries: int = 500) -> dict[str, Any]:
        """Return a bounded remote config manifest and full-tree fingerprint."""
        return _operations().get_config_manifest(max_entries)

    @mcp.tool()
    def diff_config(local_config_dir: str = "printer_data/config") -> dict[str, Any]:
        """Compare a workspace config mirror with the current remote config."""
        return _operations().diff_config(local_config_dir)

    @mcp.tool()
    def pull_config(
        local_config_dir: str = "printer_data/config", expanded: bool = False
    ) -> dict[str, Any]:
        """Atomically refresh a workspace config mirror, removing stale local files."""
        return _operations().pull_config(local_config_dir, expanded)

    @mcp.tool()
    def backup_config() -> dict[str, Any]:
        """Create a timestamped local backup of the current remote config."""
        return _operations().backup_config()

    @mcp.tool()
    def validate_config(local_config_dir: str = "printer_data/config") -> dict[str, Any]:
        """Upload to an isolated staging directory and run Klipper check_config.py."""
        return _operations().validate_config(local_config_dir)

    @mcp.tool()
    def prepare_config_apply(local_config_dir: str = "printer_data/config") -> dict[str, Any]:
        """Back up, diff, stage, and validate config; return a time-limited plan hash."""
        return _operations().prepare_config_apply(local_config_dir)

    @mcp.tool()
    def apply_config(
        plan_hash: str,
        confirm: bool,
        restart_service: str = "klipper",
        allow_unknown_print_state: bool = False,
    ) -> dict[str, Any]:
        """Atomically apply a reviewed plan, restart, health-check, and auto-rollback."""
        return _operations().apply_config(
            plan_hash, confirm, restart_service, allow_unknown_print_state
        )

    @mcp.tool()
    def restart_service(
        service: str,
        confirm: bool,
        allow_unknown_print_state: bool = False,
    ) -> dict[str, Any]:
        """Restart an allowlisted service after confirmation and an idle-state check."""
        return _operations().restart_service(service, confirm, allow_unknown_print_state)

    @mcp.tool()
    def restore_backup(
        backup_id: str,
        confirm_backup_id: str,
        restart_service: str = "klipper",
        allow_unknown_print_state: bool = False,
    ) -> dict[str, Any]:
        """Validate and restore a named workspace backup with atomic rollback guards."""
        return _operations().restore_backup(
            backup_id,
            confirm_backup_id,
            restart_service,
            allow_unknown_print_state,
        )

    return mcp


def main() -> None:
    create_server().run(transport="stdio")
