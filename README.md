# 3D Printing Ops

Practical 3D printer operations for AI agents and humans.

This marketplace currently contains one skill, **klipper-ops**. It combines a
concise operational workflow and a separate local MCP server, used together.
The skill recommends installing the companion MCP and explains the operational
scenarios. The MCP package owns execution and also provides a CLI for recovery.

## What You Can Do

- Inspect Klipper host services and Moonraker print state.
- Read bounded logs for an allowlisted service.
- Pull config snapshots, compare changes, and keep verified backups.
- Prepare a config change, review its patch, then apply it explicitly.
- Check Klipper readiness after restart and restore the previous tree on failure.
- Recover an interrupted transaction or restore a verified backup.

Slicer profiles, slicer settings, firmware flashing, and print motion commands
are outside this skill's scope.

## How It Fits Together

| Component | Responsibility |
| --- | --- |
| Skill | Use cases, diagnostic order, interpretation, and user approval of changes. |
| MCP package and its CLI | Configuration, SSH, snapshots, validation, locks, transactions, and recovery. |
| Workspace | Printer connection settings, config mirrors, backups, and operation records. |

Install the skill and its companion MCP separately. The skill detects missing MCP
tools and recommends their installation; it does not silently install or register
the server. Small scripts shipped with the skill launch the CLI from the MCP
package. Raw SSH is available only as an explicit CLI recovery command.

## Install

Requirements: macOS or Linux, local Python 3.11+, OpenSSH, and network access to
the printer. The printer host needs Linux/systemd, Python 3.8+, its Klipper
checkout, and Moonraker. Use SSH keys or an SSH agent; an explicit askpass helper
is also supported. System service restarts require passwordless, narrowly scoped
sudo access, unless the SSH user is root. User services use systemctl --user.

### Skill

Use a compatible skill installer with:

```text
repo: anton-kostryukov/3d-printing-ops
path: skills/klipper-ops
ref: 0.4.0
```

Or install manually:

```bash
git clone --branch 0.4.0 https://github.com/anton-kostryukov/3d-printing-ops.git
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R 3d-printing-ops/skills/klipper-ops "${CODEX_HOME:-$HOME/.codex}/skills/klipper-ops"
```

The destination above is an example for Codex. Other agents can install the
same skill folder in their own skills directory.

### MCP Server

Install the companion package from its dedicated directory:

```bash
pipx install "git+https://github.com/anton-kostryukov/3d-printing-ops.git@0.4.0#subdirectory=mcp/klipper-ops-server"
# Alternative:
uv tool install "git+https://github.com/anton-kostryukov/3d-printing-ops.git@0.4.0#subdirectory=mcp/klipper-ops-server"
```

This installs both klipper-ops and klipper-ops-mcp. Runtime code resides only in
mcp/klipper-ops-server; the installable skill remains at skills/klipper-ops.

## Initialize A Printer Workspace

```bash
export KLIPPER_OPS_SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/klipper-ops"
"$KLIPPER_OPS_SKILL_DIR/scripts/init-project.sh" \
  --host printer.local --user pi --name my-printer \
  --with-wrappers ./my-printer
cd my-printer
./scripts/status.sh
./scripts/logs.sh klipper 15 120
./scripts/pull-config.sh
```

Initialization preserves existing settings and wrappers. It creates a workspace
.gitignore for private env files, host keys, backups, config mirrors, and
transaction records. For SSH aliases without an explicit user, pass
--remote-home with the actual remote home directory.

## A Config Change From Start To Finish

Pull once before editing. Then edit the local mirror, prepare a plan, review its
patch and backup location, and apply that exact plan:

```bash
./scripts/prepare-config.sh
# Inspect the returned patch, validation scope, backup path, and plan_hash.
./scripts/push-config.sh --plan <plan_hash> --yes
```

Applying a plan restarts the configured Klipper service. The operation checks
that the printer is idle, that the remote config and staged tree still match the
reviewed fingerprints, and that the service and Klipper become ready. A failed
restart or readiness check restores the previous config and checks recovery.

