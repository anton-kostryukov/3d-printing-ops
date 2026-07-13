# Changelog

All notable changes to `klipper-ops` are documented here.

## 0.3.0 - 2026-07-13

### Added

- Added the installable `klipper-ops-mcp` Python 3.11+ stdio server using the stable MCP Python SDK 1.x line.
- Added structured MCP tools for compact printer status, bounded service logs, remote config manifests, local/remote diffs, atomic pulls, backups, staged validation, two-phase config apply, allowlisted restarts, and backup restore.
- Added expiring config apply plans with local/remote fingerprints, backup IDs, staged validation, drift detection, atomic directory replacement, service health checks, and automatic rollback.
- Added `logs.sh` for bounded journal reads and `restart-service.sh` for confirmed, idle-gated service restarts when MCP is unavailable.
- Added `skills/klipper-ops/references/mcp-tools.md` with the public tool contract, write gates, and refusal handling.
- Added Python unit tests, shell contract tests, release metadata validation, and GitHub Actions CI.
- Added an MIT license for publication and reuse.

### Changed

- Split responsibilities so the skill owns use-case selection, diagnostic order, confirmation policy, interpretation, and response shape while MCP owns typed execution and safety enforcement.
- Made MCP the preferred operational surface while retaining bundled shell scripts as a plug-and-play fallback.
- Changed dotenv precedence to `.env`, `.klipper-ops.env`, `.klipper-ops.local.env`, then exported process environment.
- Made shell config pulls replace the local mirror atomically instead of overlaying existing files.
- Changed shell config pushes to create a local backup, upload an isolated staging tree, run the configured Klipper checker, atomically replace the remote directory, and retain a remote rollback directory.
- Made the Klipper checker path configurable with `PRINTER_KLIPPER_CHECK_SCRIPT` and systemd scope configurable with `PRINTER_SYSTEMCTL_SCOPE`.
- Added `KLIPPER_OPS_SSH_TIMEOUT` and `KLIPPER_OPS_PLAN_TTL_SECONDS` environment contracts.
- Changed generated wrappers to discover standard installations and support `KLIPPER_OPS_SKILL_DIR` overrides after relocation.
- Changed shell backup metadata from sourceable `metadata.env` to inert `metadata.txt`; MCP backups use `metadata.json`.
- Bounded the shell status config summary instead of listing every top-level config entry.
- Pinned the marketplace skill source to release tag `0.3.0` instead of mutable `main`.
- Reworked README installation and integration guidance for Codex, Claude Code, Gemini CLI, Cursor, and generic MCP clients.

### Fixed

- Stopped shell fallbacks from sourcing workspace env files as executable code.
- Prevented deleted remote config files from lingering after pull operations.
- Prevented shell pushes from silently overlaying a live remote config without mandatory backup, staging validation, or rollback material.
- Removed the release-policy conflict that told skill consumers to bump versions for documentation-only changes.
- Removed the stale README claim that the repository name includes `-skill`.

### Security

- Deliberately excluded arbitrary SSH execution and caller-selected remote paths from the MCP tool surface.
- Restricted service operations to `PRINTER_SERVICES`, logs to bounded windows, local paths to the printer workspace, host/user values to validated character sets, and printer names to safe backup path components.
- Refused config apply, restore, and restart while Moonraker reports an active or paused print.
- Required reviewed plan hashes or explicit identifiers for write operations and explicit disclosure before unknown-print-state recovery overrides.

## 0.2.0 - 2026-06-05

### Changed

- Documented GitHub Flow with `main` as the primary branch.
- Clarified that versions, git tags, and GitHub Releases are reserved for functional changes and bugfixes.
- Clarified that documentation, repository metadata, topics, and process-only changes are committed without release artifacts unless they accompany functional release work.
- Clarified AI-agent installation, including cloning the repository into a `klipper-ops` skill directory for Codex-compatible skill loaders.
- Reshaped and renamed the repository as the `3d-printing-ops` marketplace, currently containing the `klipper-ops` skill at canonical install path `skills/klipper-ops`.

## 0.1.4 - 2026-06-04

### Changed

- Expanded GitHub repository topics beyond Codex to cover generic AI agents and common agent tools: Claude Code, Gemini CLI, Cursor, OpenAI Agents, shell scripts, and Klipper ops.

## 0.1.3 - 2026-06-04

### Changed

- Made the README introduction tool-agnostic by describing the project as an AI-agent skill rather than a Codex-specific skill.
- Updated the published GitHub repository description to avoid Codex-specific positioning.

## 0.1.2 - 2026-06-04

### Changed

- Renamed the published GitHub repository to `klipper-ops-skill` so consumers can recognize it as a skill package.
- Updated README clone and initialization examples to use `anton-kostryukov/klipper-ops-skill`.

## 0.1.1 - 2026-06-04

### Added

- Human-readable `README.md` with quick start, configuration, AI-agent integration snippets, script reference, and release contract.
- `scripts/init-project.sh` for bootstrapping printer workspaces with env files, config directories, backups, and optional local wrappers.
- Explicit use case for initializing a new printer workspace.
- GitHub publication preparation guidance through README release and integration sections.
- `.gitignore` entries for local printer env, known hosts, backups, and config mirrors.

### Changed

- Bumped skill version to `0.1.1` for publication documentation and project initialization support.

## 0.1.0 - 2026-06-04

### Added

- Publishable `klipper-ops` skill metadata and concise operational workflow.
- Transparent use cases for Klipper service checks, bounded logs, config mirrors, backups, pushes, config checks, and focused SSH diagnostics.
- Bundled plug-and-play scripts:
  - `scripts/status.sh`
  - `scripts/ssh.sh`
  - `scripts/backup-config.sh`
  - `scripts/pull-config.sh`
  - `scripts/pull-config-expanded.sh`
  - `scripts/push-config.sh`
  - `scripts/check-config.sh`
  - `scripts/lib/printer-env.sh`
- Workspace env loading from `.env`, `.klipper-ops.env`, and `.klipper-ops.local.env`.
- Configurable `PRINTER_HOST`, `PRINTER_USER`, `PRINTER_REMOTE_CONFIG_DIR`, `PRINTER_SERVICES`, `SSH_ASKPASS_PATH`, and `KNOWN_HOSTS_PATH`.

### Changed

- Removed repository-layout assumptions from skill instructions.
- Generalized the skill beyond any specific printer vendor or host naming scheme.
- Clarified that slicer profile workflows are out of scope.

### Fixed

- Validated `PRINTER_SERVICES` before interpolating it into remote service snapshot commands.
