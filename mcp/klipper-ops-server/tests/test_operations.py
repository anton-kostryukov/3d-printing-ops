from __future__ import annotations

import asyncio
import fcntl
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from klipper_ops_mcp.config import ConfigError, load_config
from klipper_ops_mcp.files import create_archive, extract_archive, fingerprint, manifest
from klipper_ops_mcp.operations import KlipperOperations
from klipper_ops_mcp.transport import PrinterCommandError, SSHTransport


class LocalHostTransport(SSHTransport):
    """Execute the actual remote worker in a sandbox printer directory, without SSH."""

    def _execute(self, remote_command, payload, timeout):
        result = subprocess.run(
            shlex.split(remote_command),
            input=payload,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            raise PrinterCommandError(result.stderr.decode())
        return result.stdout


@pytest.fixture
def printer(tmp_path, monkeypatch):
    host = tmp_path / "host"
    remote = host / "printer_data/config"
    remote.mkdir(parents=True)
    (remote / "printer.cfg").write_text("[printer]\nmax_velocity: 100\n")
    (remote / ".git").mkdir()
    (remote / ".git/HEAD").write_text("ref: refs/heads/main\n")
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "systemctl").write_text(
        "#!" + sys.executable + "\n"
        "import os,sys,pathlib\n"
        "args=sys.argv[1:]\n"
        "if 'show' in args: print('ActiveState=active\\nLoadState=loaded')\n"
        "if 'restart' in args:\n"
        " p=pathlib.Path(os.environ['TEST_REMOTE'])/'restart-count'\n"
        " p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\n"
        "if 'is-active' in args: print('active')\n"
    )
    (binary / "sudo").write_text('#!/usr/bin/env bash\nshift\nexec "$@"\n')
    (binary / "ssh").write_text(
        "#!" + sys.executable + "\nimport subprocess,sys\n"
        "raise SystemExit(subprocess.call(sys.argv[-1],shell=True))\n"
    )
    for executable in binary.iterdir():
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("TEST_REMOTE", str(host))
    state = {"print": "standby", "unavailable": False, "bad_config": False}

    class Moonraker(BaseHTTPRequestHandler):
        def do_GET(self):
            if state["unavailable"]:
                self.send_error(503)
                return
            if self.path.startswith("/printer/info"):
                bad = "bad" in (remote / "printer.cfg").read_text()
                result = {
                    "state": "error" if bad else "ready",
                    "state_message": "bad config" if bad else "ready",
                }
            else:
                result = {
                    "status": {
                        "print_stats": {"state": state["print"]},
                        "webhooks": {"state": "ready"},
                    }
                }
            body = json.dumps({"result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Moonraker)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    checker = host / "check.py"
    checker.write_text("import sys\nfrom pathlib import Path\nassert Path(sys.argv[1]).is_file()\n")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    values = {
        "PRINTER_HOST": "printer.local",
        "PRINTER_USER": "pi",
        "PRINTER_REMOTE_CONFIG_DIR": str(remote),
        "PRINTER_REMOTE_HOME": str(host),
        "PRINTER_MOONRAKER_URL": f"http://127.0.0.1:{server.server_port}",
        "PRINTER_KLIPPER_CHECK_SCRIPT": str(checker),
        "KLIPPER_OPS_HEALTH_TIMEOUT": "1",
    }
    (workspace / ".klipper-ops.env").write_text(
        "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items())
    )
    config = load_config(workspace)
    ops = KlipperOperations(config, LocalHostTransport(config))
    try:
        yield ops, remote, state, host
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def candidate(ops, content="[printer]\nmax_velocity: 200\n"):
    ops.pull_config()
    (ops.config.project_root / "printer_data/config/printer.cfg").write_text(content)
    return ops.prepare_config_apply()


def test_real_worker_prepare_apply_backup_and_restore(printer):
    ops, remote, _state, host = printer
    prepared = candidate(ops)
    assert prepared["counts"] == {"added": 0, "modified": 1, "deleted": 0}
    backup = Path(prepared["backup_path"])
    assert "100" in (backup / "printer.cfg").read_text()
    result = ops.apply_config(prepared["plan_hash"], True)
    assert result["health"]["klippy_state"] == "ready"
    assert "200" in (remote / "printer.cfg").read_text()
    assert (remote / ".git/HEAD").read_text() == "ref: refs/heads/main\n"
    assert (host / "restart-count").read_text() == "1"
    ops.restore_backup(prepared["backup_id"], prepared["backup_id"])
    assert "100" in (remote / "printer.cfg").read_text()
    assert (remote / ".git/HEAD").exists()


def test_active_print_blocks_cli_equivalent_apply_and_restart(printer):
    ops, remote, state, host = printer
    prepared = candidate(ops)
    state["print"] = "printing"
    with pytest.raises(PrinterCommandError, match="printing"):
        ops.apply_config(prepared["plan_hash"], True, allow_unknown_print_state=True)
    with pytest.raises(PrinterCommandError, match="printing"):
        ops.restart_service("klipper", True, True)
    assert "100" in (remote / "printer.cfg").read_text()
    assert not (host / "restart-count").exists()


def test_systemd_active_with_klipper_error_rolls_back(printer):
    ops, remote, _state, host = printer
    prepared = candidate(ops, "[printer]\n# bad runtime setting\n")
    with pytest.raises(PrinterCommandError, match="previous config restored"):
        ops.apply_config(prepared["plan_hash"], True)
    assert "100" in (remote / "printer.cfg").read_text()
    assert (remote / ".git/HEAD").exists()
    assert (host / "restart-count").read_text() == "2"


def test_unknown_print_state_requires_override(printer):
    ops, _remote, state, _host = printer
    state["unavailable"] = True
    with pytest.raises(PrinterCommandError, match="unknown"):
        ops.restart_service("nginx", True)
    result = ops.restart_service("nginx", True, True)
    assert result["health"]["state"] == "active"


def test_remote_drift_stops_apply_under_remote_lock(printer):
    ops, remote, _state, host = printer
    prepared = candidate(ops)
    (remote / "new.cfg").write_text("[new]\n")
    with pytest.raises(PrinterCommandError, match="remote config changed"):
        ops.apply_config(prepared["plan_hash"], True)
    assert not (host / "restart-count").exists()


def test_staged_drift_stops_apply(printer):
    ops, remote, _state, _host = printer
    prepared = candidate(ops)
    record = json.loads(
        (
            ops.config.project_root / ".klipper-ops/plans" / (prepared["plan_hash"] + ".json")
        ).read_text()
    )
    stage = remote.parent / (".klipper-ops-stage-" + record["plan"]["token"])
    (stage / "printer.cfg").write_text("[different]\n")
    with pytest.raises(PrinterCommandError, match="staged config changed"):
        ops.apply_config(prepared["plan_hash"], True)


def test_pull_removes_deleted_files_but_preserves_local_edits(printer):
    ops, remote, _state, _host = printer
    (remote / "remove-me.cfg").write_text("[old]\n")
    ops.pull_config()
    local = ops.config.project_root / "printer_data/config"
    (remote / "remove-me.cfg").unlink()
    ops.pull_config()
    assert not (local / "remove-me.cfg").exists()
    (local / "printer.cfg").write_text("[local]\n")
    with pytest.raises(ConfigError, match="local mirror has edits"):
        ops.pull_config()
    assert (local / "printer.cfg").read_text() == "[local]\n"
    ops.pull_config(overwrite=True)
    assert "100" in (local / "printer.cfg").read_text()


@pytest.mark.parametrize(
    "target", [".", ".git", ".klipper-ops", "scripts", "printer_data", "backups"]
)
def test_pull_cannot_delete_workspace_or_internal_directories(printer, target):
    ops, _remote, _state, _host = printer
    with pytest.raises(ConfigError):
        ops.pull_config(target)
    assert ops.config.project_root.is_dir()


def test_absolute_remote_symlink_survives_backup_pull_apply(printer):
    ops, remote, _state, host = printer
    external = host / "module.cfg"
    external.write_text("[external]\n")
    (remote / "module.cfg").symlink_to(external)
    prepared = candidate(ops)
    assert (Path(prepared["backup_path"]) / "module.cfg").readlink() == external
    ops.apply_config(prepared["plan_hash"], True)
    assert (remote / "module.cfg").readlink() == external
    assert external.read_text() == "[external]\n"


def test_plan_integrity_identity_and_reuse(printer):
    ops, _remote, _state, _host = printer
    prepared = candidate(ops)
    other = replace(ops.config, user="another-user")
    with pytest.raises(ConfigError, match="another printer"):
        KlipperOperations(other, ops.transport).apply_config(prepared["plan_hash"], True)
    ops.apply_config(prepared["plan_hash"], True)
    with pytest.raises(ConfigError, match="used"):
        ops.apply_config(prepared["plan_hash"], True)


def test_expired_plan_can_be_discarded(printer, monkeypatch):
    ops, remote, _state, _host = printer
    prepared = candidate(ops)
    monkeypatch.setattr("klipper_ops_mcp.operations.time.time", lambda: prepared["expires_at"] + 1)
    with pytest.raises(ConfigError, match="expired"):
        ops.apply_config(prepared["plan_hash"], True)
    ops.discard_config_apply(prepared["plan_hash"])
    assert not list(remote.parent.glob(".klipper-ops-stage-*"))


def test_interrupted_transaction_can_restore_old_tree(printer):
    ops, remote, _state, _host = printer
    token = "a" * 64
    rollback = remote.parent / (".klipper-ops-rollback-" + token)
    stage = remote.parent / (".klipper-ops-stage-" + token)
    state_dir = remote.parent / (
        ".klipper-ops-" + __import__("hashlib").sha256(str(remote).encode()).hexdigest()[:16]
    )
    state_dir.mkdir()
    os.rename(remote, rollback)
    stage.mkdir()
    (state_dir / "transaction.json").write_text(
        json.dumps(
            {
                "token": token,
                "target": str(remote),
                "rollback": str(rollback),
                "stage": str(stage),
                "phase": "swapping",
            }
        )
    )
    result = ops.recover_config(True)
    assert result["recovered"]
    assert "100" in (remote / "printer.cfg").read_text()
    assert (remote / ".git/HEAD").exists()


def test_remote_lock_rejects_concurrent_mutation(printer):
    ops, remote, _state, _host = printer
    token = "b" * 64
    state_dir = remote.parent / (
        ".klipper-ops-" + __import__("hashlib").sha256(str(remote).encode()).hexdigest()[:16]
    )
    state_dir.mkdir()
    with (state_dir / "lock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(PrinterCommandError, match="remote lock"):
            ops.transport.run("discard", token=token)


def test_skill_launcher_uses_separate_mcp_cli_and_its_write_gates(printer, tmp_path):
    ops, remote, state, host = printer
    skill = Path(__file__).resolve().parents[3] / "skills/klipper-ops"
    installed = tmp_path / "installed-skill"
    shutil.copytree(skill, installed, ignore=shutil.ignore_patterns("__pycache__"))
    # The skill launcher contains no runtime; it delegates to the separately installed CLI.
    entry = [sys.executable, "-S", str(installed / "scripts/ops.py")]
    env = {**os.environ, "KLIPPER_OPS_CLI": str(Path(sys.executable).parent / "klipper-ops")}
    version = subprocess.run(
        entry + ["--version"], env=env, capture_output=True, text=True, check=True
    )
    assert version.stdout.strip() == "0.4.0"
    fake_ssh = tmp_path / "bin/ssh"
    fake_ssh.write_text(
        "#!" + sys.executable + "\nimport subprocess,sys\n"
        "raise SystemExit(subprocess.call(sys.argv[-1],shell=True))\n"
    )
    fake_ssh.chmod(0o755)
    values = {
        "PRINTER_HOST": ops.config.host,
        "PRINTER_USER": ops.config.user,
        "PRINTER_REMOTE_HOME": str(host),
        "PRINTER_REMOTE_CONFIG_DIR": str(remote),
        "PRINTER_KLIPPER_CHECK_SCRIPT": ops.config.check_script,
        "PRINTER_MOONRAKER_URL": ops.config.moonraker_url,
        "KLIPPER_OPS_HEALTH_TIMEOUT": "1",
    }
    (ops.config.project_root / ".klipper-ops.env").write_text(
        "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items())
    )
    env["KLIPPER_OPS_PROJECT_ROOT"] = str(ops.config.project_root)
    subprocess.run(entry + ["pull"], env=env, capture_output=True, check=True)
    (ops.config.project_root / "printer_data/config/printer.cfg").write_text(
        "[printer]\nmax_velocity: 300\n"
    )
    prepared = json.loads(
        subprocess.run(
            entry + ["prepare"], env=env, capture_output=True, text=True, check=True
        ).stdout
    )
    state["print"] = "paused"
    result = subprocess.run(
        entry + ["apply", "--plan", prepared["plan_hash"], "--yes"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "paused" in result.stderr
    assert "100" in (remote / "printer.cfg").read_text()


def test_actual_mcp_protocol_executes_reviewed_apply(printer):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    ops, remote, _state, _host = printer

    async def exercise():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "klipper_ops_mcp"],
            env={**os.environ, "KLIPPER_OPS_PROJECT_ROOT": str(ops.config.project_root)},
        )
        async with (
            stdio_client(parameters) as streams,
            ClientSession(*streams) as session,
        ):
            await session.initialize()
            status = await session.call_tool("get_printer_status", {})
            assert not status.isError
            assert status.structuredContent["print"]["state"] == "standby"
            pulled = await session.call_tool("pull_config", {})
            assert not pulled.isError
            (ops.config.project_root / "printer_data/config/printer.cfg").write_text(
                "[printer]\nmax_velocity: 400\n"
            )
            prepared = await session.call_tool("prepare_config_apply", {})
            assert not prepared.isError
            assert "+max_velocity: 400" in prepared.structuredContent["patch"]
            plan_hash = prepared.structuredContent["plan_hash"]
            refused = await session.call_tool(
                "apply_config", {"plan_hash": plan_hash, "confirm": False}
            )
            assert refused.isError
            applied = await session.call_tool(
                "apply_config", {"plan_hash": plan_hash, "confirm": True}
            )
            assert not applied.isError
            assert applied.structuredContent["health"]["klippy_state"] == "ready"

    asyncio.run(exercise())
    assert "400" in (remote / "printer.cfg").read_text()


def test_default_validator_against_upstream_parser(printer, tmp_path):
    parser_path = os.environ.get("KLIPPER_OPS_TEST_CONFIGFILE")
    if not parser_path:
        pytest.skip("set KLIPPER_OPS_TEST_CONFIGFILE to test a downloaded upstream parser")
    ops, remote, _state, host = printer
    klippy = host / "klipper/klippy"
    klippy.mkdir(parents=True)
    shutil.copyfile(parser_path, klippy / "configfile.py")
    config = replace(ops.config, check_script="", klipper_dir=str(klippy.parent))
    operations = KlipperOperations(config, LocalHostTransport(config))
    operations.pull_config()
    source = config.project_root / "printer_data/config"
    (source / "printer.cfg").write_text("[include macros.cfg]\n[printer]\nmax_velocity: 100\n")
    (source / "macros.cfg").write_text("[gcode_macro TEST]\ngcode:\n  G4 P1\n")
    assert operations.validate_config()["scope"] == "syntax-and-includes"
    # An absolute live-root include must resolve to the new staged file, not the old tree.
    (source / "printer.cfg").write_text(f"[include {remote}/macros.cfg]\n[printer]\n")
    (source / "macros.cfg").write_text("this is invalid syntax\n")
    with pytest.raises(PrinterCommandError, match="section headers"):
        operations.validate_config()
    assert not list(remote.parent.glob(".klipper-ops-stage-*"))


@pytest.mark.parametrize("member_name", ["../escape", "/escape"])
def test_archive_traversal_is_rejected(tmp_path, member_name):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        info = tarfile.TarInfo(member_name)
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="unsafe path"):
        extract_archive(payload.getvalue(), tmp_path / "extract")


def test_archive_cannot_write_through_absolute_or_relative_symlinks(tmp_path):
    for target in ("../outside", str(tmp_path / "outside")):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as archive:
            link = tarfile.TarInfo("link")
            link.type = tarfile.SYMTYPE
            link.linkname = target
            archive.addfile(link)
            child = tarfile.TarInfo("link/child")
            child.size = 1
            archive.addfile(child, io.BytesIO(b"x"))
        with pytest.raises(ValueError, match="traverses an archived symlink"):
            extract_archive(payload.getvalue(), tmp_path / "extract")
    assert not (tmp_path / "outside").exists()


def test_fingerprint_ignores_git_and_macos_metadata(tmp_path):
    (tmp_path / "printer.cfg").write_text("[printer]\n")
    initial = fingerprint(manifest(tmp_path))
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/HEAD").write_text("private metadata")
    (tmp_path / "._printer.cfg").write_text("macOS")
    assert fingerprint(manifest(tmp_path)) == initial
    restored = tmp_path.parent / (tmp_path.name + "-restored")
    extract_archive(create_archive(tmp_path), restored)
    assert not (restored / ".git").exists()
    assert fingerprint(manifest(restored)) == initial
    shutil.rmtree(restored)
