"""Move files to the OS trash / Recycle Bin."""

from __future__ import annotations

from pathlib import Path

from send2trash import send2trash


def delete_to_trash(path: Path) -> None:
    """Move *path* to the Recycle Bin (Windows) or Trash (macOS/Linux).

    Raises OSError (including send2trash's TrashPermissionError) on failure.
    """
    send2trash(str(path))
