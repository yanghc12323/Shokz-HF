"""Launch the local Windows engineering desktop application."""

from __future__ import annotations

import sys

from desktop_app.app import create_application
from desktop_app.project_service import ProjectService
from desktop_app.run_controller import RunController
from desktop_app.ui.main_window import MainWindow
from desktop_app.validation_service import ValidationService


def create_main_window(argv: list[str] | None = None) -> MainWindow:
    create_application(argv)
    return MainWindow(ProjectService(), ValidationService(), RunController())


def main() -> int:
    application = create_application(sys.argv[1:])
    window = create_main_window(sys.argv[1:])
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
