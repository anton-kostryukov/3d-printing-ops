# Klipper Ops MCP Server

Separate local stdio MCP server used with the `klipper-ops` skill. The skill
recommends installing this companion when its tools are absent. This package owns
all runtime code and installs both `klipper-ops-mcp` and `klipper-ops` (CLI).

```bash
python3 -m pip install .
klipper-ops init --host printer.local --user pi --with-wrappers ./my-printer
KLIPPER_OPS_PROJECT_ROOT=/path/to/printer klipper-ops-mcp
```

The public tool surface is typed and bounded. It deliberately does not expose
arbitrary SSH commands or unrestricted remote paths.

Requires local Python 3.11+, SSH, and a Linux Klipper host with Python 3.8+,
systemd, and Moonraker. The default validator uses the host's installed Klipper
config parser for syntax/includes. Config apply requires an idle printer, then
Klipper ready after restart; failures trigger rollback and recovery checks.

See the repository README for client setup, environment variables, upgrade notes,
the two-phase apply workflow, and interrupted-transaction recovery.
