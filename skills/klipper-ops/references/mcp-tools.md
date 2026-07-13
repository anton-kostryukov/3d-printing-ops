# MCP Tool Contract

The MCP server is local stdio infrastructure. It reads exactly one printer
workspace selected by `KLIPPER_OPS_PROJECT_ROOT` or its process working directory.

## Read And Prepare Tools

| Tool | Contract |
| --- | --- |
| `get_printer_status` | Structured host, print, config, and service state. |
| `get_service_logs` | One allowlisted service; 1-1440 minutes and 1-500 lines. |
| `get_config_manifest` | Remote fingerprint plus a bounded file list. |
| `diff_config` | Added, modified, and deleted paths against a workspace mirror. |
| `pull_config` | Atomic local replacement so deleted remote files do not linger. |
| `backup_config` | Local backup with JSON metadata and a stable backup ID. |
| `validate_config` | Isolated remote staging and Klipper `check_config.py`. |
| `prepare_config_apply` | Backup, diff, stage, validate, fingerprint, and plan expiry. |

Preparation may run while printing because it does not replace live config or
restart a service. Still avoid unnecessary printer-host load during sensitive work.

## Write Tools

| Tool | Required gate |
| --- | --- |
| `apply_config` | Reviewed plan hash, `confirm=true`, unchanged fingerprints, idle printer. |
| `restart_service` | Allowlisted service, `confirm=true`, idle printer. |
| `restore_backup` | Exact backup ID repeated as confirmation, then normal apply gates. |

`apply_config` atomically swaps the directory, restarts the selected service,
checks that it is active, and restores the previous directory if health fails.
The remote rollback directory remains available for inspection.

Never treat a model-provided `confirm=true` as user consent unless the user has
seen the prepared diff and explicitly approved the write in the current task.

## Refusals

- Active print: wait; there is no active-print override.
- Unknown print state: explain why Moonraker is unavailable. Use
  `allow_unknown_print_state=true` only for an explicitly approved recovery.
- Expired plan or drift: prepare a new plan and show the new diff.
- Service outside `PRINTER_SERVICES`: update workspace config deliberately; do not
  bypass the allowlist.
- Validation failure: report the bounded checker output and leave live config alone.
