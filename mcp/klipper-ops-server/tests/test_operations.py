from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from klipper_ops_mcp.config import ConfigError, PrinterConfig
from klipper_ops_mcp.operations import (
    APPLY_SCRIPT,
    ARCHIVE_SCRIPT,
    PRINT_STATE_SCRIPT,
    STATUS_SCRIPT,
    KlipperOperations,
    _safe_extract,
    compare_manifests,
    local_manifest,
    manifest_fingerprint,
)
from klipper_ops_mcp.transport import CommandResult, PrinterCommandError


def make_config(root: Path) -> PrinterConfig:
    return PrinterConfig(
        project_root=root,
        name="test-printer",
        host="printer.local",
        user="pi",
        remote_home="/home/pi",
        remote_data_dir="/home/pi/printer_data",
        remote_config_dir="/home/pi/printer_data/config",
        remote_log_dir="/home/pi/printer_data/logs",
        services=("klipper", "moonraker"),
        check_script="/home/pi/klipper/scripts/check_config.py",
        systemctl_scope="system",
        known_hosts_path=root / ".known_hosts",
        askpass_path=None,
        ssh_timeout=30,
        plan_ttl_seconds=3600,
    )


class StatusTransport:
    def run_script(self, script: str, args=(), **kwargs) -> CommandResult:
        if script == PRINT_STATE_SCRIPT:
            payload = json.dumps({"state": "standby", "filename": ""}).encode()
        elif script == STATUS_SCRIPT:
            payload = (
                b"HOST\tprinter\nUPTIME_SECONDS\t42\nCONFIG\tpresent\t7\n"
                b"SERVICE\tklipper\nId=klipper.service\nActiveState=active\n"
                b"SERVICE\tmoonraker\nId=moonraker.service\nActiveState=active\n"
            )
        else:
            raise AssertionError("unexpected script")
        return CommandResult(payload, b"", 0)


class ApplyTransport:
    def __init__(self) -> None:
        self.applied = False

    def run_script(self, script: str, args=(), **kwargs) -> CommandResult:
        assert script == APPLY_SCRIPT
        self.applied = True
        return CommandResult(
            f"APPLIED\t{args[0]}\nROLLBACK\t{args[2]}\nSERVICE\t{args[3]}\tactive\n".encode(),
            b"",
            0,
        )


class PlannedOperations(KlipperOperations):
    def __init__(
        self,
        config: PrinterConfig,
        transport: ApplyTransport,
        remote: dict,
    ) -> None:
        super().__init__(config, transport)
        self.remote = remote
        self.staged: dict | None = None

    def remote_manifest(self, remote_dir: str | None = None) -> dict:
        if remote_dir is None:
            return self.remote
        assert self.staged is not None
        return self.staged

    def _backup_remote(self) -> dict:
        return {
            "backup_id": "test-printer/backup-1",
            "path": str(self.config.project_root / "backups/test-printer/backup-1/config"),
        }

    def _upload_stage(self, source: Path, stage: str) -> None:
        self.staged = local_manifest(source)
        self.staged["root"] = stage

    def _validate_remote(self, remote_dir: str) -> dict:
        return {"valid": True, "exit_code": 0, "output": "config valid"}

    def get_print_state(self) -> dict:
        return {"state": "standby", "filename": ""}


def test_local_manifest_and_diff_are_deterministic(tmp_path: Path) -> None:
    local_dir = tmp_path / "local"
    remote_dir = tmp_path / "remote"
    local_dir.mkdir()
    remote_dir.mkdir()
    (local_dir / "printer.cfg").write_text("new\n", encoding="utf-8")
    (local_dir / "added.cfg").write_text("added\n", encoding="utf-8")
    (remote_dir / "printer.cfg").write_text("old\n", encoding="utf-8")
    (remote_dir / "deleted.cfg").write_text("deleted\n", encoding="utf-8")

    local = local_manifest(local_dir)
    remote = local_manifest(remote_dir)
    diff = compare_manifests(local, remote)

    assert diff["added"] == ["added.cfg"]
    assert diff["modified"] == ["printer.cfg"]
    assert diff["deleted"] == ["deleted.cfg"]
    assert manifest_fingerprint(local) == manifest_fingerprint(local_manifest(local_dir))


