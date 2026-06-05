---
name: klipper-ops
description: Token-efficient Klipper printer host operations. Use when checking or debugging printer-side systemd services, journal logs, Klipper, Moonraker, Mainsail/nginx, crowsnest, SSH status, printer_data/config pushes/pulls, backups, or other repeated printer maintenance commands; prefer compact service snapshots and bounded logs before verbose status dumps.
---

# klipper-ops

Version: `0.2.0`

Use this skill to keep printer host diagnostics short, repeatable, and safe. It is for operations against printer-side services, Klipper `printer_data/config` mirrors, and host state, not for broad codebase architecture questions.

Out of scope: local slicer profiles, slicer app configuration, and non-printer-host profile sync workflows.

## Use Cases

- Check whether Klipper, Moonraker, web UI services, camera services, or other configured printer services are active without dumping full service status.
- Read recent bounded logs for a named printer-side service while debugging startup, restart, config, or connectivity failures.
- Pull `printer_data/config` into a workspace before comparing, reviewing, or editing printer configuration.
- Back up remote `printer_data/config` before any printer-side push or risky service restart.
- Push a verified local `printer_data/config` mirror back to the printer with an explicit `--yes`.
- Run a focused Klipper config check before restarting after config edits.
- Execute one-off SSH diagnostics through a consistent env and known-hosts setup.
- Initialize a new printer workspace with env files, config directories, backups, and optional wrapper scripts.

## Bundled Scripts

This skill ships plug-and-play scripts in `scripts/`. From a printer workspace, run the bundled script path directly:

```bash
/path/to/klipper-ops/scripts/status.sh
/path/to/klipper-ops/scripts/ssh.sh 'systemctl is-active klipper moonraker nginx crowsnest 2>/dev/null || true'
```

Repo scripts with the same names may wrap or override these. Prefer the repo script when it exists and is clearly printer-specific; otherwise use the bundled script.

Printer settings come from the current printer workspace, not the skill. The scripts load, in order:

1. `.env`
2. `.klipper-ops.env`
3. `.klipper-ops.local.env`

Required: `PRINTER_HOST`. Common overrides: `PRINTER_NAME`, `PRINTER_USER`, `PRINTER_REMOTE_CONFIG_DIR`, `PRINTER_SERVICES`, `SSH_ASKPASS_PATH`, and `KNOWN_HOSTS_PATH`.

## Versioning

- Keep `VERSION` in sync with the version shown in this file.
- Update `CHANGELOG.md` for every behavior, script, environment contract, or documentation change.
- Use granular entries under Added, Changed, Fixed, Removed, and Security when applicable.
- Bump patch for fixes/docs, minor for new backward-compatible scripts or env options, and major for breaking command or environment behavior.

## Start Small

1. Check local repo state before changing files.
2. Prefer existing repo scripts over ad hoc SSH:
   - `scripts/status.sh` for a quick host/service/`printer_data/config` snapshot.
   - `scripts/ssh.sh '<remote command>'` for focused remote checks.
   - `scripts/backup-config.sh` before printer-side changes.
   - `scripts/pull-config.sh` or `scripts/pull-config-expanded.sh` before drift analysis.
   - `scripts/push-config.sh --yes` only after backup and local verification.
   - `scripts/init-project.sh --host <host>` when starting a new printer workspace.
   Use `./scripts/...` when the printer repo has wrappers; otherwise use the resolved bundled script path.
3. Treat printer network commands as host-network operations that may require approval outside sandbox.
4. Keep command output bounded. Never start with full `systemctl status` or unbounded `journalctl`.

## Typical Flow

1. Inspect repo state and relevant local files.
2. Run `scripts/status.sh` for orientation, or a narrower `scripts/ssh.sh` command if the user names a symptom.
3. For Klipper `printer_data/config` work, pull the remote mirror before comparing or editing; back up before pushing.
4. Verify with the smallest check that proves the operation worked: service active state, `journalctl -n`, config test, or focused file diff.
5. Report only changed state, backup path, and the next risky command if one remains.

## Compact Service Snapshot

For service health, use `systemctl show` fields instead of verbose status:

```bash
scripts/ssh.sh 'for s in klipper moonraker nginx crowsnest; do echo "== $s =="; systemctl show "$s" --no-pager -p Id -p LoadState -p ActiveState -p SubState -p MainPID -p ExecMainStatus -p NRestarts -p FragmentPath 2>/dev/null || true; done'
```

If only active/inactive matters:

```bash
scripts/ssh.sh 'systemctl is-active klipper moonraker nginx crowsnest 2>/dev/null || true'
```

For restarts, check state before and after, and read bounded logs only if the service does not settle:

```bash
scripts/ssh.sh 'sudo systemctl restart klipper && systemctl is-active klipper'
```

## Bounded Logs

Read recent logs only, with a reason and a service name:

```bash
scripts/ssh.sh 'journalctl -u klipper --since "15 min ago" -n 120 --no-pager'
scripts/ssh.sh 'journalctl -u moonraker --since "15 min ago" -n 120 --no-pager'
```

Increase to `-n 300` only when the first sample shows truncation around the failure. Do not paste or request full historical logs unless the user asks for a deep incident review.

## Config And Backup Rules

- Before pushing to the printer, run `scripts/backup-config.sh` and report the created backup path.
- Use `scripts/pull-config.sh` or `scripts/pull-config-expanded.sh` to refresh mirrors before analyzing remote drift.
- For local file inspection, use `rg`, `sed -n`, and focused paths. Avoid reading whole expanded configs unless a section range is known.
- Before restart after config edits, prefer a Klipper config check when available:

```bash
scripts/check-config.sh
```

- If the command is missing or fails due local printer layout, fall back to a focused restart plus bounded `journalctl -u klipper --since "5 min ago" -n 120 --no-pager`.

## Drift And File Questions

- Compare local mirrors with normal repo tools first: `git diff -- printer_data/config`, `rg`, and `sed -n`.
- Use expanded config only for include resolution, macro lookup, or confirming effective values.
- When a change touches reusable scripts or agent rules, keep the publication contract generic and document only portable behavior.

## Escalation Pattern

When sandbox blocks mDNS/SSH/printer networking, rerun the same scoped command with approval. Keep approvals narrow: prefer `scripts/status.sh`, `scripts/ssh.sh`, `scripts/backup-config.sh`, `scripts/pull-config.sh`, or `scripts/push-config.sh --yes` over broad shells.

## Response Shape

Report:

- service states that matter;
- the smallest relevant log excerpt summary, not full logs;
- backup path when created;
- exact next command only when it is needed.

Keep raw command output out of the final response unless the user explicitly asks for it.
