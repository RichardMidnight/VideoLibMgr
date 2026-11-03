"""Main window: video surface, transport controls and playlist actions."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPointF,
    QRunnable,
    QSettings,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QFont, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpacerItem,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyleOptionSlider,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.config import Config
from ..core.playlist import VIDEO_EXTENSIONS, FolderPlaylist, is_hidden, is_video
from ..core.trash import delete_to_trash
from ..video.engine import VlcEngine
from .video_view import VideoView

SEEK_RANGE = 1000
SEEK_STEP_MS = 10_000
TICK_MS = 250
HIDE_CONTROLS_MS = 2_500
TRASH_ATTEMPTS = 10
TRASH_RETRY_DELAY_S = 0.25


class _FileRow:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            stat = path.stat()
            self.size = int(stat.st_size)
            self.mtime = float(stat.st_mtime)
        except OSError:
            self.size = 0
            self.mtime = 0.0


class FileListModel(QAbstractTableModel):
    HEADERS: ClassVar[list[str]] = ["Name", "Size", "Date", "Rating"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[_FileRow] = []
        self._ratings: dict[str, int] = {}
        self._current: Path | None = None

    def set_folder(self, folder: Path) -> None:
        self.beginResetModel()
        try:
            entries = list(folder.iterdir())
        except OSError:
            entries = []
        rows: list[_FileRow] = []
        for entry in entries:
            if not entry.is_file() or is_hidden(entry) or not is_video(entry):
                continue
            rows.append(_FileRow(entry))
        rows.sort(key=lambda row: row.path.name.casefold())
        self._rows = rows
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._rows = []
        self._current = None
        self.endResetModel()

    def set_ratings(self, ratings: dict[str, int]) -> None:
        self._ratings = dict(ratings)
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 3),
                self.index(self.rowCount() - 1, 3),
                [Qt.ItemDataRole.DisplayRole],
            )

    def set_current(self, path: Path | None) -> None:
        self._current = Path(path) if path else None
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, 0),
                [Qt.ItemDataRole.FontRole, Qt.ItemDataRole.ForegroundRole],
            )

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return 4

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def path_at(self, row: int) -> Path | None:
        if 0 <= row < len(self._rows):
            return self._rows[row].path
        return None

    def index_for_path(self, path: Path) -> QModelIndex | None:
        target = os.path.normcase(str(Path(path)))
        for i, row in enumerate(self._rows):
            if os.path.normcase(str(row.path)) == target:
                return self.index(i, 0)
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        key = str(row.path)
        rating = _clamp_rating(self._ratings.get(key, 0))
        if index.column() == 0:
            if role == Qt.ItemDataRole.DisplayRole:
                return row.path.name
            if role == Qt.ItemDataRole.FontRole and self._current == row.path:
                font = QFont()
                font.setBold(True)
                return font
            if role == Qt.ItemDataRole.ForegroundRole and self._current == row.path:
                return QColor("#7db7ff")
            return None
        if index.column() == 1:
            if role == Qt.ItemDataRole.DisplayRole:
                return _format_size(row.size)
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return None
        if index.column() == 2:
            if role == Qt.ItemDataRole.DisplayRole:
                return _format_date(row.mtime)
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return None
        if index.column() == 3:
            if role == Qt.ItemDataRole.DisplayRole:
                return "★" * rating + "☆" * (5 - rating)
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignCenter)
            return None
        return None


class FileSortProxy(QSortFilterProxyModel):
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        model = self.sourceModel()
        if not isinstance(model, FileListModel):
            return super().lessThan(left, right)
        lrow = self.mapToSource(left).row()
        rrow = self.mapToSource(right).row()
        if not (0 <= lrow < len(model._rows) and 0 <= rrow < len(model._rows)):
            return super().lessThan(left, right)
        left_row = model._rows[lrow]
        right_row = model._rows[rrow]
        column = left.column()
        if column == 0:
            return left_row.path.name.casefold() < right_row.path.name.casefold()
        if column == 1:
            return left_row.size < right_row.size
        if column == 2:
            return left_row.mtime < right_row.mtime
        if column == 3:
            lr = _clamp_rating(model._ratings.get(str(left_row.path), 0))
            rr = _clamp_rating(model._ratings.get(str(right_row.path), 0))
            return lr < rr
        return left_row.path.name.casefold() < right_row.path.name.casefold()


def _clamp_rating(value: int) -> int:
    return max(0, min(5, int(value)))


def _format_size(size: int) -> str:
    if size <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(size)} B"


def _format_date(mtime: float) -> str:
    if mtime <= 0:
        return ""
    return time.strftime("%Y-%m-%d", time.localtime(mtime))


class ToggleSwitch(QCheckBox):
    """Checkbox rendered as a pill-style toggle switch (Movies & TV / Fluent style).

    Subclasses ``QCheckBox`` so all check semantics (``isChecked``, ``toggled``,
    keyboard shortcuts) are unchanged. The track is a stylesheet-styled
    indicator; the knob is painted in ``paintEvent`` because the Qt style-sheet
    engine has no reliable CSS gradient support for a circular knob.
    """

    KNOB_PADDING = 3
    _TRACK = """
    QCheckBox {
        spacing: 12px;
    }
    QCheckBox::indicator {
        width: 40px;
        height: 22px;
        border-radius: 11px;
    }
    QCheckBox::indicator:unchecked {
        background-color: #3a3a3a;
    }
    QCheckBox::indicator:checked {
        background-color: #4c8dff;
    }
    """

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setStyleSheet(self._TRACK)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        # The track is styled at 40x22 and this widget always carries the
        # indicator only (no text), so the indicator occupies the widget's
        # left 40x22 px, vertically centred.
        width, height = 40, 22
        if self.width() <= 0 or self.height() <= 0:
            return
        y = max(0, (self.height() - height) // 2)
        radius = max(2, min(width, height) // 2 - self.KNOB_PADDING)
        cy = y + height // 2
        if self.isChecked():
            cx = width - self.KNOB_PADDING - radius
            color = QColor("#ffffff")
        else:
            cx = self.KNOB_PADDING + radius
            color = QColor("#cfcfcf")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
        painter.end()


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        self.overlay_checkbox = ToggleSwitch("")
        self.overlay_checkbox.setToolTip(
            "Show the control bar floating on top of the video (Movies & TV style) "
            "instead of below it."
        )
        self.overlay_checkbox.setChecked(bool(self.config.overlay_controls))
        form.addRow("Overlay control bar on video (Movies & TV style)", self.overlay_checkbox)

        layout.addLayout(form)
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        self.config.overlay_controls = self.overlay_checkbox.isChecked()
        self.config.save()
        super().accept()


class ClickableSlider(QSlider):
    """Seek bar that jumps to the clicked position."""

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            option = QStyleOptionSlider()
            self.initStyleOption(option)
            groove = self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider,
                option,
                QStyle.SubControl.SC_SliderGroove,
                self,
            )
            handle = self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider,
                option,
                QStyle.SubControl.SC_SliderHandle,
                self,
            )
            if self.orientation() == Qt.Orientation.Horizontal:
                if groove.width() <= 0:
                    super().mousePressEvent(event)
                    return
                handle_width = handle.width() or 0
                pos = event.position().x() if hasattr(event, "position") else event.x()
                range_span = self.maximum() - self.minimum()
                if range_span <= 0:
                    super().mousePressEvent(event)
                    return
                if abs(pos - (handle.x() + handle_width / 2)) <= max(6, handle_width):
                    super().mousePressEvent(event)
                    return
                slider_pos = pos - groove.x() - handle_width / 2
                slider_pos = max(0, min(slider_pos, groove.width() - handle_width))
                ratio = (
                    slider_pos / (groove.width() - handle_width)
                    if (groove.width() - handle_width) > 0
                    else 0
                )
                value = self.minimum() + range_span * ratio
                self.setValue(round(value))
                self.sliderMoved.emit(self.value())
                self.sliderPressed.emit()
                self.sliderReleased.emit()
                event.accept()
                return
        super().mousePressEvent(event)


def _format_time(milliseconds: int) -> str:
    total = max(0, milliseconds) // 1000
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class _TrashSignals(QObject):
    finished = Signal(str, str)  # path, error ("" means success)


class _TrashTask(QRunnable):
    """Move a file to the trash in the background, retrying while VLC releases it."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.signals = _TrashSignals()

    def run(self) -> None:
        error = ""
        for attempt in range(TRASH_ATTEMPTS):
            try:
                delete_to_trash(self.path)
                error = ""
                break
            except OSError as exc:
                error = str(exc) or exc.__class__.__name__
                if attempt + 1 < TRASH_ATTEMPTS:
                    time.sleep(TRASH_RETRY_DELAY_S)
        self.signals.finished.emit(str(self.path), error)