def test_archive_path_traversal_is_rejected(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        member = tarfile.TarInfo("../outside")
        member.size = 3
        archive.addfile(member, io.BytesIO(b"bad"))

    with pytest.raises(PrinterCommandError):
        _safe_extract(payload.getvalue(), tmp_path / "target")


def test_archive_cannot_write_through_symlink(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        link = tarfile.TarInfo("escape")
        link.type = tarfile.SYMTYPE
        link.linkname = "../outside"
        archive.addfile(link)
        child = tarfile.TarInfo("escape/file.cfg")
        child.size = 3
        archive.addfile(child, io.BytesIO(b"bad"))

    with pytest.raises(PrinterCommandError, match="traverses an archived symlink"):
        _safe_extract(payload.getvalue(), tmp_path / "target")


def test_standalone_relative_symlink_is_preserved(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        link = tarfile.TarInfo("external.cfg")
        link.type = tarfile.SYMTYPE
        link.linkname = "../shared/external.cfg"
        archive.addfile(link)
    target = tmp_path / "target"
    target.mkdir()

    _safe_extract(payload.getvalue(), target)

    assert (target / "external.cfg").is_symlink()
    assert (target / "external.cfg").readlink() == Path("../shared/external.cfg")


def test_status_is_structured(tmp_path: Path) -> None:
    operations = KlipperOperations(make_config(tmp_path), StatusTransport())

    status = operations.get_printer_status()

    assert status["remote_hostname"] == "printer"
    assert status["config"] == {"state": "present", "file_count": 7}
    assert [service["ActiveState"] for service in status["services"]] == ["active", "active"]
    assert status["print"]["state"] == "standby"


def test_apply_requires_confirmation_before_remote_calls(tmp_path: Path) -> None:
    operations = KlipperOperations(make_config(tmp_path), StatusTransport())

    with pytest.raises(ConfigError):
        operations.apply_config("0" * 64, confirm=False)


def test_active_print_blocks_writes(tmp_path: Path) -> None:
    class PrintingTransport:
        def run_script(self, script: str, args=(), **kwargs) -> CommandResult:
            assert script == PRINT_STATE_SCRIPT
            return CommandResult(b'{"state":"printing"}', b"", 0)

    operations = KlipperOperations(make_config(tmp_path), PrintingTransport())

    with pytest.raises(PrinterCommandError, match="printing"):
        operations._require_idle(False)


def test_expanded_pull_uses_separate_default_target(tmp_path: Path) -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        content = b"[printer]\n"
        member = tarfile.TarInfo("printer.cfg")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))

    class PullTransport:
        def run_script(self, script: str, args=(), **kwargs) -> CommandResult:
            assert script == ARCHIVE_SCRIPT
            assert args[1] == "expanded"
            return CommandResult(payload.getvalue(), b"", 0)

    operations = KlipperOperations(make_config(tmp_path), PullTransport())

    result = operations.pull_config(expanded=True)

    assert result["path"] == str((tmp_path / "printer_data/config-expanded").resolve())
    assert (tmp_path / "printer_data/config-expanded/printer.cfg").is_file()
    assert not (tmp_path / "printer_data/config/printer.cfg").exists()


def test_prepare_and_apply_recheck_fingerprints(tmp_path: Path) -> None:
    local_dir = tmp_path / "printer_data/config"
    remote_dir = tmp_path / "remote"
    local_dir.mkdir(parents=True)
    remote_dir.mkdir()
    (local_dir / "printer.cfg").write_text("new\n", encoding="utf-8")
    (remote_dir / "printer.cfg").write_text("old\n", encoding="utf-8")
    remote = local_manifest(remote_dir)
    remote["root"] = "/home/pi/printer_data/config"
    transport = ApplyTransport()
    operations = PlannedOperations(make_config(tmp_path), transport, remote)

    prepared = operations.prepare_config_apply()
    applied = operations.apply_config(prepared["plan_hash"], confirm=True)

    assert prepared["counts"] == {"added": 0, "modified": 1, "deleted": 0}
    assert applied["applied"] is True
    assert transport.applied is True


def test_remote_drift_blocks_prepared_apply(tmp_path: Path) -> None:
    local_dir = tmp_path / "printer_data/config"
    remote_dir = tmp_path / "remote"
    local_dir.mkdir(parents=True)
    remote_dir.mkdir()
    (local_dir / "printer.cfg").write_text("new\n", encoding="utf-8")
    (remote_dir / "printer.cfg").write_text("old\n", encoding="utf-8")
    remote = local_manifest(remote_dir)
    remote["root"] = "/home/pi/printer_data/config"
    transport = ApplyTransport()
    operations = PlannedOperations(make_config(tmp_path), transport, remote)
    prepared = operations.prepare_config_apply()
    operations.remote["files"][0]["sha256"] = "f" * 64

    with pytest.raises(PrinterCommandError, match="remote config changed"):
        operations.apply_config(prepared["plan_hash"], confirm=True)

    assert transport.applied is False
