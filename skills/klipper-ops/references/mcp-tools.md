# MCP Tool Contract

Install the separate companion MCP package before operating the printer. The
skill recommends installation when its tools are absent. The MCP server is local
stdio infrastructure, bound to one workspace selected by
`KLIPPER_OPS_PROJECT_ROOT` or its initial working directory. Reconnect after env changes.

## Read And Prepare Tools

| Tool | Contract |
| --- | --- |
| `get_printer_status` | Structured host, print, config, and service state. |
| `get_service_logs` | One allowlisted service; 1-1440 minutes and 1-500 lines. |
| `get_config_manifest` | Remote fingerprint plus a bounded file list. |
| `diff_config` | Added, modified, and deleted paths against a workspace mirror. |
| `pull_config` | Refresh one of the two config mirrors; refuses local edits unless `overwrite=true`. |
| `backup_config` | Local backup with JSON metadata and a stable backup ID. |
| `validate_config` | Isolated staging; installed Klipper parser checks syntax and includes without MCU access. |
| `prepare_config_apply` | Backup, diff, stage, validate, fingerprint, and plan expiry. |
| `discard_config_apply` | Remove an unused/expired staging tree and mark the plan discarded. |

Preparation may run while printing because it does not replace live config or
restart a service. Still avoid unnecessary printer-host load during sensitive work.

## Write Tools

| Tool | Required gate |
| --- | --- |
| `apply_config` | Reviewed plan hash, `confirm=true`, unchanged fingerprints, idle printer. |
| `restart_service` | Allowlisted service, `confirm=true`, idle printer. |
| `restore_backup` | Exact backup ID repeated as confirmation, then normal apply gates. |
| `recover_config` | `confirm=true`, idle-state gate, verified interrupted-transaction journal. |

`apply_config` replaces config under a remote lock, restarts the configured
Klipper service, and requires both systemd active and Moonraker Klipper ready.
It restores the old directory if checks fail. A durable journal supports recovery
after interruption; two renames are not a globally atomic filesystem exchange.
The remote `.git` entry is preserved. Local backups exclude Git metadata.
Inspect transaction state after a timeout, then recover an interrupted change
before retrying. A failed or uncertain plan cannot be applied twice.

Never treat a model-provided `confirm=true` as user consent unless the user has
seen the prepared diff and explicitly approved the write in the current task.

## Refusals

- Active print: wait; there is no active-print override.
- Unknown print state: explain why Moonraker is unavailable. Use
  `allow_unknown_print_state=true` only for an explicitly approved recovery.
- Expired plan or drift: prepare a new plan and show the new diff.
- Local edits before pull: inspect them; use `overwrite=true` only to discard them explicitly.
- Service outside `PRINTER_SERVICES`: update workspace config deliberately; do not
  bypass the allowlist.
- Validation failure: report the bounded checker output and leave live config alone.
