# Klipper Ops MCP Server

Local stdio MCP server for the `klipper-ops` skill. Install and run it from a
printer workspace; set `KLIPPER_OPS_PROJECT_ROOT` when the MCP client does not
launch servers with that workspace as its current directory.

```bash
python3 -m pip install .
KLIPPER_OPS_PROJECT_ROOT=/path/to/printer klipper-ops-mcp
```

The public tool surface is typed and bounded. It deliberately does not expose
arbitrary SSH commands or unrestricted remote paths.
