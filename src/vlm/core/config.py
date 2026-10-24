"""Tiny JSON config store. Pure Python: no Qt imports."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "VideoLibraryManager"


def config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def _clamp_int(value: object, low: int, high: int, default: int) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


class Config:
    """Persisted user settings."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else config_dir() / "config.json"
        self.last_folder: str | None = None
        self.volume: int = 100
        self.auto_advance: bool = True
        self.geometry: str | None = None
        self.ratings: dict[str, int] = {}
        self.panel_visible: bool = False
        self.panel_width: int = 300
        self.panel_sort_column: int = 0  # 0 name, 1 size, 2 date, 3 rating
        self.panel_sort_order: int = 0  # 0 ascending, 1 descending
        self.overlay_controls: bool = False
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        folder = data.get("last_folder")
        self.last_folder = folder if isinstance(folder, str) else None
        self.volume = _clamp_int(data.get("volume"), 0, 100, 100)
        self.auto_advance = bool(data.get("auto_advance", True))
        geometry = data.get("geometry")
        self.geometry = geometry if isinstance(geometry, str) else None
        ratings = data.get("ratings")
        if isinstance(ratings, dict):
            cleaned: dict[str, int] = {}
            for key, value in ratings.items():
                if isinstance(key, str):
                    cleaned[key] = _clamp_int(value, 0, 5, 0)
            self.ratings = cleaned
        self.panel_visible = bool(data.get("panel_visible", False))
        self.panel_width = _clamp_int(data.get("panel_width"), 160, 1200, 300)
        self.panel_sort_column = _clamp_int(data.get("panel_sort_column"), 0, 3, 0)
        self.panel_sort_order = _clamp_int(data.get("panel_sort_order"), 0, 1, 0)
        self.overlay_controls = bool(data.get("overlay_controls", False))

    def save(self) -> None:
        data = {
            "last_folder": self.last_folder,
            "volume": self.volume,
            "auto_advance": self.auto_advance,
            "geometry": self.geometry,
            "ratings": self.ratings,
            "panel_visible": self.panel_visible,
            "panel_width": self.panel_width,
            "panel_sort_column": self.panel_sort_column,
            "panel_sort_order": self.panel_sort_order,
            "overlay_controls": self.overlay_controls,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def get_rating(self, path: Path | str) -> int:
        return _clamp_int(self.ratings.get(str(Path(path))), 0, 5, 0)

    def set_rating(self, path: Path | str, rating: int) -> None:
        self.ratings[str(Path(path))] = _clamp_int(rating, 0, 5, 0)
