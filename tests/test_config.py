from __future__ import annotations

from pathlib import Path

from vlm.core.config import Config


def test_defaults_and_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = Config(path)
    assert config.volume == 100
    assert config.auto_advance is True
    assert config.last_folder is None

    config.volume = 42
    config.auto_advance = False
    config.last_folder = "C:/videos"
    config.save()

    loaded = Config(path)
    assert loaded.volume == 42
    assert loaded.auto_advance is False
    assert loaded.last_folder == "C:/videos"


def test_invalid_file_uses_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("not json", encoding="utf-8")
    assert Config(path).volume == 100


def test_volume_is_clamped(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"volume": 999}', encoding="utf-8")
    assert Config(path).volume == 100
