# Changelog

All notable changes to `klipper-ops` are documented here.

## Unreleased

### Changed

- Documented GitHub Flow with `main` as the primary branch.
- Clarified that versions, git tags, and GitHub Releases are reserved for functional changes and bugfixes.
- Clarified that documentation, repository metadata, topics, and process-only changes are committed without release artifacts unless they accompany functional release work.
- Clarified AI-agent installation, including cloning the repository into a `klipper-ops` skill directory for Codex-compatible skill loaders.

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
