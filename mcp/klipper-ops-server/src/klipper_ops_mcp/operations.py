from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import tarfile
import tempfile
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .config import ConfigError, PrinterConfig
from .transport import PrinterCommandError, SSHTransport

STATUS_SCRIPT = r"""set -eu
config_dir=$1
scope=$2
shift 2
printf 'HOST\t%s\n' "$(hostname)"
printf 'UPTIME_SECONDS\t%s\n' "$(cut -d. -f1 /proc/uptime 2>/dev/null || printf unknown)"
if [ -d "$config_dir" ]; then
  printf 'CONFIG\tpresent\t%s\n' "$(find "$config_dir" -type f 2>/dev/null | wc -l | tr -d ' ')"
else
  printf 'CONFIG\tmissing\t0\n'
fi
for service in "$@"; do
  printf 'SERVICE\t%s\n' "$service"
  if [ "$scope" = user ]; then
    systemctl --user show "$service" --no-pager \
      -p Id -p LoadState -p ActiveState -p SubState -p MainPID \
      -p ExecMainStatus -p NRestarts -p FragmentPath 2>/dev/null || true
  else
    systemctl show "$service" --no-pager \
      -p Id -p LoadState -p ActiveState -p SubState -p MainPID \
      -p ExecMainStatus -p NRestarts -p FragmentPath 2>/dev/null || true
  fi
done
"""

LOGS_SCRIPT = r"""set -eu
service=$1
minutes=$2
lines=$3
scope=$4
if [ "$scope" = user ]; then
  journalctl --user -u "$service" --since "$minutes minutes ago" -n "$lines" --no-pager -o short-iso
else
  journalctl -u "$service" --since "$minutes minutes ago" -n "$lines" --no-pager -o short-iso
fi
"""

PRINT_STATE_SCRIPT = r"""python3 - <<'PY'
import json
import urllib.request

url = "http://127.0.0.1:7125/printer/objects/query?print_stats"
try:
    with urllib.request.urlopen(url, timeout=3) as response:
        payload = json.load(response)
    stats = payload.get("result", {}).get("status", {}).get("print_stats", {})
    print(json.dumps({
        "state": stats.get("state", "unknown"),
        "filename": stats.get("filename", ""),
        "message": stats.get("message", ""),
    }))
except Exception as exc:
    print(json.dumps({"state": "unknown", "error": str(exc)[:300]}))
PY
"""

MANIFEST_SCRIPT = r"""python3 - "$1" <<'PY'
import hashlib
import json
import os
import sys

root = os.path.abspath(sys.argv[1])
if not os.path.isdir(root):
    raise SystemExit(f"config directory does not exist: {root}")

entries = []
for directory, dirnames, filenames in os.walk(root, followlinks=False):
    for name in list(dirnames):
        path = os.path.join(directory, name)
        if os.path.islink(path):
            relative = os.path.relpath(path, root)
            target = os.readlink(path)
            entries.append({
                "path": relative,
                "type": "symlink",
                "size": len(target),
                "sha256": hashlib.sha256(target.encode()).hexdigest(),
            })
            dirnames.remove(name)
    for name in filenames:
        path = os.path.join(directory, name)
        relative = os.path.relpath(path, root)
        if os.path.islink(path):
            target = os.readlink(path)
            entries.append({
                "path": relative,
                "type": "symlink",
                "size": len(target),
                "sha256": hashlib.sha256(target.encode()).hexdigest(),
            })
            continue
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        entries.append({
            "path": relative,
            "type": "file",
            "size": os.path.getsize(path),
            "sha256": digest.hexdigest(),
        })
entries.sort(key=lambda item: item["path"])
print(json.dumps({"root": root, "files": entries}, separators=(",", ":")))
PY
"""

ARCHIVE_SCRIPT = r"""set -eu
if [ "$2" = expanded ]; then
  tar --exclude='._*' -h -C "$1" -czf - .
else
  tar --exclude='._*' -C "$1" -czf - .
fi
"""

STAGE_SCRIPT = r"""set -eu
stage=$1
case "$stage" in *'/.klipper-ops-stage-'*) ;; *) echo 'unsafe staging path' >&2; exit 64 ;; esac
rm -rf "$stage"
mkdir -p "$stage"
tar -xzf - -C "$stage"
"""

