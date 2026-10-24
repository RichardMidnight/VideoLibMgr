"""Application bootstrap: Qt setup, dark theme, main window."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from .core.config import Config
from .ui.main_window import MainWindow
from .video.engine import VlcEngine

STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1c1c1c;
    color: #e8e8e8;
}
#TopBar {
    background-color: #232323;
    border-bottom: 1px solid #2e2e2e;
}
#ControlBar {
    background-color: #232323;
    border-top: 1px solid #2e2e2e;
}
#TitleLabel {
    color: #f0f0f0;
    font-size: 14px;
}
#CountLabel {
    color: #9a9a9a;
    font-size: 12px;
}
#TimeLabel {
    color: #c8c8c8;
    font-size: 12px;
}
#EmptyTitle {
    color: #f0f0f0;
    font-size: 22px;
    font-weight: 600;
}
#EmptyHint {
    color: #9a9a9a;
    font-size: 13px;
}
QToolButton {
    border: none;
    border-radius: 4px;
    padding: 2px;
}
QToolButton:hover {
    background-color: #333333;
}
QToolButton:pressed {
    background-color: #3d3d3d;
}
QToolButton:disabled {
    background-color: transparent;
}
QPushButton {
    background-color: #2d2d2d;
    border: 1px solid #3c3c3c;
    border-radius: 6px;
    padding: 8px 18px;
}
QPushButton:hover {
    background-color: #3a3a3a;
}
QPushButton:pressed {
    background-color: #454545;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #3a3a3a;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #4c8dff;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #e8e8e8;
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover {
    background: #ffffff;
}
QMenu {
    background-color: #262626;
    border: 1px solid #3a3a3a;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #3a3a3a;
}
QMessageBox {
    background-color: #232323;
}
"""


def _apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1c1c1c"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e8e8e8"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#232323"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#2a2a2a"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e8e8e8"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#2d2d2d"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e8e8e8"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#4c8dff"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2a2a2a"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#e8e8e8"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8a8a8a"))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv if argv is None else argv)

    app = QApplication(arguments)
    app.setApplicationName("Video Library Manager")
    app.setApplicationDisplayName("Video Library Manager")
    app.setOrganizationName("VideoLibraryManager")
    _apply_theme(app)

    try:
        engine = VlcEngine()
    except Exception as exc:  # noqa: BLE001 - surfaced to the user
        QMessageBox.critical(
            None,
            "libVLC error",
            f"Could not initialise libVLC.\n\n{exc}\n\n"
            "Run the app from a terminal to see prerequisite help.",
        )
        return 1

    config = Config()
    window = MainWindow(engine, config)
    window.show()

    for argument in arguments[1:]:
        candidate = Path(argument)
        if candidate.exists():
            window.open_path(candidate)
            break

    return app.exec()
