# Agent Instructions

These instructions apply to the `klipper-ops` skill project.

## Purpose

This project owns a publishable Codex skill for token-efficient Klipper printer host operations. It bundles reusable scripts for SSH, systemd snapshots, bounded logs, and `printer_data/config` backup/pull/push workflows.

## Editing Rules

1. Keep `SKILL.md` concise; this skill exists to reduce token use.
2. Keep bundled scripts portable and configurable through environment variables or workspace env files.
3. Prefer command patterns that bound output: `systemctl show`, `systemctl is-active`, and `journalctl -n` with `--since`.
4. Do not embed printer-specific hostnames, usernames, passwords, paths outside normal Klipper defaults, or local repository references.
5. Do not add slicer profile workflows to this skill.
6. Keep use cases transparent in `SKILL.md` when adding or removing operational coverage.
7. Maintain `VERSION` and granular `CHANGELOG.md` entries for every behavior, script, environment contract, or documentation change.
8. Run skill validation and shell syntax checks after edits.
