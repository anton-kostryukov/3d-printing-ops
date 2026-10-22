from __future__ import annotations

import difflib
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import ConfigError, PrinterConfig
from .files import create_archive, extract_archive, fingerprint, manifest
from .transport import PrinterCommandError, SSHTransport


def compare_manifests(local: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    before = {entry["path"]: entry for entry in remote["files"]}
    after = {entry["path"]: entry for entry in local["files"]}
    added = sorted(after.keys() - before.keys())
    deleted = sorted(before.keys() - after.keys())
    modified = sorted(path for path in after.keys() & before.keys() if after[path] != before[path])
    return {
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "counts": {"added": len(added), "modified": len(modified), "deleted": len(deleted)},
        "has_changes": bool(added or modified or deleted),
    }


def bounded_diff(diff: dict[str, Any]) -> dict[str, Any]:
    return {
        **diff,
        **{key: diff[key][:200] for key in ("added", "modified", "deleted")},
        "truncated": any(len(diff[key]) > 200 for key in ("added", "modified", "deleted")),
    }


def config_patch(source: Path, backup: Path, diff: dict[str, Any]) -> dict[str, Any]:
    lines: list[str] = []
    truncated = False
    for relative in sorted(set(diff["added"] + diff["modified"] + diff["deleted"])):
        if Path(relative).suffix not in {".cfg", ".conf", ".ini"}:
            continue
        before, after = backup / relative, source / relative
        parts = Path(relative).parts
        if any(
            root.joinpath(*parts[:index]).is_symlink()
            for root in (source, backup)
            for index in range(1, len(parts) + 1)
        ):
            continue
        if any(path.is_file() and path.stat().st_size > 65536 for path in (before, after)):
            truncated = True
            continue
        try:
            old = before.read_text().splitlines() if before.is_file() else []
            new = after.read_text().splitlines() if after.is_file() else []
        except UnicodeDecodeError:
            continue
        for line in difflib.unified_diff(
            old, new, fromfile="remote/" + relative, tofile="candidate/" + relative, lineterm=""
        ):
            if len(lines) >= 200 or sum(map(len, lines)) + len(line) > 20000:
                truncated = True
                break
            lines.append(line[:2000])
    return {"patch": "\n".join(lines), "patch_truncated": truncated}


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class KlipperOperations:
    def __init__(self, config: PrinterConfig, transport: SSHTransport | None = None):
        self.config = config
        self.transport = transport or SSHTransport(config)

    @contextmanager
    def workspace_lock(self):
        state = self.config.resolve_workspace_path(".klipper-ops")
        state.mkdir(mode=0o700, exist_ok=True)
        descriptor = os.open(state / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ConfigError("another operation holds this workspace lock") from exc
            yield
        finally:
            os.close(descriptor)

    def get_printer_status(self) -> dict[str, Any]:
        return {
            "printer": self.config.name,
            "host": self.config.host,
            **self.transport.run("status"),
        }

    def get_print_state(self) -> dict[str, Any]:
        return self.transport.run("state")

    def get_service_logs(self, service: str, minutes: int = 15, lines: int = 120) -> dict[str, Any]:
        self.config.require_service(service)
        if not 1 <= minutes <= 1440 or not 1 <= lines <= 500:
            raise ConfigError("log bounds: minutes 1-1440, lines 1-500")
        return self.transport.run("logs", service=service, minutes=minutes, lines=lines)

    def remote_manifest(self) -> dict[str, Any]:
        return self.transport.run("manifest")

    def get_config_manifest(self, max_entries: int = 500) -> dict[str, Any]:
        if not 1 <= max_entries <= 2000:
            raise ConfigError("max_entries must be between 1 and 2000")
        snapshot = self.remote_manifest()
        return {
            "root": snapshot["root"],
            "fingerprint": fingerprint(snapshot),
            "file_count": len(snapshot["files"]),
            "files": snapshot["files"][:max_entries],
            "truncated": len(snapshot["files"]) > max_entries,
        }

    def diff_config(self, local_config_dir: str = "printer_data/config") -> dict[str, Any]:
        source = self.config.config_source(local_config_dir)
        local, remote = manifest(source), self.remote_manifest()
        return {
            "local_root": str(source),
            "remote_root": remote["root"],
            "local_fingerprint": fingerprint(local),
            "remote_fingerprint": fingerprint(remote),
            **bounded_diff(compare_manifests(local, remote)),
        }

    def _backup_remote(self) -> dict[str, Any]:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_id = f"{self.config.name}/{timestamp}-{secrets.token_hex(4)}"
        backup_root = self.config.resolve_workspace_path("backups/" + backup_id)
        backup_root.mkdir(mode=0o700, parents=True, exist_ok=False)
        config_dir = backup_root / "config"
        try:
            extract_archive(self.transport.run("archive"), config_dir)
            metadata = {
                "schema": 1,
                "backup_id": backup_id,
                "printer": self.config.name,
                "identity": self.identity(),
                "created_at": datetime.now(UTC).isoformat(),
                "fingerprint": fingerprint(manifest(config_dir)),
            }
            atomic_json(backup_root / "metadata.json", metadata)
            return {**metadata, "path": str(config_dir)}
        except BaseException:
            shutil.rmtree(backup_root)
            raise

    def backup_config(self) -> dict[str, Any]:
        with self.workspace_lock():
            return self._backup_remote()

    def pull_config(
        self,
        local_config_dir: str = "printer_data/config",
        expanded: bool = False,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        if expanded and local_config_dir == "printer_data/config":
            local_config_dir = "printer_data/config-expanded"
        target = self.config.mirror_target(local_config_dir)
        with self.workspace_lock():
            return self._pull(target, expanded, overwrite)

    def _pull(self, target: Path, expanded: bool, overwrite: bool) -> dict[str, Any]:
        record = self.config.resolve_workspace_path(f".klipper-ops/{target.name}-mirror.json")
        if target.exists() and any(target.iterdir()) and not overwrite:
            previous = json.loads(record.read_text()) if record.is_file() else {}
            if (
                previous.get("fingerprint") != fingerprint(manifest(target))
                or previous.get("identity") != self.identity()
            ):
                raise ConfigError(
                    "local mirror has edits or was not pulled by this tool; "
                    "use overwrite=true after reviewing them"
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.pull-", dir=target.parent))
        old = target.with_name(f".{target.name}.old-{secrets.token_hex(6)}")
        try:
            extract_archive(self.transport.run("archive", expanded=expanded), temporary)
            snapshot = manifest(temporary)
            if target.exists():
                os.replace(target, old)
            try:
                os.replace(temporary, target)
            except BaseException:
                if old.exists():
                    os.replace(old, target)
                raise
            atomic_json(record, {"fingerprint": fingerprint(snapshot), "identity": self.identity()})
            return {
                "path": str(target),
                "expanded": expanded,
                "file_count": len(snapshot["files"]),
                "fingerprint": fingerprint(snapshot),
            }
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
            if old.exists():
                shutil.rmtree(old)

    def identity(self) -> dict[str, str]:
        return {
            "host": self.config.host,
            "user": self.config.user,
            "config_dir": self.config.remote_config_dir,
            "klipper_service": self.config.klipper_service,
            "scope": self.config.systemctl_scope,
            "moonraker_url": self.config.moonraker_url,
        }

    def _upload(self, source: Path, token: str) -> dict[str, Any]:
        return self.transport.run("stage", token=token, payload=create_archive(source))

    def validate_config(self, local_config_dir: str = "printer_data/config") -> dict[str, Any]:
        source = self.config.config_source(local_config_dir)
        token = secrets.token_hex(32)
        with self.workspace_lock():
            try:
                return self._upload(source, token)["validation"]
            finally:
                with suppress(PrinterCommandError):
                    self.transport.run("discard", token=token)

    def prepare_config_apply(self, local_config_dir: str = "printer_data/config") -> dict[str, Any]:
        source = self.config.config_source(local_config_dir)
        with self.workspace_lock():
            return self._prepare(source)

    def _prepare(self, source: Path) -> dict[str, Any]:
        local, remote = manifest(source), self.remote_manifest()
        diff = compare_manifests(local, remote)
        if not diff["has_changes"]:
            raise ConfigError("local and remote config are identical")
        backup = self._backup_remote()
        if backup["fingerprint"] != fingerprint(remote):
            raise PrinterCommandError("remote config changed during backup; prepare again")
        token = secrets.token_hex(32)
        success = False
        try:
            staged = self._upload(source, token)
            if staged["fingerprint"] != fingerprint(local):
                raise PrinterCommandError("candidate changed during upload; prepare again")
            plan = {
                "schema": 2,
                "token": token,
                "identity": self.identity(),
                "expires_at": staged["expires_at"],
                "local_fingerprint": fingerprint(local),
                "remote_fingerprint": fingerprint(remote),
                "backup_id": backup["backup_id"],
                "backup_path": backup["path"],
                "validation": staged["validation"],
                "diff": diff,
                "patch": config_patch(source, Path(backup["path"]), diff),
            }
            if fingerprint(manifest(source)) != plan["local_fingerprint"]:
                raise PrinterCommandError("local config changed while preparing the review patch")
            plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
            plans = self.config.resolve_workspace_path(".klipper-ops/plans")
            plans.mkdir(mode=0o700, exist_ok=True)
            atomic_json(plans / f"{plan_hash}.json", {"plan": plan, "status": "prepared"})
            success = True
            return {
                "plan_hash": plan_hash,
                "expires_at": plan["expires_at"],
                "backup_id": plan["backup_id"],
                "backup_path": plan["backup_path"],
                "validation": plan["validation"],
                **plan["patch"],
                **bounded_diff(diff),
            }
        finally:
            if not success:
                with suppress(PrinterCommandError):
                    self.transport.run("discard", token=token)

    def _load_plan(
        self,
        plan_hash: str,
        allow_expired: bool = False,
    ) -> tuple[Path, dict[str, Any]]:
        if not re.fullmatch(r"[0-9a-f]{64}", plan_hash):
            raise ConfigError("invalid plan_hash")
        path = self.config.resolve_workspace_path(f".klipper-ops/plans/{plan_hash}.json")
        if not path.is_file():
            raise ConfigError("apply plan not found")
        record = json.loads(path.read_text())
        plan = record["plan"]
        expected = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        if (
            expected != plan_hash
            or plan.get("schema") != 2
            or plan.get("identity") != self.identity()
        ):
            raise ConfigError("apply plan was altered or belongs to another printer configuration")
        statuses = {"prepared", "uncertain", "applying"} if allow_expired else {"prepared"}
        if record.get("status") not in statuses:
            raise ConfigError("apply plan has been used, discarded, or has an uncertain outcome")
        if not allow_expired and plan["expires_at"] <= time.time():
            raise ConfigError("apply plan has expired; discard it and prepare again")
        return path, record

    def apply_config(
        self,
        plan_hash: str,
        confirm: bool,
        restart_service: str | None = None,
        allow_unknown_print_state: bool = False,
    ) -> dict[str, Any]:
        if confirm is not True:
            raise ConfigError("confirm=true is required after review")
        service = restart_service or self.config.klipper_service
        self.config.require_service(service)
        if service != self.config.klipper_service:
            raise ConfigError("config apply must restart PRINTER_KLIPPER_SERVICE")
        with self.workspace_lock():
            path, record = self._load_plan(plan_hash)
            plan = record["plan"]
            record["status"] = "applying"
            atomic_json(path, record)
            try:
                result = self.transport.run(
                    "apply",
                    token=plan["token"],
                    service=service,
                    expected_remote=plan["remote_fingerprint"],
                    expected_local=plan["local_fingerprint"],
                    allow_unknown_print_state=allow_unknown_print_state,
                )
            except BaseException:
                record["status"] = "uncertain"
                atomic_json(path, record)
                raise
            record["status"] = "applied"
            atomic_json(path, record)
            return {
                **result,
                "plan_hash": plan_hash,
                "backup_id": plan["backup_id"],
                "backup_path": plan["backup_path"],
            }

    def discard_config_apply(self, plan_hash: str) -> dict[str, Any]:
        with self.workspace_lock():
            path, record = self._load_plan(plan_hash, allow_expired=True)
            self.transport.run("discard", token=record["plan"]["token"])
            record["status"] = "discarded"
            atomic_json(path, record)
            return {"discarded": True, "plan_hash": plan_hash}

    def restart_service(
        self,
        service: str,
        confirm: bool,
        allow_unknown_print_state: bool = False,
    ) -> dict[str, Any]:
        if confirm is not True:
            raise ConfigError("confirm=true is required for restarts")
        self.config.require_service(service)
        with self.workspace_lock():
            return self.transport.run(
                "restart",
                service=service,
                allow_unknown_print_state=allow_unknown_print_state,
            )

    def restore_backup(
        self,
        backup_id: str,
        confirm_backup_id: str,
        restart_service: str | None = None,
        allow_unknown_print_state: bool = False,
    ) -> dict[str, Any]:
        if backup_id != confirm_backup_id:
            raise ConfigError("confirm_backup_id must match backup_id")
        if not re.fullmatch(re.escape(self.config.name) + r"/[A-Za-z0-9_-]+", backup_id):
            raise ConfigError("backup_id must name this printer's backup")
        source = self.config.config_source("backups/" + backup_id + "/config")
        metadata_path = source.parent / "metadata.json"
        if not metadata_path.is_file():
            raise ConfigError("backup has no verified metadata")
        metadata = json.loads(metadata_path.read_text())
        if metadata.get("identity") != self.identity() or metadata.get(
            "fingerprint"
        ) != fingerprint(manifest(source)):
            raise ConfigError("backup identity or content does not match its metadata")
        prepared = self.prepare_config_apply(str(source))
        return {
            "restored_backup_id": backup_id,
            **self.apply_config(
                prepared["plan_hash"],
                True,
                restart_service,
                allow_unknown_print_state,
            ),
        }

    def recover_config(
        self, confirm: bool, allow_unknown_print_state: bool = False
    ) -> dict[str, Any]:
        if confirm is not True:
            raise ConfigError("confirm=true is required for recovery")
        with self.workspace_lock():
            return self.transport.run(
                "recover",
                service=self.config.klipper_service,
                allow_unknown_print_state=allow_unknown_print_state,
            )
