from pathlib import Path
import sys

from desktop_app.__main__ import create_main_window
from desktop_app.app import _resource_path
from desktop_app.ui.main_window import MainWindow


def test_module_entrypoint_builds_main_window():
    window = create_main_window([])

    assert isinstance(window, MainWindow)
    assert window.windowTitle() == "耳廓工程分析"


def test_frozen_resource_path_keeps_the_desktop_package_directory(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert _resource_path("assets", "fonts", "NotoSansSC-VF.ttf") == (
        tmp_path / "desktop_app" / "assets" / "fonts" / "NotoSansSC-VF.ttf"
    )
