# Video Library Manager

Minimal local video player: open a video or folder, move through the folder with
Prev/Next, and delete the current video to the Recycle Bin. Windows-first;
the engine and UI layers are kept separate for a later port.

## Run

```powershell
python run.py
```

`run.py` checks prerequisites first and offers to install anything missing:

- Python 3.11+
- Python packages: PySide6, python-vlc, Send2Trash (prompts to `pip install`)
- VLC 3.x, 64-bit, matching Python (prompts to install via winget on Windows,
  or opens the VLC download page)

You can also install the project properly:

```powershell
python -m pip install -e ".[dev]"
vlm
```

## Controls

| Input | Action |
|---|---|
| `Space` | Play / pause |
| `Ctrl+Left` / `Ctrl+Right` | Previous / next video |
| `Left` / `Right` | Seek 10 seconds |
| `Del` | Delete current video (Recycle Bin) |
| `F` | Fullscreen |
| `Esc` | Leave fullscreen |
| `M` | Mute |

Opening a file loads its whole folder as the playlist. Auto-advance is on by
default (stop at the end of the folder). Drag-and-drop works for files and
folders.

## Layout

```
src/vlm/
  bootstrap.py   # prerequisite checks (stdlib only)
  core/          # pure Python: no Qt, no vlc imports
  video/         # libVLC wrapper
  ui/            # Qt widgets
```

## Requirements notes

- VLC must match Python's architecture (64-bit Python needs 64-bit VLC).
- The app sets `PYTHON_VLC_LIB_PATH` / `PYTHON_VLC_MODULE_PATH` from the
  detected VLC installation before importing `vlc`.
- On macOS, install VLC.app; on Linux, install the distro `vlc`/`libvlc`
  package. Those platforms are untested as of v0.1.

## Tests

```powershell
python -m pytest
```
