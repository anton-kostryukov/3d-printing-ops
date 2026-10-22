---
name: klipper-ops
description: Operate Klipper printer hosts with a companion MCP server. Use for service health, bounded logs, config review, backups, validated config changes, restarts, and recovery. Excludes slicer profiles and slicer application settings.
---

# Klipper Ops

Version: `0.4.0`

This skill supplies the operational workflow. The separately installed Klipper Ops
MCP server supplies printer tools, transport, validation, and recovery.

## Connect The Companion MCP

Check whether the Klipper Ops MCP tools are available. If absent, recommend
installing and connecting the companion server before printer operations:

```bash
pipx install "git+https://github.com/anton-kostryukov/3d-printing-ops.git@0.4.0#subdirectory=mcp/klipper-ops-server"
```

The alternative is `uv tool install` with the same URL. The server command is
`klipper-ops-mcp`; set `KLIPPER_OPS_PROJECT_ROOT` to the absolute printer workspace.
Follow the client's MCP configuration format. Installing this skill does not
install or register the server. Keep installation and printer writes within the
user's authorization; explain any missing dependency or connection.

The server also installs the `klipper-ops` CLI. Bundled shell scripts are small
launchers for that CLI, not another implementation. Set `KLIPPER_OPS_CLI` if the
executable is outside PATH. Initialize with `init-project.sh --host HOST --user
USER --with-wrappers WORKSPACE` after installing the companion package.

## Use Cases

- Inspect compact host, print, and allowlisted service state.
- Read one service's recent logs with explicit time and line bounds.
- Pull config mirrors, including expanded copies for inspection.
- Review remote drift and local config edits.
- Back up and validate a candidate without restarting the live printer.
- Prepare a reviewable plan, then apply the approved change with readiness checks.
- Restart an allowlisted service, restore a verified backup, or recover an
  interrupted config transaction.
- Discard unused or expired plans and their staging trees.
- Initialize a printer workspace and configurable CLI launchers.

## Workflow

1. Check workspace state and call `get_printer_status`, or start with a narrower
   tool if the user identified a symptom.
2. Read `get_service_logs` with 15 minutes and 120 lines before increasing bounds.
3. Before pulling, inspect local edits. `pull_config` refuses to overwrite changed
   mirrors; use `overwrite=true` only when those edits may be discarded.
4. For config edits, call `prepare_config_apply`. It backs up, stages, validates,
   and returns a patch, backup ID/path, expiry, and plan hash.
5. Show the relevant patch and validation scope. Apply that plan only when covered
   by explicit user approval; do not treat a model-generated `confirm=true` as consent.
6. Check returned Klipper readiness. After a timeout or uncertain result, inspect
   status and the transaction before retrying. Use `recover_config` for an
   interrupted transaction, and `discard_config_apply` for an abandoned plan.

Never apply, restart, recover, or restore during an active or paused print.
Unknown print state requires an explicitly authorized recovery override. A config
apply must still reach Klipper ready after restarting.

The default preflight checks syntax/includes using the installed Klipper parser;
it does not establish hardware or pin compatibility. Existing external symlinks
are preserved; expanded mirrors are for inspection, not upload candidates.

For tool parameters, refusal handling, and CLI mappings, read
[references/mcp-tools.md](references/mcp-tools.md) when needed.

## Response

Report the relevant service/print state, concise evidence, reviewed changes,
backup and rollback locations, validation scope, and remaining action. Summarize
bounded output instead of dumping it. Use raw `ssh.sh 'COMMAND'` only for an
explicitly scoped recovery that the typed tools cannot perform.