REMOVE_STAGE_SCRIPT = r"""set -eu
case "$1" in
  *'/.klipper-ops-stage-'*) rm -rf "$1" ;;
  *) echo 'unsafe staging path' >&2; exit 64 ;;
esac
"""

VALIDATE_SCRIPT = r"""set -eu
config_dir=$1
checker=$2
test -f "$config_dir/printer.cfg"
test -f "$checker"
python3 "$checker" "$config_dir/printer.cfg"
"""

RESTART_SCRIPT = r"""set -eu
service=$1
scope=$2
if [ "$scope" = user ]; then
  systemctl --user restart "$service"
  systemctl --user is-active --quiet "$service"
  state=$(systemctl --user is-active "$service")
else
  sudo -n systemctl restart "$service"
  sudo -n systemctl is-active --quiet "$service"
  state=$(systemctl is-active "$service")
fi
printf 'SERVICE\t%s\t%s\n' "$service" "$state"
"""

APPLY_SCRIPT = r"""set -eu
target=$1
stage=$2
rollback=$3
service=$4
scope=$5

case "$stage" in *'/.klipper-ops-stage-'*) ;; *) echo 'unsafe staging path' >&2; exit 64 ;; esac
case "$rollback" in
  *'/.klipper-ops-rollback-'*) ;;
  *) echo 'unsafe rollback path' >&2; exit 64 ;;
esac
test -d "$target"
test ! -L "$target"
test -d "$stage"
test ! -e "$rollback"
test ! -e "${stage}.failed"

service_restart() {
  if [ "$scope" = user ]; then
    systemctl --user restart "$service"
  else
    sudo -n systemctl restart "$service"
  fi
}
service_active() {
  if [ "$scope" = user ]; then
    systemctl --user is-active --quiet "$service"
  else
    sudo -n systemctl is-active --quiet "$service"
  fi
}

mv "$target" "$rollback"
if ! mv "$stage" "$target"; then
  mv "$rollback" "$target"
  exit 70
fi

if ! service_restart || ! service_active; then
  failed="${stage}.failed"
  mv "$target" "$failed" || true
  mv "$rollback" "$target"
  service_restart || true
  echo 'new config failed health check; previous config restored' >&2
  exit 70
fi

printf 'APPLIED\t%s\nROLLBACK\t%s\nSERVICE\t%s\tactive\n' "$target" "$rollback" "$service"
"""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_manifest(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        raise ConfigError(f"local config directory does not exist: {root}")
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            target = os.readlink(path)
            entries.append(
                {
                    "path": relative,
                    "type": "symlink",
                    "size": len(target),
                    "sha256": hashlib.sha256(target.encode()).hexdigest(),
                }
            )
        elif path.is_file():
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "size": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    return {"root": str(root), "files": entries}


def manifest_fingerprint(manifest: dict[str, Any]) -> str:
    payload = json.dumps(manifest["files"], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def compare_manifests(local: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    local_files = {item["path"]: item for item in local["files"]}
    remote_files = {item["path"]: item for item in remote["files"]}
    added = sorted(local_files.keys() - remote_files.keys())
    deleted = sorted(remote_files.keys() - local_files.keys())
    modified = sorted(
        path
        for path in local_files.keys() & remote_files.keys()
        if local_files[path] != remote_files[path]
    )
    return {
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "counts": {
            "added": len(added),
            "modified": len(modified),
            "deleted": len(deleted),
        },
        "has_changes": bool(added or modified or deleted),
    }


def _bounded_diff(diff: dict[str, Any], limit: int = 200) -> dict[str, Any]:
    result = {"counts": diff["counts"], "has_changes": diff["has_changes"]}
    for key in ("added", "modified", "deleted"):
        result[key] = diff[key][:limit]
    result["truncated"] = any(len(diff[key]) > limit for key in ("added", "modified", "deleted"))
    return result


def _create_archive(source: Path) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz", dereference=False) as archive:
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            if ".git" in relative.parts or path.name.startswith("._"):
                continue
            archive.add(path, arcname=relative.as_posix(), recursive=False)
    return stream.getvalue()


def _safe_extract(payload: bytes, target: Path) -> None:
    target_root = target.resolve()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = archive.getmembers()
        symlink_paths = {PurePosixPath(member.name) for member in members if member.issym()}
        for member in members:
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise PrinterCommandError(f"unsafe path in printer archive: {member.name}")
            if any(parent in symlink_paths for parent in member_path.parents):
                raise PrinterCommandError(
                    f"archive member traverses an archived symlink: {member.name}"
                )
            destination = (target / Path(*member_path.parts)).resolve()
            try:
                destination.relative_to(target_root)
            except ValueError as exc:
                raise PrinterCommandError(f"archive path escapes target: {member.name}") from exc
            if member.isdev() or member.isfifo():
                raise PrinterCommandError(f"unsupported archive member: {member.name}")
            if member.issym():
                link = PurePosixPath(member.linkname)
                if link.is_absolute():
                    raise PrinterCommandError(
                        f"unsafe absolute link in printer archive: {member.name}"
                    )
            elif member.islnk():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or ".." in link.parts:
                    raise PrinterCommandError(f"unsafe hard link in printer archive: {member.name}")
        archive.extractall(target, members=members, filter="fully_trusted")


class KlipperOperations:
    def __init__(self, config: PrinterConfig, transport: SSHTransport | None = None):
        self.config = config
        self.transport = transport or SSHTransport(config)

    def get_printer_status(self) -> dict[str, Any]:
        result = self.transport.run_script(
            STATUS_SCRIPT,
            (self.config.remote_config_dir, self.config.systemctl_scope, *self.config.services),
        )
        status: dict[str, Any] = {
            "printer": self.config.name,
            "host": self.config.host,
            "services": [],
        }
        current: dict[str, str] | None = None
        for line in result.text.splitlines():
            if line.startswith("HOST\t"):
                status["remote_hostname"] = line.split("\t", 1)[1]
            elif line.startswith("UPTIME_SECONDS\t"):
                raw = line.split("\t", 1)[1]
                status["uptime_seconds"] = int(raw) if raw.isdigit() else None
            elif line.startswith("CONFIG\t"):
                _, state, count = line.split("\t", 2)
                status["config"] = {"state": state, "file_count": int(count)}
            elif line.startswith("SERVICE\t"):
                current = {"name": line.split("\t", 1)[1]}
                status["services"].append(current)
            elif current is not None and "=" in line:
                key, value = line.split("=", 1)
                current[key] = value
        status["print"] = self.get_print_state()
        return status

    def get_print_state(self) -> dict[str, Any]:
        result = self.transport.run_script(PRINT_STATE_SCRIPT)
        try:
            return json.loads(result.text)
        except json.JSONDecodeError as exc:
            raise PrinterCommandError("Moonraker returned an invalid print-state response") from exc

    def get_service_logs(self, service: str, minutes: int = 15, lines: int = 120) -> dict[str, Any]:
        service = self.config.require_service(service)
        if not 1 <= minutes <= 1440:
            raise ConfigError("minutes must be between 1 and 1440")
        if not 1 <= lines <= 500:
            raise ConfigError("lines must be between 1 and 500")
        result = self.transport.run_script(
            LOGS_SCRIPT,
            (service, str(minutes), str(lines), self.config.systemctl_scope),
        )
        entries = result.text.splitlines()
        return {
            "service": service,
            "since_minutes": minutes,
            "requested_lines": lines,
            "line_count": len(entries),
            "lines": entries,
        }

    def remote_manifest(self, remote_dir: str | None = None) -> dict[str, Any]:
        result = self.transport.run_script(
            MANIFEST_SCRIPT, (remote_dir or self.config.remote_config_dir,)
        )
        try:
            return json.loads(result.text)
        except json.JSONDecodeError as exc:
            raise PrinterCommandError("printer returned an invalid config manifest") from exc

    def get_config_manifest(self, max_entries: int = 500) -> dict[str, Any]:
        if not 1 <= max_entries <= 2000:
            raise ConfigError("max_entries must be between 1 and 2000")
        manifest = self.remote_manifest()
        files = manifest["files"]
        return {
            "root": manifest["root"],
            "fingerprint": manifest_fingerprint(manifest),
            "file_count": len(files),
            "files": files[:max_entries],
            "truncated": len(files) > max_entries,
        }

    def diff_config(self, local_config_dir: str = "printer_data/config") -> dict[str, Any]:
        local_dir = self.config.resolve_workspace_path(local_config_dir)
        local = local_manifest(local_dir)
        remote = self.remote_manifest()
        return {
            "local_root": str(local_dir),
            "remote_root": remote["root"],
            "local_fingerprint": manifest_fingerprint(local),
            "remote_fingerprint": manifest_fingerprint(remote),
            **_bounded_diff(compare_manifests(local, remote)),
        }

    def _download_archive(self, remote_dir: str, expanded: bool = False) -> bytes:
        return self.transport.run_script(
            ARCHIVE_SCRIPT, (remote_dir, "expanded" if expanded else "preserve")
        ).stdout

    def _backup_remote(self) -> dict[str, Any]:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_id = f"{self.config.name}/{timestamp}-{secrets.token_hex(3)}"
        backups_root = self.config.resolve_workspace_path("backups")
        backups_root.mkdir(parents=True, exist_ok=True)
        printer_backup_root = (backups_root / self.config.name).resolve()
        try:
            printer_backup_root.relative_to(backups_root)
        except ValueError as exc:
            raise ConfigError("printer backup directory escapes the workspace") from exc
        backup_root = printer_backup_root / backup_id.rsplit("/", 1)[1]
        config_dir = backup_root / "config"
        config_dir.mkdir(parents=True, exist_ok=False)
        _safe_extract(self._download_archive(self.config.remote_config_dir), config_dir)
        metadata = {
            "backup_id": backup_id,
            "printer": self.config.name,
            "host": self.config.host,
            "remote_config_dir": self.config.remote_config_dir,
            "created_at": datetime.now(UTC).isoformat(),
            "fingerprint": manifest_fingerprint(local_manifest(config_dir)),
        }
        (backup_root / "metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        return {**metadata, "path": str(config_dir)}

    def backup_config(self) -> dict[str, Any]:
        return self._backup_remote()

    def pull_config(
        self, local_config_dir: str = "printer_data/config", expanded: bool = False
    ) -> dict[str, Any]:
        if expanded and local_config_dir == "printer_data/config":
            local_config_dir = "printer_data/config-expanded"
        target = self.config.resolve_workspace_path(local_config_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix=f".{target.name}.pull-", dir=target.parent))
        old: Path | None = None
        try:
            _safe_extract(self._download_archive(self.config.remote_config_dir, expanded), temp)
            manifest = local_manifest(temp)
            if target.exists():
                old = target.with_name(f".{target.name}.old-{secrets.token_hex(4)}")
                os.replace(target, old)
            os.replace(temp, target)
            if old:
                shutil.rmtree(old)
            return {
                "path": str(target),
                "expanded": expanded,
                "file_count": len(manifest["files"]),
                "fingerprint": manifest_fingerprint(manifest),
            }
        except Exception:
            if old and old.exists() and not target.exists():
                os.replace(old, target)
            raise
        finally:
            if temp.exists():
                shutil.rmtree(temp)

    def _stage_path(self, identifier: str) -> str:
        parent = str(PurePosixPath(self.config.remote_config_dir).parent)
        return f"{parent}/.klipper-ops-stage-{identifier}"

    def _upload_stage(self, source: Path, stage: str) -> None:
        self.transport.run_script(STAGE_SCRIPT, (stage,), input_bytes=_create_archive(source))

    def _remove_stage(self, stage: str) -> None:
        self.transport.run_script(REMOVE_STAGE_SCRIPT, (stage,))

    def _validate_remote(self, remote_dir: str) -> dict[str, Any]:
        result = self.transport.run_script(
            VALIDATE_SCRIPT,
            (remote_dir, self.config.check_script),
            check=False,
            timeout=max(self.config.ssh_timeout, 60),
        )
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")[-4000:]
        return {"valid": result.returncode == 0, "exit_code": result.returncode, "output": output}

    def validate_config(self, local_config_dir: str = "printer_data/config") -> dict[str, Any]:
        source = self.config.resolve_workspace_path(local_config_dir)
        local = local_manifest(source)
        stage = self._stage_path(f"validate-{secrets.token_hex(6)}")
        uploaded = False
        try:
            self._upload_stage(source, stage)
            uploaded = True
            validation = self._validate_remote(stage)
            staged = self.remote_manifest(stage)
            validation.update(
                {
                    "local_fingerprint": manifest_fingerprint(local),
                    "staged_fingerprint": manifest_fingerprint(staged),
                }
            )
            return validation
        finally:
            if uploaded:
                self._remove_stage(stage)

    def prepare_config_apply(self, local_config_dir: str = "printer_data/config") -> dict[str, Any]:
        source = self.config.resolve_workspace_path(local_config_dir)
        local = local_manifest(source)
        remote = self.remote_manifest()
        diff = compare_manifests(local, remote)
        if not diff["has_changes"]:
            raise ConfigError("local and remote config manifests are identical")

        backup = self._backup_remote()
        nonce = secrets.token_hex(16)
        created_at = int(time.time())
        plan_hash = hashlib.sha256(
            f"{nonce}:{manifest_fingerprint(local)}:{manifest_fingerprint(remote)}".encode()
        ).hexdigest()
        stage = self._stage_path(plan_hash)
        try:
            self._upload_stage(source, stage)
        except Exception:
            with suppress(PrinterCommandError):
                self._remove_stage(stage)
            raise
        validation = self._validate_remote(stage)
        if not validation["valid"]:
            self._remove_stage(stage)
            raise PrinterCommandError(f"staged config validation failed: {validation['output']}")
        staged = self.remote_manifest(stage)
        local_fingerprint = manifest_fingerprint(local)
        if manifest_fingerprint(staged) != local_fingerprint:
            self._remove_stage(stage)
            raise PrinterCommandError("staged config does not match the local manifest")

        plan = {
            "schema": 1,
            "plan_hash": plan_hash,
            "created_at": created_at,
            "expires_at": created_at + self.config.plan_ttl_seconds,
            "printer": self.config.name,
            "host": self.config.host,
            "remote_config_dir": self.config.remote_config_dir,
            "stage": stage,
            "local_fingerprint": local_fingerprint,
            "remote_fingerprint": manifest_fingerprint(remote),
            "backup_id": backup["backup_id"],
            "backup_path": backup["path"],
            "diff": diff,
            "applied": False,
        }
        plans_dir = self.config.resolve_workspace_path(".klipper-ops/plans")
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plans_dir / f"{plan_hash}.json"
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        os.chmod(plan_path, 0o600)
        return {
            "plan_hash": plan_hash,
            "expires_at": plan["expires_at"],
            "backup_id": backup["backup_id"],
            "backup_path": backup["path"],
            "validation": validation,
            **_bounded_diff(diff),
        }

    def _load_plan(self, plan_hash: str) -> tuple[Path, dict[str, Any]]:
        if not re.fullmatch(r"[0-9a-f]{64}", plan_hash):
            raise ConfigError("plan_hash must be a 64-character lowercase hex digest")
        plan_path = self.config.resolve_workspace_path(f".klipper-ops/plans/{plan_hash}.json")
        if not plan_path.is_file():
            raise ConfigError("apply plan was not found in this workspace")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan.get("plan_hash") != plan_hash or plan.get("schema") != 1:
            raise ConfigError("apply plan is invalid")
        if (
            plan.get("host") != self.config.host
            or plan.get("remote_config_dir") != self.config.remote_config_dir
        ):
            raise ConfigError("apply plan belongs to another printer configuration")
        if plan.get("applied"):
            raise ConfigError("apply plan has already been used")
        if int(plan.get("expires_at", 0)) < int(time.time()):
            cleanup_error = ""
            try:
                self._remove_stage(str(plan.get("stage", "")))
                plan["expired_stage_removed_at"] = int(time.time())
                plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            except PrinterCommandError as exc:
                cleanup_error = f"; staging cleanup also failed: {exc}"
            raise ConfigError(f"apply plan has expired; prepare a new plan{cleanup_error}")
        return plan_path, plan

    def _require_idle(self, allow_unknown_print_state: bool) -> dict[str, Any]:
        print_state = self.get_print_state()
        state = str(print_state.get("state", "unknown")).lower()
        if state in {"printing", "paused"}:
            raise PrinterCommandError(f"write operation refused while printer state is {state}")
        if state == "unknown" and not allow_unknown_print_state:
            raise PrinterCommandError(
                "printer state is unknown; retry when Moonraker is reachable or explicitly "
                "allow unknown state"
            )
        return print_state

    def apply_config(
        self,
        plan_hash: str,
        confirm: bool,
        restart_service: str = "klipper",
        allow_unknown_print_state: bool = False,
    ) -> dict[str, Any]:
        if confirm is not True:
            raise ConfigError("confirm=true is required after the user reviews the prepared plan")
        service = self.config.require_service(restart_service)
        plan_path, plan = self._load_plan(plan_hash)
        print_state = self._require_idle(allow_unknown_print_state)
        current = self.remote_manifest()
        if manifest_fingerprint(current) != plan["remote_fingerprint"]:
            raise PrinterCommandError(
                "remote config changed after plan preparation; prepare a new plan"
            )
        staged = self.remote_manifest(plan["stage"])
        if manifest_fingerprint(staged) != plan["local_fingerprint"]:
            raise PrinterCommandError(
                "staged config changed after plan preparation; prepare a new plan"
            )

        parent = str(PurePosixPath(self.config.remote_config_dir).parent)
        rollback = f"{parent}/.klipper-ops-rollback-{plan_hash}"
        result = self.transport.run_script(
            APPLY_SCRIPT,
            (
                self.config.remote_config_dir,
                plan["stage"],
                rollback,
                service,
                self.config.systemctl_scope,
            ),
            timeout=max(self.config.ssh_timeout, 90),
        )
        plan.update(
            {
                "applied": True,
                "applied_at": int(time.time()),
                "rollback_path": rollback,
                "restart_service": service,
            }
        )
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        return {
            "applied": True,
            "plan_hash": plan_hash,
            "service": service,
            "service_state": "active",
            "rollback_path": rollback,
            "backup_id": plan["backup_id"],
            "print_state_before_apply": print_state,
            "remote_output": result.text.splitlines(),
        }

    def restart_service(
        self,
        service: str,
        confirm: bool,
        allow_unknown_print_state: bool = False,
    ) -> dict[str, Any]:
        if confirm is not True:
            raise ConfigError("confirm=true is required for service restarts")
        service = self.config.require_service(service)
        print_state = self._require_idle(allow_unknown_print_state)
        result = self.transport.run_script(
            RESTART_SCRIPT,
            (service, self.config.systemctl_scope),
            timeout=max(self.config.ssh_timeout, 60),
        )
        return {
            "service": service,
            "state": "active",
            "print_state_before_restart": print_state,
            "remote_output": result.text.splitlines(),
        }

    def restore_backup(
        self,
        backup_id: str,
        confirm_backup_id: str,
        restart_service: str = "klipper",
        allow_unknown_print_state: bool = False,
    ) -> dict[str, Any]:
        if confirm_backup_id != backup_id:
            raise ConfigError("confirm_backup_id must exactly match backup_id")
        backups_root = self.config.resolve_workspace_path("backups")
        source = (backups_root / backup_id / "config").resolve()
        try:
            source.relative_to(backups_root)
        except ValueError as exc:
            raise ConfigError("backup_id escapes the workspace backup directory") from exc
        if not source.is_dir():
            raise ConfigError(f"backup does not exist: {backup_id}")
        relative_source = source.relative_to(self.config.project_root).as_posix()
        prepared = self.prepare_config_apply(relative_source)
        applied = self.apply_config(
            prepared["plan_hash"],
            confirm=True,
            restart_service=restart_service,
            allow_unknown_print_state=allow_unknown_print_state,
        )
        return {"restored_backup_id": backup_id, "prepared": prepared, "applied": applied}
