from __future__ import annotations

from pathlib import Path

from vlm.core.playlist import FolderPlaylist, list_videos


def _touch(folder: Path, name: str) -> Path:
    path = folder / name
    path.write_bytes(b"x")
    return path


def test_list_videos_filters_and_sorts(tmp_path: Path) -> None:
    for name in ["b 10.mp4", "a 2.mkv", "notes.txt", ".hidden.mp4", "c.AVI"]:
        _touch(tmp_path, name)
    (tmp_path / "sub").mkdir()
    _touch(tmp_path / "sub", "inner.mp4")

    assert [path.name for path in list_videos(tmp_path)] == ["a 2.mkv", "b 10.mp4", "c.AVI"]


def test_open_file_selects_that_file(tmp_path: Path) -> None:
    _touch(tmp_path, "show 1.mp4")
    second = _touch(tmp_path, "show 2.mp4")

    playlist = FolderPlaylist.open_file(second)

    assert playlist.current == second
    assert playlist.position == 2
    assert playlist.count == 2
    assert playlist.has_previous
    assert not playlist.has_next


def test_open_file_includes_unknown_extension(tmp_path: Path) -> None:
    _touch(tmp_path, "show 1.mp4")
    odd = _touch(tmp_path, "notes.txt")

    playlist = FolderPlaylist.open_file(odd)

    assert odd in playlist.files
    assert playlist.current == odd


def test_next_and_previous_stop_at_bounds(tmp_path: Path) -> None:
    for index in range(3):
        _touch(tmp_path, f"v{index}.mp4")

    playlist = FolderPlaylist.from_folder(tmp_path)
    assert playlist.position == 1
    assert not playlist.previous()

    assert playlist.next()
    assert playlist.next()
    assert not playlist.next()
    assert playlist.position == 3


def test_remove_current_advances(tmp_path: Path) -> None:
    first = _touch(tmp_path, "v0.mp4")
    second = _touch(tmp_path, "v1.mp4")
    third = _touch(tmp_path, "v2.mp4")

    playlist = FolderPlaylist.from_folder(tmp_path)
    playlist.select(1)

    assert playlist.remove_current() == second
    assert playlist.current == third
    assert playlist.count == 2

    assert playlist.remove_current() == third
    assert playlist.current == first

    assert playlist.remove_current() == first
    assert playlist.current is None
    assert not playlist


def test_empty_folder_is_false(tmp_path: Path) -> None:
    assert not FolderPlaylist.from_folder(tmp_path)