Directory replacement uses two renames under a remote lock and a durable
transaction journal. This is a recoverable transaction, not a filesystem-wide
atomic exchange. The old tree remains available as a rollback directory after a
successful apply. A killed process or lost SSH connection can leave an uncertain
outcome: inspect status before retrying and use recovery if the journal reports
an interrupted transaction.

```bash
./scripts/status.sh
./scripts/recover-config.sh --yes
# Discard an unused or expired plan:
./scripts/discard-config.sh <plan_hash>
# Restore an identified backup:
./scripts/restore-backup.sh <backup_id> --yes
```

An active or paused print always blocks apply, restart, recovery, and restore.
Unknown print state also blocks writes. The explicit recovery flag
--allow-unknown-print-state permits a write when Moonraker is unavailable, but a
config apply still has to pass the post-restart Klipper readiness check.

### Validation Limits

The default validator uses ConfigFileReader from the printer's installed
klippy/configfile.py to check syntax and include resolution. It does not start
Klippy, open MCU serial devices, or prove pin and hardware compatibility.
Full runtime acceptance is checked through Moonraker after restart.
An optional custom checker is supported through PRINTER_KLIPPER_CHECK_SCRIPT;
its successful exit is only a preflight check.

Absolute and relative symlinks are preserved as inert snapshot entries. Existing
external links may be retained, but new or changed external links are rejected.
Absolute includes inside the live config root are redirected to the candidate
during validation. Expanded pulls are for inspection and should not be used as
upload sources.

## Configure

Both interfaces parse these files as data, without shell execution or variable
expansion, in the following order:

1. .env
2. .klipper-ops.env
3. .klipper-ops.local.env
4. exported environment variables, which take precedence

```dotenv
PRINTER_HOST=printer.local
PRINTER_USER=pi
PRINTER_NAME=my-printer
PRINTER_REMOTE_CONFIG_DIR=/home/pi/printer_data/config
PRINTER_KLIPPER_DIR=/home/pi/klipper
PRINTER_KLIPPER_SERVICE=klipper
PRINTER_SERVICES="klipper moonraker nginx crowsnest"
PRINTER_SYSTEMCTL_SCOPE=system
PRINTER_MOONRAKER_URL=http://127.0.0.1:7125
KNOWN_HOSTS_PATH=.known_hosts
KLIPPER_OPS_SSH_TIMEOUT=30
KLIPPER_OPS_HEALTH_TIMEOUT=30
KLIPPER_OPS_PLAN_TTL_SECONDS=3600
```

Moonraker URLs are resolved **on the printer host**. Relative local paths are
resolved from the workspace. Set PRINTER_REMOTE_HOME when the SSH login uses a
nonstandard home; root defaults to /root. Set PRINTER_KLIPPER_DIR when Klipper is
installed elsewhere, and include PRINTER_KLIPPER_SERVICE in PRINTER_SERVICES.

SSH_ASKPASS_PATH must point to an explicitly configured executable; it is never
autodiscovered. KLIPPER_OPS_PYTHON selects the local Python executable used by
shell launchers. KLIPPER_OPS_CLI selects the companion CLI when it is outside PATH.
Generated workspace wrappers discover the CLI and retain an installation fallback.
Restart an MCP server after changing its workspace settings;
a running server keeps its initial printer configuration.

Pulls write only to printer_data/config or printer_data/config-expanded. They
refuse to overwrite local edits unless --overwrite is explicitly supplied.
Backups and plans use content fingerprints and printer identity. Git metadata and
macOS sidecar files are excluded from snapshots and diffs; the remote .git entry
is preserved during apply. Snapshots are limited to 10,000 entries, 64 MiB
uncompressed, and 32 MiB compressed.

## AI Agent Integration

Run one local stdio MCP server per printer workspace and pass an absolute
KLIPPER_OPS_PROJECT_ROOT.

### Codex

