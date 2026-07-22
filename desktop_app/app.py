"""Desktop application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


_FONT_LOADED = False


def _resource_path(*parts: str) -> Path:
    """Locate package resources in both source and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS, "desktop_app", *parts)
    return Path(__file__).resolve().parent.joinpath(*parts)


def _install_chinese_font(application: QApplication) -> None:
    global _FONT_LOADED
    if not _FONT_LOADED:
        font_id = QFontDatabase.addApplicationFont(
            str(_resource_path("assets", "fonts", "NotoSansSC-VF.ttf"))
        )
        if font_id < 0:
            raise RuntimeError("无法加载内置中文界面字体")
        _FONT_LOADED = True
    application.setFont(QFont("Noto Sans SC", 10))


def create_application(argv: list[str] | None = None) -> QApplication:
    """Create the single Qt application instance used by the desktop client."""
    existing = QApplication.instance()
    if existing is not None:
        _install_chinese_font(existing)
        return existing
    application = QApplication(sys.argv if argv is None else ["Shokz-耳部降采样分析系统", *argv])
    _install_chinese_font(application)
    return application
