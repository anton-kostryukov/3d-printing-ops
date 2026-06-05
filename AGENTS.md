# Agent Instructions

These instructions apply to the `klipper-ops` skill project.

## Purpose

This project owns a publishable AI-agent skill for token-efficient Klipper printer host operations. It bundles reusable scripts for SSH, systemd snapshots, bounded logs, and `printer_data/config` backup/pull/push workflows.

## Editing Rules

1. Keep `skills/klipper-ops/SKILL.md` concise; this skill exists to reduce token use.
2. Keep bundled scripts portable and configurable through environment variables or workspace env files.
3. Prefer command patterns that bound output: `systemctl show`, `systemctl is-active`, and `journalctl -n` with `--since`.
4. Do not embed printer-specific hostnames, usernames, passwords, paths outside normal Klipper defaults, or local repository references.
5. Do not add slicer profile workflows to this skill.
6. Keep use cases transparent in `skills/klipper-ops/SKILL.md` when adding or removing operational coverage.
7. Maintain `VERSION`, `marketplace.json`, and granular `CHANGELOG.md` entries for every behavior, script, environment contract, marketplace, or documentation change.
8. Keep `README.md` human-readable and publication-oriented whenever setup, integration, or release behavior changes.
9. Use GitHub Flow with `main` as the primary branch.
10. Commit task changes before finishing.
11. Create version bumps, git tags, and GitHub Releases only for functional changes or bugfixes. Documentation, repository metadata, topics, and process-only changes do not get releases unless they accompany functional release work.
12. Keep the git tag for a release exactly equal to `VERSION`.
13. Run skill validation against `skills/klipper-ops` and shell syntax checks after edits.
