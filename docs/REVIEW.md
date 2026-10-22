# Operational Readiness Review

Reviewed 2026-10-22 against release 0.3.0. Findings below are addressed by 0.4.0.

| Priority | Finding | Repair and regression evidence |
| --- | --- | --- |
| P1 | Default validation depended on a nonexistent standard Klipper checker. | Use installed ConfigFileReader; test valid and invalid staged includes against the official commit-pinned parser. |
| P1 | Active systemd process was treated as a healthy Klipper instance. | Poll Moonraker ready; test active service with runtime error and successful rollback. |
| P1 | Shell push bypassed active-print gates and the MCP write contract. | CLI and MCP share the runtime in the MCP package; copied-skill launcher test blocks a paused-print apply. |
| P1 | Pull could replace the workspace root or unrelated directories. | Restrict mirror destinations; test root, Git, state, scripts, backups, and local-edit preservation. |
| P1 | Remote Git metadata could be lost during whole-directory replacement. | Exclude Git from snapshots and retain the remote Git entry through apply, restore, and rollback tests. |
| P1 | Apply drift checks occurred outside any remote transaction lock. | Recheck fingerprints under a per-printer lock; test remote drift, staging drift, and competing mutation. |
| P2 | Interrupted writes lacked persistent recovery state. | Durable transaction journal, signal rollback, explicit recovery tool, and interrupted-rename recovery test. |
| P2 | Archive links, partial backups, and inconsistent exclusions made ordinary snapshots unreliable. | Bounded inert extraction, consistent manifests, cleanup on failure, and absolute-symlink round trip tests. |
| P2 | Plans/backups lacked sufficient identity, integrity, and replay checks. | Bind identity, verify backup contents and plan digest, invalidate uncertain writes, test reuse and identity mismatch. |
| P2 | Skill and MCP responsibilities risked converging into one bundled runtime. | Runtime remains solely under mcp/klipper-ops-server; skill recommends companion installation and ships only launchers. |
| P2 | CI verified imports and mocks but not executable printer workflows or distributions. | Execute the remote worker with local service simulators, MCP calls, CLI launchers, sdist-to-wheel build, and installed-wheel discovery. |

## Acceptance Boundary

The repository is tested without connecting to a physical printer. The simulator
exercises files, processes, Moonraker HTTP responses, lock contention, and recovery.
The official Klipper parser test checks syntax/includes, not hardware semantics.
Connecting a real printer still requires verifying its SSH identity, directory
layout, service privileges, Moonraker access, and post-restart readiness.

The remote lock serializes this toolkit's writes; it cannot stop an unrelated
editor, Moonraker SAVE_CONFIG, or another tool that ignores the lock. The final
fingerprint check narrows this race but is not a distributed lock on those tools.
Directory replacement uses two renames with journaled recovery, so abrupt power
loss or SIGKILL can require explicit recovery rather than immediate rollback.
