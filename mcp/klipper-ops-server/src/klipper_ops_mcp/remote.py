"""Fixed remote worker, sent over SSH; requires only Python 3.8+ on the host."""

import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from klipper_ops_files import (
    MAX_ARCHIVE_BYTES,
    create_archive,
    extract_archive,
    fingerprint,
    manifest,
)


def atomic_json(path, value):
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Worker:
    def __init__(self, request):
        self.request = request
        self.root = Path(request["config_dir"])
        if not self.root.is_absolute() or self.root.parent == self.root:
            raise ValueError("config root must be an absolute non-root directory")
        if ".." in self.root.parts or str(self.root) != request["config_dir"]:
            raise ValueError("config root must be normalized")
        self.key = hashlib.sha256(str(self.root).encode()).hexdigest()[:16]
        self.state = self.root.parent / (".klipper-ops-" + self.key)

    def json_request(self, path):
        url = self.request["moonraker_url"].rstrip("/") + path
        # Do not send local printer traffic through host HTTP_PROXY settings.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=3) as response:
            payload = response.read(1024 * 1024 + 1)
            if len(payload) > 1024 * 1024:
                raise ValueError("Moonraker response exceeds 1 MiB")
        return json.loads(payload)["result"]

    def print_state(self):
        try:
            result = self.json_request("/printer/objects/query?print_stats&webhooks")
            objects = result["status"]
            stats = objects["print_stats"]
            state = stats.get("state")
            if state not in {"standby", "printing", "paused", "complete", "cancelled", "error"}:
                raise ValueError("unrecognized print state")
            return {
                "state": state,
                "filename": str(stats.get("filename", ""))[:512],
                "message": str(stats.get("message", ""))[:2000],
                "klippy_state": objects.get("webhooks", {}).get("state", "unknown"),
            }
        except Exception as exc:
            return {"state": "unknown", "error": str(exc)[:400]}

    def require_idle(self):
        state = self.print_state()
        if state["state"] in {"printing", "paused"}:
            raise ValueError("write refused while printer state is " + state["state"])
        if state["state"] == "unknown" and not self.request.get("allow_unknown_print_state", False):
            raise ValueError("printer state is unknown; explicit recovery override required")
        return state

    def command(self, command, timeout=20):
        result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
        return (
            result.returncode,
            result.stdout.decode(errors="replace")[-16000:],
            result.stderr.decode(errors="replace")[-2000:],
        )

    def service(self, verb, service):
        if service not in self.request["services"] or not re.fullmatch(
            r"[A-Za-z0-9_][A-Za-z0-9@_.-]*", service
        ):
            raise ValueError("service is not allowlisted")
        command = ["systemctl"]
        if self.request["scope"] == "user":
            command.append("--user")
        elif verb == "restart" and os.geteuid() != 0:
            command = ["sudo", "-n"] + command
        command += [verb, "--", service]
        code, output, error = self.command(command, timeout=30)
        if verb == "restart" and code:
            raise ValueError("service restart failed: " + error)
        return code, output

    def wait_healthy(self, service, require_klippy=True):
        deadline = time.monotonic() + self.request["health_timeout"]
        last = "service is inactive"
        while time.monotonic() < deadline:
            code, _ = self.service("is-active", service)
            if code == 0:
                if not require_klippy:
                    return {"service": service, "state": "active"}
                try:
                    info = self.json_request("/printer/info")
                    last = str(info.get("state_message", info.get("state", "unknown")))[:1000]
                    if info.get("state") == "ready":
                        return {"service": service, "state": "active", "klippy_state": "ready"}
                except Exception as exc:
                    last = str(exc)[:1000]
            time.sleep(0.2)
        raise ValueError("printer did not become ready: " + last)

    @contextlib.contextmanager
    def locked(self):
        if self.state.is_symlink():
            raise ValueError("remote state directory must not be a symlink")
        self.state.mkdir(mode=0o700, exist_ok=True)
        if self.state.stat().st_uid != os.getuid():
            raise ValueError("remote state directory has another owner")
        self.state.chmod(0o700)
        lock = self.state / "lock"
        descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("another printer operation holds the remote lock") from exc
            yield
        finally:
            os.close(descriptor)

    def stage(self):
        token = self.request["token"]
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            raise ValueError("invalid staging token")
        return self.root.parent / (".klipper-ops-stage-" + token)

    def validate(self, stage):
        config = stage / "printer.cfg"
        if not config.is_file() or config.is_symlink():
            raise ValueError("candidate must contain a regular printer.cfg")
        checker = self.request.get("check_script", "")
        if checker:
            code, output, error = self.command(["python3", checker, str(config)], timeout=60)
            return {
                "valid": code == 0,
                "scope": "custom-checker",
                "exit_code": code,
                "output": (output + error)[-4000:],
            }
        module_path = Path(self.request["klipper_dir"]) / "klippy/configfile.py"
        if not module_path.is_file():
            raise ValueError("Klipper config parser not found; set PRINTER_KLIPPER_DIR")
        spec = importlib.util.spec_from_file_location("klipper_configfile", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        live_root = self.root

        class CandidateReader(module.ConfigFileReader):
            def _resolve_include(reader, filename, include, parser, visited):
                # A live-root absolute include must validate the staged candidate.
                if os.path.isabs(include):
                    try:
                        relative = Path(include).relative_to(live_root)
                        include = str(stage / relative)
                    except ValueError:
                        pass
                return super()._resolve_include(filename, include, parser, visited)

        reader = CandidateReader()
        data = reader.read_config_file(str(config))
        parsed = reader.build_fileconfig_with_includes(data, str(config))
        # Parse SAVE_CONFIG data without starting Klippy or opening an MCU serial port.
        autosave = "\n".join(
            line[4:]
            for line in data.splitlines()
            if line.startswith("#*# ")
            and not line.startswith("#*# <")
            and not line.startswith("#*# DO NOT")
        )
        if autosave.strip():
            reader.append_fileconfig(parsed, autosave, "*AUTOSAVE*")
        return {
            "valid": True,
            "scope": "syntax-and-includes",
            "exit_code": 0,
            "output": (
                "Klipper parser accepted syntax and includes; "
                "runtime readiness is checked after restart."
            ),
        }

    def check_links(self, stage):
        current = {entry["path"]: entry for entry in manifest(self.root)["files"]}
        for entry in manifest(stage)["files"]:
            if entry["type"] != "symlink":
                continue
            target = entry["target"]
            try:
                (stage / entry["path"]).resolve().relative_to(stage)
            except ValueError:
                if current.get(entry["path"]) != entry:
                    raise ValueError(
                        "new or changed external symlink is not allowed: " + entry["path"]
                    ) from None
            # Absolute references into live config would validate old files.
            if os.path.isabs(target):
                try:
                    Path(target).relative_to(self.root)
                except ValueError:
                    continue
                raise ValueError(
                    "use a relative symlink for a link into the config tree: " + entry["path"]
                )

    def upload(self):
        stage = self.stage()
        if stage.exists() or stage.is_symlink():
            raise ValueError("staging token already exists")
        payload = sys.stdin.buffer.read(MAX_ARCHIVE_BYTES + 1)
        stage.mkdir(mode=0o700)
        try:
            extract_archive(payload, stage)
            self.check_links(stage)
            result = self.validate(stage)
            if not result["valid"]:
                raise ValueError("candidate validation failed: " + result["output"])
            snapshot = manifest(stage)
            receipt = {
                "fingerprint": fingerprint(snapshot),
                "expires_at": int(time.time()) + self.request["plan_ttl"],
            }
            atomic_json(self.state / (self.request["token"] + ".json"), receipt)
            return {
                "validation": result,
                "fingerprint": receipt["fingerprint"],
                "expires_at": receipt["expires_at"],
            }
        except BaseException:
            shutil.rmtree(stage)
            raise

    def remove_stage(self):
        stage = self.stage()
        journal_path = self.state / "transaction.json"
        if journal_path.is_file():
            journal = json.loads(journal_path.read_text())
            if journal.get("token") == self.request["token"] and journal.get("phase") in {
                "swapping",
                "checking",
                "recovery-required",
            }:
                raise ValueError("recover the interrupted transaction before discarding its stage")
        if stage.is_symlink():
            raise ValueError("stage must not be a symlink")
        if stage.exists():
            shutil.rmtree(stage)
        receipt = self.state / (self.request["token"] + ".json")
        receipt.unlink(missing_ok=True)
        return {"discarded": True}

    def apply(self):
        stage = self.stage()
        token = self.request["token"]
        receipt_path = self.state / (token + ".json")
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("used") or receipt["expires_at"] <= time.time():
            raise ValueError("remote apply plan is used or expired")
        if self.root.is_symlink() or not self.root.is_dir() or stage.is_symlink():
            raise ValueError("config and staging roots must be real directories")
        if fingerprint(manifest(self.root)) != self.request["expected_remote"]:
            raise ValueError("remote config changed after preparation")
        expected = self.request["expected_local"]
        if fingerprint(manifest(stage)) != expected or receipt["fingerprint"] != expected:
            raise ValueError("staged config changed after validation")
        self.check_links(stage)
        self.validate_or_raise(stage)
        state = self.require_idle()
        return self.swap(stage, receipt_path, receipt, state)

    def validate_or_raise(self, stage):
        result = self.validate(stage)
        if not result["valid"]:
            raise ValueError("staged validation failed: " + result["output"])

    def swap(self, stage, receipt_path, receipt, print_state):
        token = self.request["token"]
        service = self.request["service"]
        rollback = self.root.parent / (".klipper-ops-rollback-" + token)
        if rollback.exists() or rollback.is_symlink():
            raise ValueError("rollback path already exists")
        journal_path = self.state / "transaction.json"
        if journal_path.exists():
            previous = json.loads(journal_path.read_text())
            if previous.get("phase") in {"swapping", "checking", "recovery-required"}:
                raise ValueError("an interrupted transaction needs recovery: " + str(journal_path))
        journal = {
            "target": str(self.root),
            "stage": str(stage),
            "rollback": str(rollback),
            "phase": "swapping",
            "token": token,
        }
        atomic_json(journal_path, journal)
        moved = False
        installed = False
        preserved_git = False

        # Ensure TERM/HUP enter the same rollback path as an ordinary failure.
        def interrupted(signum, frame):
            raise RuntimeError(f"operation interrupted by signal {signum}")

        for signum in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(signum, interrupted)
        try:
            stage.chmod(self.root.stat().st_mode & 0o777)
            os.rename(self.root, rollback)
            moved = True
            if (rollback / ".git").exists() or (rollback / ".git").is_symlink():
                os.rename(rollback / ".git", stage / ".git")
                preserved_git = True
            os.rename(stage, self.root)
            installed = True
            journal["phase"] = "checking"
            atomic_json(journal_path, journal)
            self.service("restart", service)
            health = self.wait_healthy(service)
            receipt["used"] = True
            atomic_json(receipt_path, receipt)
            journal["phase"] = "applied"
            atomic_json(journal_path, journal)
            return {
                "applied": True,
                "health": health,
                "rollback_path": str(rollback),
                "print_state_before_apply": print_state,
            }
        except BaseException as original:
            recovery_error = ""
            try:
                if installed:
                    os.rename(self.root, stage)
                if preserved_git:
                    os.rename(stage / ".git", rollback / ".git")
                if moved:
                    os.rename(rollback, self.root)
                    self.service("restart", service)
                    self.wait_healthy(service)
                journal["phase"] = "rolled-back"
            except BaseException as recovery:
                recovery_error = f"; recovery failed: {recovery}; inspect {journal_path}"
                journal["phase"] = "recovery-required"
            atomic_json(journal_path, journal)
            raise ValueError(
                "apply failed: {}; previous config {}{}".format(
                    original,
                    "restored" if not recovery_error else "requires recovery",
                    recovery_error,
                )
            ) from original

    def recover(self):
        journal_path = self.state / "transaction.json"
        if not journal_path.is_file():
            raise ValueError("no interrupted transaction to recover")
        journal = json.loads(journal_path.read_text())
        token = journal.get("token", "")
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            raise ValueError("transaction journal has an invalid token")
        stage = self.root.parent / (".klipper-ops-stage-" + token)
        rollback = self.root.parent / (".klipper-ops-rollback-" + token)
        if (
            journal.get("target") != str(self.root)
            or journal.get("stage") != str(stage)
            or journal.get("rollback") != str(rollback)
        ):
            raise ValueError("transaction journal paths do not match this printer")
        if journal.get("phase") not in {"swapping", "checking", "recovery-required"}:
            raise ValueError(
                "transaction is not interrupted; use backup restore for a completed apply"
            )
        self.require_idle()
        if rollback.is_symlink() or self.root.is_symlink() or stage.is_symlink():
            raise ValueError("recovery directories must not be symlinks")
        if rollback.is_dir():
            if self.root.exists():
                failed = self.root.parent / (".klipper-ops-failed-" + token)
                if failed.exists():
                    raise ValueError("failed config path already exists")
                if (self.root / ".git").exists() or (self.root / ".git").is_symlink():
                    os.rename(self.root / ".git", rollback / ".git")
                os.rename(self.root, failed)
            elif (stage / ".git").exists() or (stage / ".git").is_symlink():
                os.rename(stage / ".git", rollback / ".git")
            os.rename(rollback, self.root)
        elif not self.root.is_dir():
            raise ValueError("neither live config nor rollback exists; manual recovery required")
        self.service("restart", self.request["klipper_service"])
        health = self.wait_healthy(self.request["klipper_service"])
        journal["phase"] = "rolled-back"
        atomic_json(journal_path, journal)
        return {"recovered": True, "health": health, "transaction_path": str(journal_path)}

    def dispatch(self):
        action = self.request["action"]
        if action == "state":
            return self.print_state()
        if action == "status":
            services = []
            for service in self.request["services"]:
                command = ["systemctl"]
                if self.request["scope"] == "user":
                    command.append("--user")
                command += [
                    "show",
                    "--no-pager",
                    "-p",
                    "Id,LoadState,ActiveState,SubState,MainPID,ExecMainStatus,NRestarts",
                    "--",
                    service,
                ]
                code, output, error = self.command(command)
                entry = {
                    "name": service,
                    **dict(line.split("=", 1) for line in output.splitlines() if "=" in line),
                }
                if code:
                    entry["error"] = error
                services.append(entry)
            journal_path = self.state / "transaction.json"
            transaction = json.loads(journal_path.read_text()) if journal_path.is_file() else None
            return {
                "remote_hostname": os.uname().nodename,
                "services": services,
                "print": self.print_state(),
                "config": {"state": "present" if self.root.is_dir() else "missing"},
                "transaction": transaction,
            }
        if action == "logs":
            service = self.request["service"]
            if service not in self.request["services"]:
                raise ValueError("service is not allowlisted")
            lines, minutes = self.request["lines"], self.request["minutes"]
            if not 1 <= lines <= 500 or not 1 <= minutes <= 1440:
                raise ValueError("invalid log bounds")
            command = ["journalctl"]
            if self.request["scope"] == "user":
                command.append("--user")
            command += [
                "-u",
                service,
                "--since",
                f"{minutes} minutes ago",
                "-n",
                str(lines),
                "--no-pager",
                "-o",
                "short-iso",
            ]
            code, output, error = self.command(command)
            if code:
                raise ValueError("journalctl failed: " + error)
            entries = [line[:2000] for line in output.splitlines()[-lines:]]
            return {
                "service": service,
                "lines": entries,
                "line_count": len(entries),
                "truncated": len(output) >= 16000,
            }
        if action in {"manifest", "archive"}:
            before = manifest(self.root)
            if action == "manifest":
                return before
            payload = create_archive(self.root, self.request.get("expanded", False))
            if fingerprint(before) != fingerprint(manifest(self.root)):
                raise ValueError("config changed during snapshot; retry")
            sys.stdout.buffer.write(payload)
            return None
        with self.locked():
            if action == "stage":
                return self.upload()
            if action == "discard":
                return self.remove_stage()
            if action == "apply":
                if self.request["service"] != self.request["klipper_service"]:
                    raise ValueError("apply must restart the configured Klipper service")
                return self.apply()
            if action == "recover":
                return self.recover()
            if action == "restart":
                state = self.require_idle()
                service = self.request["service"]
                self.service("restart", service)
                health = self.wait_healthy(service, service == self.request["klipper_service"])
                return {"service": service, "health": health, "print_state_before_restart": state}
        raise ValueError("unknown worker operation")


def main():
    request = json.loads(sys.argv[1])
    try:
        result = Worker(request).dispatch()
        if result is not None:
            print(json.dumps(result, separators=(",", ":")))
    except Exception as exc:
        print(str(exc)[:4000], file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
