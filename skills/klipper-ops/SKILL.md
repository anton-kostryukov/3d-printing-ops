---
name: klipper-ops
description: Safe, token-efficient Klipper printer host operations through typed MCP tools with bundled shell fallbacks. Use for compact service health, bounded journal logs, Moonraker print state, printer_data/config manifests, diffs, pulls, backups, validation, staged config applies, rollback, allowlisted restarts, workspace initialization, or focused SSH recovery; do not use for slicer profiles or slicer app configuration.
---

# klipper-ops

Version: `0.3.0`

Operate Klipper hosts through a small, auditable surface. Prefer the `klipper-ops`
MCP server when connected; use bundled `scripts/` as a portable fallback.

## Use Cases

- Inspect host, Moonraker print, config, and allowlisted service state.
- Read recent logs for one service with explicit time and line bounds.
- Pull config mirrors atomically, including an expanded symlink-following mirror.
- Compare local and remote config manifests without dumping full files.
- Back up and validate config before any live change.
- Prepare, review, and explicitly apply an atomic config plan with rollback.
- Restart an allowlisted service only after confirmation and an idle-state check.
- Restore a named backup with explicit backup-ID confirmation.
- Initialize a printer workspace and shell wrappers.
- Run focused raw SSH only when typed tools and bounded scripts cannot recover a host.

Out of scope: slicer profiles, slicer app settings, firmware flashing, and general
printer tuning methodology.

## Choose The Surface

1. Use MCP tools first. They return structured data, enforce bounds and allowlists,
   and never expose arbitrary SSH execution or caller-selected remote paths.
2. Use workspace `./scripts/*.sh` wrappers or bundled scripts when MCP is absent.
3. Use `ssh.sh` only for a narrow recovery command. Do not turn it into an MCP tool.

Read [references/mcp-tools.md](references/mcp-tools.md) when selecting tools or
handling a write refusal.

## Workflow

1. Check repo state, then call `get_printer_status` or `status.sh`.
2. For a named failure, use `get_service_logs` or `logs.sh`; start with 15 minutes
   and 120 lines.
3. Before config analysis, call `pull_config` or the matching pull script.
4. Before writes, create a backup and validate the candidate.
5. For MCP writes, call `prepare_config_apply`, show the user its diff, backup ID,
   validation result, and plan hash, then wait for explicit confirmation.
6. Call `apply_config` only with that reviewed plan. It must recheck drift and print
   state, atomically swap config, restart, health-check, and roll back on failure.
7. Report changed state, backup ID/path, rollback path, and any remaining risk.

Never restart or apply config while Moonraker reports `printing` or `paused`.
Unknown print state requires a disclosed, explicit override and should be reserved
for recovery when Moonraker is unavailable.

## Shell Fallback

Scripts load `.env`, `.klipper-ops.env`, and `.klipper-ops.local.env` as dotenv
data, then apply exported environment overrides. They do not execute those files.

| Script | Purpose |
| --- | --- |
| `status.sh` | Compact host and service snapshot. |
| `logs.sh` | Bounded logs for an allowlisted service. |
| `pull-config.sh` | Atomic config mirror refresh. |
| `pull-config-expanded.sh` | Atomic expanded mirror refresh. |
| `backup-config.sh` | Timestamped local config backup. |
| `check-config.sh` | Remote Klipper config check. |
| `push-config.sh --yes` | Backup, stage, validate, and atomically replace config. |
| `restart-service.sh --yes SERVICE` | Idle-gated allowlisted restart. |
| `init-project.sh --host HOST` | Initialize a printer workspace. |
| `ssh.sh COMMAND` | Focused recovery-only SSH fallback. |

Printer-specific hostnames, credentials, and nonstandard paths belong in the
workspace environment files, never in this skill.

## Response Shape

Summarize service/print state, relevant bounded log evidence, config diff counts,
backup and rollback identifiers, and the next risky action. Keep raw dumps out of
the response unless the user asks for them.