```bash
codex mcp add klipper-ops \
  --env KLIPPER_OPS_PROJECT_ROOT=/absolute/path/to/my-printer \
  -- klipper-ops-mcp
```

### Claude Code

```bash
claude mcp add --scope local klipper-ops \
  --env KLIPPER_OPS_PROJECT_ROOT=/absolute/path/to/my-printer \
  -- klipper-ops-mcp
```

### Gemini CLI

```bash
gemini mcp add klipper-ops klipper-ops-mcp \
  --env KLIPPER_OPS_PROJECT_ROOT=/absolute/path/to/my-printer
```

### Cursor And Other MCP Clients

Use the client's stdio configuration, such as .cursor/mcp.json:

```json
{
  "mcpServers": {
    "klipper-ops": {
      "command": "klipper-ops-mcp",
      "args": [],
      "env": {
        "KLIPPER_OPS_PROJECT_ROOT": "/absolute/path/to/my-printer"
      }
    }
  }
}
```

Add the operational policy to AGENTS.md, CLAUDE.md, GEMINI.md, or a project rule:

> Use klipper-ops for printer host work. Start with compact status and bounded
> logs. Review local edits before pulling. Prepare config changes, show the patch,
> validation scope and backup, then obtain user approval before applying the plan.
> After an uncertain result, inspect the transaction before retrying.

## Tools And Commands

| MCP tool | Bundled command |
| --- | --- |
| get_printer_status | status.sh |
| get_service_logs | logs.sh SERVICE [MINUTES] [LINES] |
| get_config_manifest / diff_config | ops.py diff |
| pull_config | pull-config.sh / pull-config-expanded.sh |
| backup_config | backup-config.sh |
| validate_config | check-config.sh [LOCAL_CONFIG_DIR] |
| prepare_config_apply | prepare-config.sh [LOCAL_CONFIG_DIR] |
| apply_config | push-config.sh --plan HASH --yes |
| discard_config_apply | discard-config.sh HASH |
| restart_service | restart-service.sh --yes SERVICE |
| restore_backup | restore-backup.sh BACKUP_ID --yes |
| recover_config | recover-config.sh --yes |

The direct CLI is also available as python3 /path/to/skill/scripts/ops.py COMMAND.
ssh.sh accepts one explicitly quoted recovery command and is not exposed by MCP.

## Upgrade From 0.3.x

- Reinstall the separate MCP package and update the skill together.
- Prepare new plans; 0.3.x plans cannot be applied.
- push-config.sh now requires a reviewed plan and restarts Klipper.
- check-config.sh validates a local candidate directory, not an arbitrary remote file.
- Use PRINTER_KLIPPER_DIR for the standard parser; remove the old nonexistent
  checker path from workspace env files unless you supplied your own checker.
- Old backups remain readable, but automatic restore requires new verified JSON
  metadata. Review older backups manually before preparing them as candidates.
- Read any local mirror edits before the first 0.4.x pull; use --overwrite only
  after deciding to discard them.

## Development And Releases

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e './mcp/klipper-ops-server[dev]'
.venv/bin/pytest mcp/klipper-ops-server
bash tests/test-shell.sh
.venv/bin/ruff check mcp/klipper-ops-server skills/klipper-ops/scripts scripts
python3 scripts/validate-project.py
.venv/bin/python -m build mcp/klipper-ops-server
```

CI runs on Python 3.11 and 3.12, executes CLI and real MCP protocol tests, and
exercises the remote worker against a local Moonraker/systemd simulator. It also
downloads a commit-pinned upstream Klipper parser for include validation tests.
No live printer is needed. These tests do not replace acceptance testing on a
physical printer; hardware readiness and host-specific permissions still need
to be verified when connecting a printer.

Use GitHub Flow with short-lived branches and PRs into main. Functionality and
bugfixes get version bumps and releases; docs and process changes use Unreleased.
Release tags are created from main and equal VERSION exactly. Package, skill,
marketplace, README, changelog, tag, and GitHub Release versions must agree.

Current version: `0.4.0`.
