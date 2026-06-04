# Klipper Ops Skill

Plug-and-play AI-agent skill and shell toolkit for calm, bounded Klipper printer host operations.

`klipper-ops` helps AI agents and humans work with printer hosts without drowning the thread in full `systemctl status` dumps, unbounded logs, or one-off SSH incantations. It focuses on the daily operations around Klipper, Moonraker, Mainsail/nginx, camera services, and `printer_data/config`.

## What It Does

- Checks printer-side systemd services with compact snapshots.
- Reads recent bounded logs with `journalctl --since` and `-n`.
- Pulls and backs up remote `printer_data/config`.
- Pushes a verified local config mirror with an explicit `--yes`.
- Runs a focused Klipper config check before restarts.
- Gives AI agents a small, repeatable command surface.

Out of scope: slicer profiles, slicer app settings, firmware flashing, and broad printer tuning methodology.

## Quick Start

Install the skill into your AI-agent skills directory. The repository is a one-skill marketplace; the installable skill lives at `skills/klipper-ops`.

For Codex and compatible skill installers:

```bash
# In Codex, ask skill-installer to install:
# repo: anton-kostryukov/klipper-ops-skill
# path: skills/klipper-ops
```

Manual install:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
tmpdir="$(mktemp -d)"
git clone git@github.com:anton-kostryukov/klipper-ops-skill.git "$tmpdir/klipper-ops-skill"
cp -R "$tmpdir/klipper-ops-skill/skills/klipper-ops" "${CODEX_HOME:-$HOME/.codex}/skills/klipper-ops"
```

Then initialize a printer workspace:

```bash
mkdir my-printer
cd my-printer
"${CODEX_HOME:-$HOME/.codex}/skills/klipper-ops/scripts/init-project.sh" --host printer.local --user pi --name my-printer --with-wrappers
```

Run the first compact check:

```bash
./scripts/status.sh
```

Pull the printer config mirror:

```bash
./scripts/pull-config.sh
```

Back up before pushing:

```bash
./scripts/backup-config.sh
./scripts/check-config.sh
./scripts/push-config.sh --yes
```

## Configuration

Printer settings live in the printer workspace, not in this skill. Scripts load these files in order:

1. `.env`
2. `.klipper-ops.env`
3. `.klipper-ops.local.env`

Minimum configuration:

```bash
PRINTER_HOST=printer.local
PRINTER_USER=pi
```

Common overrides:

```bash
PRINTER_NAME=my-printer
PRINTER_REMOTE_CONFIG_DIR=/home/pi/printer_data/config
PRINTER_SERVICES="klipper moonraker nginx crowsnest"
KNOWN_HOSTS_PATH=.known_hosts
SSH_ASKPASS_PATH=/absolute/path/to/askpass.sh
```

Use `.klipper-ops.local.env` for machine-local secrets or paths. Do not commit passwords or private keys.

## AI Agent Integration

Add a short instruction file to any printer workspace so agents use the bounded command surface.

## Marketplace Layout

This repository is intentionally shaped as a one-skill marketplace:

```text
marketplace.json
skills/
  klipper-ops/
    SKILL.md
    agents/openai.yaml
    scripts/
```

Use `marketplace.json` for discovery and `skills/klipper-ops` as the installable skill path. The repository name includes `-skill` for clarity; the skill name remains `klipper-ops`.

### Codex / OpenAI Agents

Install the skill path, not the repository root:

```bash
# Ask skill-installer to install:
# repo: anton-kostryukov/klipper-ops-skill
# path: skills/klipper-ops
```

Create or extend `AGENTS.md`:

```markdown
# Agent Instructions

For Klipper printer host operations, use `klipper-ops` before ad hoc SSH.

- Run `./scripts/status.sh` for orientation.
- Run `./scripts/pull-config.sh` before config drift analysis.
- Run `./scripts/backup-config.sh` before pushing or risky restarts.
- Prefer bounded logs: `journalctl -u <service> --since "15 min ago" -n 120 --no-pager`.
- Never start with full `systemctl status` or unbounded `journalctl`.
```

### Claude Code

Clone the repository anywhere stable, then create local wrappers in each printer workspace with `skills/klipper-ops/scripts/init-project.sh --with-wrappers`. Create or extend `CLAUDE.md` with the same operational contract:

```markdown
Use `./scripts/status.sh`, `./scripts/ssh.sh`, `./scripts/pull-config.sh`,
`./scripts/backup-config.sh`, and `./scripts/push-config.sh --yes` for Klipper
host work. Keep outputs bounded and summarize relevant service/log state.
```

### Gemini CLI

Clone the repository anywhere stable, then initialize each printer workspace with `skills/klipper-ops/scripts/init-project.sh --with-wrappers`. Create or extend `GEMINI.md`:

```markdown
When working on this printer repo, use the local `./scripts/*.sh` wrappers from
klipper-ops. Check git state before edits, pull config before analysis, back up
before pushing, and use bounded service/log commands.
```

### Cursor / Generic Agents

Clone the repository anywhere stable, then initialize each printer workspace with `skills/klipper-ops/scripts/init-project.sh --with-wrappers`. Create `.cursor/rules/klipper-ops.md` or an equivalent project rule:

```markdown
For printer host operations, prefer klipper-ops scripts over raw SSH. Keep
diagnostics compact: `systemctl show`, `systemctl is-active`, and
`journalctl --since ... -n ... --no-pager`.
```

## Script Reference

| Script | Purpose |
| --- | --- |
| `skills/klipper-ops/scripts/init-project.sh` | Create a printer workspace env, directories, and optional wrappers. |
| `skills/klipper-ops/scripts/status.sh` | Compact host, service, and config directory snapshot. |
| `skills/klipper-ops/scripts/ssh.sh` | Run a focused SSH command using workspace config. |
| `skills/klipper-ops/scripts/pull-config.sh` | Pull remote `printer_data/config` into `printer_data/config`. |
| `skills/klipper-ops/scripts/pull-config-expanded.sh` | Pull config while following symlinks into `printer_data/config-expanded`. |
| `skills/klipper-ops/scripts/backup-config.sh` | Create a timestamped config backup under `backups/<printer>/`. |
| `skills/klipper-ops/scripts/check-config.sh` | Run Klipper `check_config.py` against remote `printer.cfg`. |
| `skills/klipper-ops/scripts/push-config.sh` | Upload local config mirror to the printer; requires `--yes`. |

## Release Contract

- Use GitHub Flow: do work in short-lived branches, review through pull requests when practical, and land finished work on `main`.
- `main` is the primary branch.
- Push release tags from `main` only.
- Create versions, git tags, and GitHub Releases only for functional changes or bugfixes.
- Documentation, repository metadata, topics, and process-only changes are committed to `main` without a version bump, tag, or GitHub Release unless they accompany a functional release.
- When a release is made, `VERSION`, `skills/klipper-ops/SKILL.md`, `marketplace.json`, `README.md`, `CHANGELOG.md`, and the git tag must agree.
- Keep granular changelog entries. Use `Unreleased` for non-release documentation, metadata, and process changes.
- Bump patch for bugfixes, minor for backward-compatible functionality, and major for breaking command or environment behavior.

Current version: `0.1.4`.
