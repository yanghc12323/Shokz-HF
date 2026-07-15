from desktop_app.__main__ import create_main_window
from desktop_app.ui.main_window import MainWindow


def test_module_entrypoint_builds_main_window():
    window = create_main_window([])

    assert isinstance(window, MainWindow)
    assert window.windowTitle() == "耳廓工程分析"
