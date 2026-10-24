"""libVLC wrapper: the only module that imports ``vlc``."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal


class VlcEngine(QObject):
    """Thin wrapper around a libVLC instance and media player."""

    end_reached = Signal()
    playback_error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        import vlc  # imported late so the bootstrap can set DLL paths first

        self._vlc = vlc
        self._instance = vlc.Instance("--no-video-title-show", "--quiet")
        if self._instance is None:
            raise RuntimeError("Could not create a libVLC instance.")
        self._player = self._instance.media_player_new()
        self._media = None
        self._volume = 100

        events = self._player.event_manager()
        events.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_end_reached)
        events.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_error)
        events.event_attach(vlc.EventType.MediaPlayerPlaying, self._on_playing)

    # -- video output -----------------------------------------------------

    def attach_widget(self, widget) -> None:
        """Embed libVLC's video output into a native Qt widget."""
        handle = int(widget.winId())
        if sys.platform.startswith("win"):
            self._player.set_hwnd(handle)
        elif sys.platform == "darwin":
            self._player.set_nsobject(handle)
        else:
            self._player.set_xwindow(handle)

    # -- playback ---------------------------------------------------------

    def play(self, path: Path) -> None:
        self._media = self._instance.media_new(str(path))
        self._player.set_media(self._media)
        self._player.play()

    def stop(self) -> None:
        self._player.stop()

    def toggle_pause(self) -> None:
        state = self._player.get_state()
        if state == self._vlc.State.Playing:
            self._player.set_pause(1)
        elif state == self._vlc.State.Paused:
            self._player.set_pause(0)

    def is_playing(self) -> bool:
        return bool(self._player.is_playing())

    def is_ended(self) -> bool:
        return self._player.get_state() == self._vlc.State.Ended

    def has_media(self) -> bool:
        return self._player.get_media() is not None

    # -- state ------------------------------------------------------------

    def time_ms(self) -> int:
        return max(0, self._player.get_time())

    def length_ms(self) -> int:
        return max(0, self._player.get_length())

    def set_position(self, fraction: float) -> None:
        self._player.set_position(max(0.0, min(1.0, fraction)))

    def seek_relative(self, delta_ms: int) -> None:
        position = self._player.get_time()
        if position < 0:
            return
        target = max(0, position + delta_ms)
        length = self.length_ms()
        if length:
            target = min(target, length - 1000)
        self._player.set_time(target)

    def set_time(self, milliseconds: int) -> None:
        self._player.set_time(max(0, int(milliseconds)))

    # -- audio ------------------------------------------------------------

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, int(volume)))
        self._player.audio_set_volume(self._volume)

    def volume(self) -> int:
        return max(0, self._player.audio_get_volume())

    # -- events (fired on libVLC threads; Qt queues them on the main thread)

    def _on_playing(self, _event) -> None:
        self._player.audio_set_volume(self._volume)

    def _on_end_reached(self, _event) -> None:
        self.end_reached.emit()

    def _on_error(self, _event) -> None:
        self.playback_error.emit("VLC could not play this file.")

    # -- teardown ---------------------------------------------------------

    def shutdown(self) -> None:
        try:
            self._player.stop()
        finally:
            self._player.release()
            self._instance.release()
