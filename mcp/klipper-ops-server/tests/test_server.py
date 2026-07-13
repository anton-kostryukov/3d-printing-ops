from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from klipper_ops_mcp.server import create_server


def test_public_tool_surface_has_no_arbitrary_ssh() -> None:
    tools = asyncio.run(create_server().list_tools())
    names = {tool.name for tool in tools}

    assert names == {
        "apply_config",
        "backup_config",
        "diff_config",
        "get_config_manifest",
        "get_printer_status",
        "get_service_logs",
        "prepare_config_apply",
        "pull_config",
        "restart_service",
        "restore_backup",
        "validate_config",
    }
    assert "ssh" not in names


def test_stdio_server_handshake_and_tool_discovery() -> None:
    async def discover() -> set[str]:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "klipper_ops_mcp"],
        )
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await session.list_tools()
            return {tool.name for tool in result.tools}

    names = asyncio.run(discover())

    assert "get_printer_status" in names
    assert "prepare_config_apply" in names
    assert "apply_config" in names
    assert "ssh" not in names
