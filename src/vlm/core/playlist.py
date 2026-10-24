"""Folder playlist logic. Pure Python: no Qt, no VLC imports."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".3gp",
        ".avi",
        ".flv",
        ".m2ts",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".mts",
        ".ogv",
        ".ts",
        ".webm",
        ".wmv",
    }
)

_NUMBER_RE = re.compile(r"(\d+)")
_FILE_ATTRIBUTE_HIDDEN = 0x2


def natural_key(text: str) -> tuple[tuple[int, object], ...]:
    """Sort key that compares embedded numbers numerically ('Ep 2' < 'Ep 10')."""
    key: list[tuple[int, object]] = []
    for position, part in enumerate(_NUMBER_RE.split(text.casefold())):
        if position % 2:  # captured digits
            key.append((1, int(part)))
        elif part:
            key.append((0, part))
    return tuple(key)


def is_hidden(path: Path) -> bool:
    if path.name.startswith("."):
        return True
    if os.name == "nt":
        try:
            attributes = path.stat().st_file_attributes
        except (OSError, AttributeError):
            return False
        return bool(attributes & _FILE_ATTRIBUTE_HIDDEN)
    return False


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def list_videos(folder: Path) -> list[Path]:
    """Return playable video files in *folder*, naturally sorted by name."""
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    videos = [path for path in entries if path.is_file() and is_video(path) and not is_hidden(path)]
    videos.sort(key=lambda path: natural_key(path.name))
    return videos


@dataclass
class FolderPlaylist:
    """Ordered list of videos from one folder, with a current index."""

    files: list[Path] = field(default_factory=list)
    index: int = 0

    @classmethod
    def from_folder(cls, folder: Path) -> FolderPlaylist:
        return cls(list_videos(Path(folder)))

    @classmethod
    def open_file(cls, path: Path) -> FolderPlaylist:
        """Load the file's folder, starting at *path* (even if it is not a known video)."""
        path = Path(path)
        files = list_videos(path.parent)
        if path not in files:
            files.append(path)
            files.sort(key=lambda item: natural_key(item.name))
        return cls(files, files.index(path))

    def __bool__(self) -> bool:
        return bool(self.files)

    @property
    def current(self) -> Path | None:
        if 0 <= self.index < len(self.files):
            return self.files[self.index]
        return None

    @property
    def has_previous(self) -> bool:
        return self.index > 0

    @property
    def has_next(self) -> bool:
        return self.index + 1 < len(self.files)

    @property
    def position(self) -> int:
        return self.index + 1 if self.files else 0

    @property
    def count(self) -> int:
        return len(self.files)

    def select(self, index: int) -> bool:
        if 0 <= index < len(self.files):
            self.index = index
            return True
        return False

    def select_path(self, path: Path) -> bool:
        """Make *path* current if it is in the playlist."""
        target = os.path.normcase(str(Path(path)))
        for position, candidate in enumerate(self.files):
            if os.path.normcase(str(candidate)) == target:
                self.index = position
                return True
        return False

    def next(self) -> bool:
        if not self.has_next:
            return False
        self.index += 1
        return True

    def previous(self) -> bool:
        if not self.has_previous:
            return False
        self.index -= 1
        return True

    def remove_current(self) -> Path | None:
        """Remove the current file; the following item takes its index."""
        if self.current is None:
            return None
        removed = self.files.pop(self.index)
        if self.index >= len(self.files):
            self.index = max(0, len(self.files) - 1)
        return removed
