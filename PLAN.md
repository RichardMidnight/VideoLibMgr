# Video Library Manager — v0.1 plan

Windows-first. Python 3.11+ · PySide6 · libVLC 3.x · ffmpeg later.

## Goal

A local video player that opens a file or folder, plays through the folder with
Prev/Next, and deletes the current video to the Recycle Bin. UI modeled loosely
on Windows "Movies & TV": dark, video-first, minimal auto-hiding control bar.

## Stack

- **PySide6** — UI, native-window video embedding
- **python-vlc** — libVLC bindings (requires VLC 3.x installed, 64-bit to match Python)
- **send2trash** — Recycle Bin (later: macOS/Linux trash)
- **pytest**, **ruff** — tests and lint

## Structure

```
src/vlm/
  __main__.py        # entry point
  app.py             # QApplication bootstrap, dark palette
  core/              # pure Python: no Qt, no vlc imports
    playlist.py      # folder scan, natural sort, index, next/prev
    trash.py         # send2trash wrapper
    config.py        # last folder, volume
  video/
    engine.py        # the only module importing vlc
  ui/
    main_window.py   # layout, actions, overlay control bar
    video_view.py    # native-window QWidget libVLC renders into
tests/
  test_playlist.py
  test_natural_sort.py
```

Rule: `core/` stays UI- and VLC-free; `video/engine.py` is the only libVLC
surface; `ui/` is the only Qt surface. This is what makes a later port cheap.

## Behavior (v0.1)

1. **Open File** → playlist = parent folder, start at that file.
   **Open Folder** → playlist = folder, start at first. Drag-and-drop both.
2. **Playlist** = video-extension allowlist, natural sort (`Video 2` before
   `Video 10`), hidden files skipped.
3. **Transport**: Prev, Play/Pause, Next, seek bar, time, volume, Delete,
   Fullscreen.
4. **Auto-advance ON** by default: end of a file plays the next; stops at the
   end of the list.
5. **Delete**: confirm → `stop()` → send to Recycle Bin → remove from playlist →
   play the next item at that index (stop if empty). If trashing fails, show an
   error and keep the item.
6. **Keys**: `Space` play/pause · `Ctrl+←/→` prev/next · `←/→` seek ±10 s ·
   `Del` delete · `F`/`Esc` fullscreen.
7. **Persist**: last folder and volume via QSettings.

## UI (Movies & TV-ish)

- Dark palette; video fills the window.
- Top bar: `Open` menu plus `filename` and `3 of 17`.
- Control bar below the video: prev / play / next, seek + time, volume, delete,
  fullscreen. In fullscreen it auto-hides after 2.5 s and the cursor hides too.
  True overlay controls are postponed: libVLC's native video child window makes
  Qt overlays unreliable on Windows.
- Standard window frame in v0.1; custom chrome later.
- Delete lives in the control bar (confirmation dialog).

## Milestones

- **M0** — venv, deps, per-OS prerequisites README (Windows first)
- **M1** — embedding spike: one file plays inside a Qt window (risk gate)
- **M2** — playlist + Prev/Play/Next + seek/volume/time + keys
- **M3** — delete-to-Recycle-Bin + auto-advance
- **M4** — fullscreen auto-hide, drag-and-drop, settings persistence
- **M5** — unit tests for `core/`, README, tag v0.1

## Status (v0.1)

Implemented on Windows: M0–M5. `python run.py` prompts to install missing pip
packages and VLC (winget or download page). 13 unit tests pass; an end-to-end
smoke test covers open → play → auto-advance → previous → delete to Recycle Bin
→ playback continues. Next up: ffmpeg-based trim/cut/join.


## Risks

- libVLC-in-Qt embedding: HWND plumbing, resize/letterbox behavior, transient
  black frames. M1 proves it before feature work.
- VLC bitness must match Python; surface a clear startup error if libVLC is
  missing.
- Delete-during-auto-advance race: cancel pending "play next" on delete.

## Out of scope (v0.2+)

Series grouping/rename/delete, trim, cut, join, repair, thumbnails, database,
installers, macOS/Linux validation, custom window chrome.
