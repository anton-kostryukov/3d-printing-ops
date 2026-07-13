from __future__ import annotations

from pathlib import Path

import pytest

from klipper_ops_mcp.config import ENV_KEYS, ConfigError, load_config, parse_env_file


def clear_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS | {"KLIPPER_OPS_PROJECT_ROOT"}:
        monkeypatch.delenv(key, raising=False)


def test_env_files_are_parsed_as_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_env(monkeypatch)
    marker = tmp_path / "executed"
    (tmp_path / ".klipper-ops.env").write_text(
        f"PRINTER_HOST=$(touch${{IFS}}{marker})\n", encoding="utf-8"
    )

    with pytest.raises(ConfigError):
        load_config(tmp_path)

    assert not marker.exists()


def test_process_environment_overrides_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_config_env(monkeypatch)
    (tmp_path / ".env").write_text("PRINTER_HOST=file-host\n", encoding="utf-8")
    (tmp_path / ".klipper-ops.local.env").write_text(
        'PRINTER_HOST="local-host"\nPRINTER_SERVICES="klipper moonraker"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PRINTER_HOST", "env-host")

    config = load_config(tmp_path)

    assert config.host == "env-host"
    assert config.services == ("klipper", "moonraker")


def test_unknown_dotenv_keys_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("APP_SETTING=$(not-executed)\nPRINTER_HOST=printer.local\n", encoding="utf-8")

    assert parse_env_file(path) == {"PRINTER_HOST": "printer.local"}


def test_workspace_paths_cannot_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_env(monkeypatch)
    monkeypatch.setenv("PRINTER_HOST", "printer.local")
    config = load_config(tmp_path)

    with pytest.raises(ConfigError):
        config.resolve_workspace_path("../another-project")


def test_service_must_be_allowlisted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_env(monkeypatch)
    monkeypatch.setenv("PRINTER_HOST", "printer.local")
    monkeypatch.setenv("PRINTER_SERVICES", "klipper moonraker")
    config = load_config(tmp_path)

    assert config.require_service("klipper") == "klipper"
    with pytest.raises(ConfigError):
        config.require_service("ssh")


def test_printer_name_cannot_escape_backup_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_config_env(monkeypatch)
    monkeypatch.setenv("PRINTER_HOST", "printer.local")
    monkeypatch.setenv("PRINTER_NAME", "../outside")

    with pytest.raises(ConfigError, match="safe path component"):
        load_config(tmp_path)
