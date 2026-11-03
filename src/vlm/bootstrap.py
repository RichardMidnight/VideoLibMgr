"""Prerequisite checks with install prompts. Stdlib only (runs before PySide6)."""

from __future__ import annotations

import ctypes
import importlib.util
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

MIN_PYTHON = (3, 11)
REQUIRED_PACKAGES = (
    ("PySide6", "PySide6"),
    ("vlc", "python-vlc"),
    ("send2trash", "Send2Trash"),
)
VLC_DOWNLOAD_URL = "https://www.videolan.org/vlc/download-windows.html"


def ensure_prerequisites() -> bool:
    """Check Python, pip packages and libVLC; prompt to install what is missing."""
    if sys.version_info < MIN_PYTHON:
        required = ".".join(str(part) for part in MIN_PYTHON)
        print(f"Python {required}+ is required (found {sys.version.split()[0]}).")
        print("Download it from https://www.python.org/downloads/")
        return False
    _linux_video_env()
    return _ensure_packages() and _ensure_libvlc()


def _linux_video_env() -> None:
    """Under Wayland, run Qt on X11 so libVLC can attach to the video window.

    libVLC's X11 output needs a real X11 window ID from ``winId()``; the
    Wayland backend doesn't provide one. Harmless if Qt is already on X11.
    """
    if sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")


# -- python packages ------------------------------------------------------


def _missing_packages() -> list[tuple[str, str]]:
    return [
        (module, package)
        for module, package in REQUIRED_PACKAGES
        if importlib.util.find_spec(module) is None
    ]


def _ensure_packages() -> bool:
    missing = _missing_packages()
    if not missing:
        return True

    names = ", ".join(package for _, package in missing)
    print(f"Missing required Python package(s): {names}")
    if not _ask("Install them now with pip?"):
        print("Install them manually, then start the app again:")
        print(f"  {sys.executable} -m pip install " + " ".join(p for _, p in missing))
        return False

    if not _ensure_pip():
        return False

    print(f"Installing: {names}")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", *[p for _, p in missing]], check=False
    )
    importlib.invalidate_caches()
    if result.returncode != 0:
        print("pip could not install the missing packages.")
        return False

    still_missing = _missing_packages()
    if still_missing:
        print("Still missing after install: " + ", ".join(p for _, p in still_missing))
        return False
    return True


def _ensure_pip() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True
    print("pip is not available; trying ensurepip…")
    return (
        subprocess.run(
            [sys.executable, "-m", "ensurepip", "--upgrade"], check=False
        ).returncode
        == 0
    )


# -- libvlc ---------------------------------------------------------------


def _ensure_libvlc() -> bool:
    if os.name == "nt":
        library = _find_windows_libvlc()
        if library:
            return _configure_windows_libvlc(library)
        return _offer_vlc_install()

    if sys.platform == "darwin":
        library = _find_mac_libvlc()
        if library:
            _configure_mac_libvlc(library)
            return True
        print("libVLC was not found. VLC media player is required.")
        print("Install it with:  brew install --cask vlc")
        print("or download it from https://www.videolan.org/vlc/download-macosx.html")
        return False
    else:
        # Linux: let python-vlc's own loader do the real test. It knows the
        # versioned names (libvlc.so.5 for VLC 3.x, libvlc.so.9 for 4.x ...),
        # unlike ctypes.util.find_library, which only sees "libvlc.so".
        try:
            import vlc  # noqa: F401
        except OSError:
            print("libVLC was not found. VLC media player is required.")
            print("Install it with your package manager, for example:")
            print("  Debian/Ubuntu: sudo apt install vlc")
            print("  Fedora:        sudo dnf install vlc")
            return False
        return True


def _find_windows_libvlc() -> Path | None:
    candidates = _windows_registry_dirs()
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "VideoLAN" / "VLC")
    vlc_executable = shutil.which("vlc")
    if vlc_executable:
        candidates.append(Path(vlc_executable).parent)

    for directory in candidates:
        library = directory / "libvlc.dll"
        if library.is_file():
            return library
    return None


def _windows_registry_dirs() -> list[Path]:
    import winreg

    directories: list[Path] = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for key in (
            r"SOFTWARE\VideoLAN\VLC",
            r"SOFTWARE\WOW6432Node\VideoLAN\VLC",
        ):
            try:
                with winreg.OpenKey(root, key) as handle:
                    directory, _ = winreg.QueryValueEx(handle, "InstallDir")
            except OSError:
                continue
            if directory:
                directories.append(Path(directory))
    return directories


def _configure_windows_libvlc(library: Path) -> bool:
    directory = library.parent
    os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(library))
    plugins = directory / "plugins"
    if plugins.is_dir():
        os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(plugins))
    os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    try:
        os.add_dll_directory(str(directory))
    except (AttributeError, OSError):
        pass

    try:
        ctypes.WinDLL(str(library))
    except OSError as exc:
        bits = 64 if sys.maxsize > 2**32 else 32
        print(f"Found VLC in {directory}, but libvlc could not be loaded: {exc}")
        print("The usual cause is a bitness mismatch: VLC must match Python.")
        print(f"Python is {bits}-bit, so install the {'64' if bits == 64 else '32'}-bit VLC.")
        return False
    return True


def _offer_vlc_install() -> bool:
    print("VLC media player (libVLC) was not found.")
    winget = shutil.which("winget")
    if winget and _ask("Install VLC now with winget?"):
        subprocess.run(
            [
                winget,
                "install",
                "--id",
                "VideoLAN.VLC",
                "-e",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ],
            check=False,
        )
        library = _find_windows_libvlc()
        if library:
            return _configure_windows_libvlc(library)
        print("VLC still not found after the install attempt.")

    if _ask("Open the VLC download page now?"):
        webbrowser.open(VLC_DOWNLOAD_URL)
    print("Install 64-bit VLC (matching Python), then start the app again.")
    return False


def _find_mac_libvlc() -> Path | None:
    candidates = (
        Path("/Applications/VLC.app/Contents/MacOS/lib/libvlc.dylib"),
        Path("/Applications/VLC.app/Contents/MacOS/libvlc.dylib"),
        Path.home() / "Applications/VLC.app/Contents/MacOS/lib/libvlc.dylib",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _configure_mac_libvlc(library: Path) -> None:
    os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(library))
    for plugins in (
        library.parent.parent / "plugins",
        library.parent / "plugins",
    ):
        if plugins.is_dir():
            os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(plugins))
            break


# -- prompting ------------------------------------------------------------


def _ask(prompt: str) -> bool:
    """Yes/no prompt that also works when there is no console (pythonw)."""
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            answer = input(f"{prompt} [Y/n] ").strip().lower()
        except EOFError:
            return False
        return answer in ("", "y", "yes")

    if os.name == "nt":
        message_box_yes_no = 0x04
        message_box_icon_question = 0x20
        id_yes = 6
        result = ctypes.windll.user32.MessageBoxW(
            None,
            prompt,
            "Video Library Manager",
            message_box_yes_no | message_box_icon_question,
        )
        return result == id_yes
    return True