class MainWindow(QMainWindow):
    def __init__(self, engine: VlcEngine, config: Config) -> None:
        super().__init__()
        self.engine = engine
        self.config = config

        self.playlist: FolderPlaylist | None = None
        self._ended = False
        self._deleting = False
        self._seeking = False
        self._muted_volume = config.volume or 100
        self._trash_pool = QThreadPool(self)
        self._trash_pool.setMaxThreadCount(2)
        self._trash_tasks: set[_TrashTask] = set()
        self._current_folder: Path | None = None
        self._file_model = FileListModel(self)
        self._file_proxy = FileSortProxy(self)
        self._file_proxy.setSourceModel(self._file_model)
        self._file_proxy.setDynamicSortFilter(True)
        self._file_proxy.sort(self.config.panel_sort_column, Qt.SortOrder(self.config.panel_sort_order))

        self.setWindowTitle("Video Library Manager")
        self.resize(1120, 700)
        self.setMinimumSize(820, 520)
        self.setAcceptDrops(True)
        self._settings = QSettings("VideoLibraryManager", "VideoLibraryManager")
        geometry = self._settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        self._build_ui()
        self._build_actions()
        self.engine.end_reached.connect(self._on_end_reached)
        self.engine.playback_error.connect(self._on_playback_error)
        self.engine.attach_widget(self.video)
        self.engine.set_volume(config.volume)

        self._overlay_hide_timer = QTimer(self)
        self._overlay_hide_timer.setSingleShot(True)
        self._overlay_hide_timer.setInterval(HIDE_CONTROLS_MS)
        self._overlay_hide_timer.timeout.connect(self._hide_overlay_controls)

        self._cursor_pos = QCursor.pos()

        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(HIDE_CONTROLS_MS)
        self._hide_timer.timeout.connect(self._hide_fullscreen_controls)

        self._update_header()
        self._update_play_icon()
        self._apply_overlay_style()
        self._update_controls_layout()

    # -- construction -----------------------------------------------------


    def _apply_overlay_style(self) -> None:
        if self.config.overlay_controls:
            self.controls.setStyleSheet(
                "#ControlBar { background-color: rgba(0,0,0,150); border-top-left-radius: 10px; border-top-right-radius: 10px; }"
                "#ControlBar QLabel { color: white; background: transparent; }"
                "#ControlBar QToolButton { color: white; background: transparent; }"
            )
            self.overlay_container.setStyleSheet("#OverlayControls { background: transparent; }")
        else:
            self.controls.setStyleSheet("")
            self.overlay_container.setStyleSheet("")

    def _update_controls_layout(self) -> None:
        """Move the control bar to where the current settings say it belongs."""
        overlay = bool(self.config.overlay_controls) and self.stack.currentIndex() == 1
        if overlay:
            self._move_controls_to_overlay()
            self.overlay_container.setVisible(True)
            self._position_overlay_controls()
        else:
            self.overlay_container.setVisible(False)
            self._move_controls_to_player_pane()
        self.controls.show()
        if overlay and self.engine.is_playing():
            # Movies & TV style: fade the bar out after a moment of idle.
            self._overlay_hide_timer.start()

    def _detach_controls(self) -> None:
        """Remove the bar from whatever layout currently holds it (no reparent)."""
        parent = self.controls.parent()
        layout = parent.layout() if parent is not None else None
        if layout is not None and layout.indexOf(self.controls) != -1:
            layout.removeWidget(self.controls)

    def _move_controls_to_overlay(self) -> None:
        layout = self.overlay_container.layout()
        if layout is None:
            return
        if layout.indexOf(self.controls) == -1:
            self._detach_controls()
            layout.addWidget(self.controls)
        self.overlay_container.raise_()

    def _move_controls_to_player_pane(self) -> None:
        pane = self.splitter.widget(1)
        layout = pane.layout() if pane is not None else None
        if layout is None:
            self._detach_controls()
            return
        if layout.indexOf(self.controls) == -1:
            self._detach_controls()
            layout.addWidget(self.controls)

    def _position_overlay_controls(self) -> None:
        if not self.overlay_container.isVisible():
            return
        margin = 16
        width = max(320, min(self.stack.width() - margin * 2, 960))
        height = self.controls.sizeHint().height() or 46
        x = max(margin, (self.stack.width() - width) // 2)
        y = self.stack.height() - height - margin
        self.overlay_container.setGeometry(x, y, width, height)
        self.overlay_container.raise_()

    def _on_video_mouse_moved(self) -> None:
        if self.config.overlay_controls and self.stack.currentIndex() == 1 and not self.isFullScreen():
            self._show_overlay_controls()

    def _show_overlay_controls(self) -> None:
        if not (self.config.overlay_controls and self.stack.currentIndex() == 1):
            return
        self._update_controls_layout()
        self._position_overlay_controls()
        self.overlay_container.setVisible(True)
        self.controls.setVisible(True)
        self._overlay_hide_timer.start()

    def _hide_overlay_controls(self) -> None:
        if not (self.config.overlay_controls and self.stack.currentIndex() == 1):
            return
        if not self.engine.is_playing():
            self._overlay_hide_timer.start()
            return
        self.overlay_container.setVisible(False)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.top_bar = QWidget()
        self.top_bar.setObjectName("TopBar")
        top = QHBoxLayout(self.top_bar)
        top.setContentsMargins(10, 6, 12, 6)
        top.setSpacing(10)

        self.open_button = QToolButton()
        self.open_button.setText("Open")
        self.open_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.open_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)

        self.toggle_panel_button = QToolButton()
        self.toggle_panel_button.setText("Files")
        self.toggle_panel_button.setCheckable(True)
        self.toggle_panel_button.setChecked(bool(self.config.panel_visible))
        self.toggle_panel_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toggle_panel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_panel_button.clicked.connect(self._toggle_file_panel)

        self.title_label = QLabel("No video open")
        self.title_label.setObjectName("TitleLabel")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.count_label = QLabel("")
        self.count_label.setObjectName("CountLabel")

        top.addWidget(self.open_button)
        top.addWidget(self.toggle_panel_button)
        top.addWidget(self.title_label, 1)
        top.addWidget(self.count_label)

        self.video = VideoView()
        self.video.double_clicked.connect(self._toggle_fullscreen)
        self.video.mouse_moved.connect(self._on_video_mouse_moved)

        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.setSpacing(10)

        empty_title = QLabel("No video open")
        empty_title.setObjectName("EmptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_hint = QLabel("Open a video, open a folder, or drop files here.")
        empty_hint.setObjectName("EmptyHint")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_buttons = QHBoxLayout()
        empty_buttons.setSpacing(10)
        open_file_button = QPushButton("Open File...")
        open_file_button.clicked.connect(self.open_file)
        open_folder_button = QPushButton("Open Folder...")
        open_folder_button.clicked.connect(self._pick_folder)
        for button in (open_file_button, open_folder_button):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        empty_buttons.addStretch(1)
        empty_buttons.addWidget(open_file_button)
        empty_buttons.addWidget(open_folder_button)
        empty_buttons.addStretch(1)

        empty_layout.addStretch(1)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_hint)
        empty_layout.addSpacing(6)
        empty_layout.addLayout(empty_buttons)
        empty_layout.addStretch(2)

        self.stack = QStackedWidget()
        self.stack.addWidget(empty)  # 0: empty state
        self.stack.addWidget(self.video)  # 1: player

        player_pane = QWidget()
        player_layout = QVBoxLayout(player_pane)
        player_layout.setContentsMargins(0, 0, 0, 0)
        player_layout.setSpacing(0)
        player_layout.addWidget(self.stack, 1)

        self.controls = QWidget()
        self.controls.setObjectName("ControlBar")
        self.controls.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar = QHBoxLayout(self.controls)
        bar.setContentsMargins(16, 10, 16, 10)
        bar.setSpacing(8)

        self.prev_button = self._tool_button(
            QStyle.StandardPixmap.SP_MediaSkipBackward, "Previous video (Ctrl+Left)"
        )
        self.play_button = self._tool_button(
            QStyle.StandardPixmap.SP_MediaPlay, "Play / pause (Space)"
        )
        self.next_button = self._tool_button(
            QStyle.StandardPixmap.SP_MediaSkipForward, "Next video (Ctrl+Right)"
        )
        self.prev_button.clicked.connect(self.play_previous)
        self.play_button.clicked.connect(self.toggle_play)
        self.next_button.clicked.connect(self.play_next)

        self.elapsed_label = QLabel("0:00")
        self.elapsed_label.setObjectName("TimeLabel")

        self.seek = ClickableSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, SEEK_RANGE)
        self.seek.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.seek.sliderPressed.connect(self._seek_pressed)
        self.seek.sliderMoved.connect(self._seek_moved)
        self.seek.sliderReleased.connect(self._seek_released)

        self.total_label = QLabel("0:00")
        self.total_label.setObjectName("TimeLabel")

        self.mute_button = self._tool_button(QStyle.StandardPixmap.SP_MediaVolume, "Mute (M)")
        self.mute_button.clicked.connect(self._toggle_mute)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.config.volume)
        self.volume_slider.setFixedWidth(90)
        self.volume_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.volume_slider.valueChanged.connect(self._volume_changed)

        self.delete_button = self._tool_button(
            QStyle.StandardPixmap.SP_TrashIcon, "Delete current video (Del)"
        )
        self.delete_button.clicked.connect(self.delete_current)

        self.fullscreen_button = self._tool_button(
            QStyle.StandardPixmap.SP_TitleBarMaxButton, "Fullscreen (F)"
        )
        self.fullscreen_button.clicked.connect(self._toggle_fullscreen)

        bar.addWidget(self.prev_button)
        bar.addWidget(self.play_button)
        bar.addWidget(self.next_button)
        bar.addSpacing(6)
        bar.addWidget(self.elapsed_label)
        bar.addWidget(self.seek, 1)
        bar.addWidget(self.total_label)
        bar.addSpacing(6)
        bar.addWidget(self.mute_button)
        bar.addWidget(self.volume_slider)
        bar.addSpacing(6)
        bar.addWidget(self.delete_button)
        bar.addWidget(self.fullscreen_button)

        player_layout.addWidget(self.controls)

        # -- optional file list panel --
        self.file_panel = QWidget()
        self.file_panel.setObjectName("FilePanel")
        panel_layout = QVBoxLayout(self.file_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        panel_header = QWidget()
        panel_header.setObjectName("PanelHeader")
        header_layout = QHBoxLayout(panel_header)
        header_layout.setContentsMargins(10, 6, 8, 6)
        header_layout.setSpacing(6)
        panel_title = QLabel("Files")
        panel_title.setObjectName("PanelTitle")
        self.rating_widget = None
        header_layout.addWidget(panel_title, 1)

        self.file_view = QTableView()
        self.file_view.setObjectName("FileList")
        self.file_view.setModel(self._file_proxy)
        self.file_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.file_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.file_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.file_view.setShowGrid(False)
        self.file_view.setAlternatingRowColors(True)
        self.file_view.verticalHeader().setVisible(False)
        self.file_view.setSortingEnabled(True)
        self.file_view.setWordWrap(False)
        self.file_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.file_view.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSortIndicatorShown(True)
        self.file_view.sortByColumn(
            self.config.panel_sort_column, Qt.SortOrder(self.config.panel_sort_order)
        )
        self.file_view.clicked.connect(self._on_file_clicked)
        self.file_view.activated.connect(self._on_file_clicked)
        self.file_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_view.customContextMenuRequested.connect(self._on_file_context_menu)
        header.sortIndicatorChanged.connect(self._on_sort_changed)

        panel_buttons = QHBoxLayout()
        panel_buttons.setContentsMargins(10, 6, 10, 8)
        panel_buttons.setSpacing(6)
        self.panel_refresh_button = QPushButton("Refresh")
        self.panel_refresh_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.panel_refresh_button.clicked.connect(self._refresh_file_list)
        panel_buttons.addWidget(self.panel_refresh_button)
        panel_buttons.addStretch(1)

        panel_layout.addWidget(panel_header)
        panel_layout.addWidget(self.file_view, 1)
        panel_layout.addLayout(panel_buttons)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("MainSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.file_panel)
        splitter.addWidget(player_pane)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([self.config.panel_width, 900])
        self.splitter = splitter

        # Floating control bar ("Movies & TV" style). The container is a child
        # of the stack so its geometry is in stack coordinates, but it is not
        # part of the stacked layout, so it floats above the video and is not
        # affected by page switches. It is native so it can be raised above
        # libVLC's video surface, which is a separate native window.
        self.overlay_container = QWidget(self.stack)
        self.overlay_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.overlay_container.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.overlay_container.setObjectName("OverlayControls")
        self.overlay_container.setVisible(False)
        overlay_layout = QVBoxLayout(self.overlay_container)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(0)

        root.addWidget(self.top_bar)
        root.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

        self.file_panel.setVisible(bool(self.config.panel_visible))
        self._apply_overlay_style()

        self._update_mute_icon()

    def _tool_button(self, pixmap: QStyle.StandardPixmap, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setIcon(self.style().standardIcon(pixmap))
        button.setIconSize(QSize(20, 20))
        button.setAutoRaise(True)
        button.setToolTip(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(34, 30)
        return button

    def _build_actions(self) -> None:
        menu = QMenu(self)

        action_open_file = menu.addAction("Open File...")
        action_open_file.setShortcut(QKeySequence.StandardKey.Open)
        action_open_file.triggered.connect(self.open_file)

        action_open_folder = menu.addAction("Open Folder...")
        action_open_folder.setShortcut(QKeySequence("Ctrl+Shift+O"))
        action_open_folder.triggered.connect(self._pick_folder)

        menu.addSeparator()

        action_exit = menu.addAction("Exit")
        action_exit.triggered.connect(self.close)

        self.open_button.setMenu(menu)

        settings_action = menu.addAction("Settings...")
        settings_action.triggered.connect(self.open_settings)

        shortcuts = (
            (QKeySequence("Space"), self.toggle_play),
            (QKeySequence("Ctrl+Left"), self.play_previous),
            (QKeySequence("Ctrl+Right"), self.play_next),
            (QKeySequence("Left"), lambda: self._seek_relative(-SEEK_STEP_MS)),
            (QKeySequence("Right"), lambda: self._seek_relative(SEEK_STEP_MS)),
            (QKeySequence("Delete"), self.delete_current),
            (QKeySequence("F"), self._toggle_fullscreen),
            (QKeySequence("Escape"), self._escape),
            (QKeySequence("M"), self._toggle_mute),
        )
        for sequence, handler in shortcuts:
            QShortcut(sequence, self).activated.connect(handler)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            self._apply_overlay_style()
            self._update_controls_layout()
            self._position_overlay_controls()

    # -- opening media ----------------------------------------------------

    @staticmethod
    def _file_filter() -> str:
        patterns = " ".join(f"*{extension}" for extension in sorted(VIDEO_EXTENSIONS))
        return f"Video files ({patterns});;All files (*)"

    def open_file(self, path: str | Path | None = None) -> None:
        if path is None:
            start = self.config.last_folder or str(Path.home())
            selected, _ = QFileDialog.getOpenFileName(
                self, "Open video", start, self._file_filter()
            )
            if not selected:
                return
            path = selected

        path = Path(path)
        if not path.is_file():
            QMessageBox.warning(self, "Open video", f"File not found:\n{path}")
            return

        self.playlist = FolderPlaylist.open_file(path)
        self.config.last_folder = str(path.parent)
        self._current_folder = path.parent
        self._refresh_file_list()
        self._show_player_page()
        self._play_current()


    def _pick_folder(self) -> None:
        self.open_folder(pick=True)

    def open_folder(self, path: str | Path | None = None, pick: bool = False) -> None:
        if path is None or pick:
            start = self.config.last_folder or str(Path.home())
            chosen = QFileDialog.getExistingDirectory(self, "Open video folder", start)
            if not chosen:
                return
            path = chosen

        folder = Path(path)
        if not folder.is_dir():
            QMessageBox.warning(self, "Open folder", f"Folder not found:\n{folder}")
            return

        self.playlist = FolderPlaylist.from_folder(folder)
        self.config.last_folder = str(folder)
        self._current_folder = folder
        self._refresh_file_list()

        if not self.playlist:
            self._show_empty_page()
            QMessageBox.information(self, "Open folder", f"No video files found in:\n{folder}")
            return

        self._show_player_page()
        self._play_current()

    def open_path(self, path: str | Path) -> None:
        candidate = Path(path)
        if candidate.is_dir():
            self.open_folder(candidate)
        elif candidate.is_file():
            self.open_file(candidate)
        else:
            QMessageBox.warning(self, "Open", f"Path not found:\n{candidate}")

    # -- playback ---------------------------------------------------------

    def _play_current(self) -> None:
        if not self.playlist or not self.playlist.current:
            return
        self._ended = False
        self.seek.setValue(0)
        self.elapsed_label.setText("0:00")
        self.total_label.setText("0:00")
        self.engine.play(self.playlist.current)
        self._update_header()
        self._sync_file_selection()

    def toggle_play(self) -> None:
        if not self.playlist or not self.playlist.current:
            self.open_file()
            return
        if self._ended:
            self._play_current()
            return
        if not self.engine.has_media():
            self._play_current()
            return
        self.engine.toggle_pause()
        self._update_play_icon()

    def play_next(self) -> None:
        if self.playlist and self.playlist.next():
            self._play_current()

    def play_previous(self) -> None:
        if self.playlist and self.playlist.previous():
            self._play_current()

    def _seek_relative(self, delta_ms: int) -> None:
        if self.playlist and self.playlist.current:
            self.engine.seek_relative(delta_ms)

    def delete_current(self) -> None:
        if self._deleting or not self.playlist or not self.playlist.current:
            return

        path = self.playlist.current
        answer = QMessageBox.question(
            self,
            "Delete video",
            f"Move “{path.name}” to the Recycle Bin?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        # Advance first: switching media releases the old file a moment later and
        # never leaves the player parked while libVLC stops or the shell trashes.
        self._deleting = True
        try:
            self.playlist.remove_current()
            if self.playlist.current:
                self._play_current()
            else:
                self.engine.stop()
                self._show_empty_page()
        finally:
            self._deleting = False

        self._refresh_file_list()
        self._trash_in_background(path)

    def _trash_in_background(self, path: Path) -> None:
        task = _TrashTask(path)
        self._trash_tasks.add(task)
        task.signals.finished.connect(
            lambda _path, error, finished=task: self._on_trash_finished(finished, error)
        )
        self._trash_pool.start(task)

    def _on_trash_finished(self, task: _TrashTask, error: str) -> None:
        self._trash_tasks.discard(task)
        self._refresh_file_list()
        if not error:
            return
        QMessageBox.warning(
            self,
            "Delete failed",
            f"Could not move “{task.path.name}” to the Recycle Bin:\n\n{error}\n\n"
            "The next video is playing, but the file is still on disk.",
        )

    # -- state updates ----------------------------------------------------

    def _toggle_file_panel(self, checked: bool | None = None) -> None:
        visible = self.toggle_panel_button.isChecked() if checked is None else bool(checked)
        self.toggle_panel_button.setChecked(visible)
        self.file_panel.setVisible(visible)
        self.config.panel_visible = visible
        if visible:
            self._refresh_file_list()

    def _refresh_file_list(self) -> None:
        if self._current_folder is None:
            self._file_model.clear()
            return
        self._file_model.set_folder(self._current_folder)
        self._file_model.set_ratings(self.config.ratings)
        self._sync_file_selection()

    def _sync_file_selection(self) -> None:
        current = self.playlist.current if self.playlist else None
        self._file_model.set_current(current)
        if current is None:
            self.file_view.clearSelection()
            return
        index = self._file_model.index_for_path(current)
        if index is None:
            return
        proxy_index = self._file_proxy.mapFromSource(index)
        if proxy_index.isValid():
            self.file_view.setCurrentIndex(proxy_index)
            self.file_view.scrollTo(proxy_index, QTableView.ScrollHint.EnsureVisible)

    def _play_path(self, path: Path) -> None:
        if self.playlist is not None and self.playlist.select_path(path):
            self._show_player_page()
            self._play_current()
            return
        self.open_file(path)

    def _on_file_clicked(self, proxy_index) -> None:
        if not proxy_index.isValid():
            return
        source_index = self._file_proxy.mapToSource(proxy_index)
        path = self._file_model.path_at(source_index.row())
        if path is None:
            return
        current = self.playlist.current if self.playlist else None
        if current is not None and os.path.normcase(str(current)) == os.path.normcase(str(path)):
            return
        self._play_path(path)

    def _on_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        self.config.panel_sort_column = column
        self.config.panel_sort_order = int(order.value if hasattr(order, "value") else order)

    def _on_file_context_menu(self, position) -> None:
        proxy_index = self.file_view.indexAt(position)
        if not proxy_index.isValid():
            return
        source_index = self._file_proxy.mapToSource(proxy_index)
        path = self._file_model.path_at(source_index.row())
        if path is None:
            return

        menu = QMenu(self)
        play_action = menu.addAction("Play")
        play_action.triggered.connect(lambda: self._play_path(path))
        menu.addSeparator()
        rating_menu = menu.addMenu("Rating")
        current = self.config.get_rating(path)
        for stars in range(6):
            label = "No rating" if stars == 0 else "★" * stars + "☆" * (5 - stars)
            action = rating_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(stars == current)
            action.triggered.connect(lambda _checked=False, value=stars: self._rate_path(path, value))
        menu.exec(self.file_view.viewport().mapToGlobal(position))

    def _rate_path(self, path: Path, rating: int) -> None:
        self.config.set_rating(path, rating)
        self.config.save()
        self._file_model.set_ratings(self.config.ratings)

    def _set_file_rating(self, row: int, rating: int) -> None:
        path = self._file_model.path_at(row)
        if path is None:
            return
        self._rate_path(path, rating)

    def _on_file_rated(self, proxy_index, rating: int) -> None:
        if not proxy_index.isValid():
            return
        source_index = self._file_proxy.mapToSource(proxy_index)
        self._set_file_rating(source_index.row(), rating)

    def _show_player_page(self) -> None:
        self.stack.setCurrentIndex(1)
        self._update_controls_layout()
        if self.config.overlay_controls:
            self._show_overlay_controls()

    def _show_empty_page(self) -> None:
        self.playlist = None
        self._ended = False
        self.stack.setCurrentIndex(0)
        self.seek.setValue(0)
        self.elapsed_label.setText("0:00")
        self.total_label.setText("0:00")
        self._file_model.set_current(None)
        self.file_view.clearSelection()
        self._update_header()
        self._update_play_icon()
        self._update_controls_layout()

    def _update_header(self) -> None:
        if self.playlist and self.playlist.current:
            name = self.playlist.current.name
            self.title_label.setText(name)
            self.count_label.setText(f"{self.playlist.position} of {self.playlist.count}")
            self.setWindowTitle(f"{name} — Video Library Manager")
        else:
            self.title_label.setText("No video open")
            self.count_label.setText("")
            self.setWindowTitle("Video Library Manager")

        has_video = bool(self.playlist and self.playlist.current)
        self.play_button.setEnabled(has_video)
        self.prev_button.setEnabled(bool(self.playlist and self.playlist.has_previous))
        self.next_button.setEnabled(bool(self.playlist and self.playlist.has_next))
        self.delete_button.setEnabled(has_video)

    def _update_play_icon(self) -> None:
        pixmap = (
            QStyle.StandardPixmap.SP_MediaPause
            if self.engine.is_playing()
            else QStyle.StandardPixmap.SP_MediaPlay
        )
        self.play_button.setIcon(self.style().standardIcon(pixmap))

    def _update_mute_icon(self) -> None:
        pixmap = (
            QStyle.StandardPixmap.SP_MediaVolumeMuted
            if self.volume_slider.value() == 0
            else QStyle.StandardPixmap.SP_MediaVolume
        )
        self.mute_button.setIcon(self.style().standardIcon(pixmap))

    # -- timers -----------------------------------------------------------

    def _on_tick(self) -> None:
        self._update_play_icon()

        if self.isFullScreen():
            position = QCursor.pos()
            if position != self._cursor_pos:
                self._cursor_pos = position
                self._show_fullscreen_controls()

        if not self.engine.has_media():
            return

        length = self.engine.length_ms()
        if length <= 0:
            return

        if not self._seeking:
            position = self.engine.time_ms()
            self.seek.setValue(min(SEEK_RANGE, int(position * SEEK_RANGE / length)))
            self.elapsed_label.setText(_format_time(position))
        self.total_label.setText(_format_time(length))

    # -- seek / volume ----------------------------------------------------

    def _seek_pressed(self) -> None:
        self._seeking = True

    def _seek_moved(self, value: int) -> None:
        length = self.engine.length_ms()
        if length > 0:
            self.elapsed_label.setText(_format_time(int(value * length / SEEK_RANGE)))

    def _seek_released(self) -> None:
        self._seeking = False
        self.engine.set_position(self.seek.value() / SEEK_RANGE)

    def _volume_changed(self, value: int) -> None:
        self.engine.set_volume(value)
        self.config.volume = value
        self._update_mute_icon()

    def _toggle_mute(self) -> None:
        if self.volume_slider.value() > 0:
            self._muted_volume = self.volume_slider.value()
            self.volume_slider.setValue(0)
        else:
            self.volume_slider.setValue(self._muted_volume or 100)

    # -- fullscreen -------------------------------------------------------

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.top_bar.show()
            self.controls.show()
            self.file_panel.setVisible(bool(self.config.panel_visible))
            self.unsetCursor()
            self._hide_timer.stop()
            self._overlay_hide_timer.stop()
            self._update_controls_layout()
            self.fullscreen_button.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton)
            )
        else:
            self.showFullScreen()
            self.top_bar.hide()
            self.file_panel.hide()
            self._update_controls_layout()
            self.fullscreen_button.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarNormalButton)
            )
            self._show_fullscreen_controls()
            if self.config.overlay_controls:
                self._show_overlay_controls()

    def _escape(self) -> None:
        if self.isFullScreen():
            self._toggle_fullscreen()

    def _overlay_active(self) -> bool:
        return bool(self.config.overlay_controls) and self.stack.currentIndex() == 1

    def _show_fullscreen_controls(self) -> None:
        if not self.isFullScreen():
            return
        self.unsetCursor()
        if self._overlay_active():
            self._show_overlay_controls()
        else:
            self.controls.show()
        self._hide_timer.start()

    def _hide_fullscreen_controls(self) -> None:
        if not self.isFullScreen():
            return
        if not self.engine.is_playing():
            self._hide_timer.start()
            return
        if self._overlay_active():
            self.overlay_container.setVisible(False)
        else:
            self.controls.hide()
        self.setCursor(Qt.CursorShape.BlankCursor)

    # -- engine events ----------------------------------------------------

    def _on_end_reached(self) -> None:
        if self._deleting or not self.playlist or not self.engine.is_ended():
            return
        if self.config.auto_advance and self.playlist.has_next:
            self.playlist.next()
            self._play_current()
            return
        self._ended = True
        self._update_play_icon()

    def _on_playback_error(self, message: str) -> None:
        QMessageBox.warning(self, "Playback error", message)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.config.overlay_controls:
            self._position_overlay_controls()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                self.open_path(local)
                event.acceptProposedAction()
                return
        event.ignore()

    def closeEvent(self, event) -> None:
        try:
            sizes = self.splitter.sizes()
            if sizes:
                self.config.panel_width = max(160, sizes[0])
        except (AttributeError, IndexError):
            pass
        self.config.save()
        self.engine.stop()
        self._trash_pool.waitForDone(2000)
        self.engine.shutdown()
        super().closeEvent(event)
