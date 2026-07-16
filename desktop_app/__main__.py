"""Launch the local Windows engineering desktop application."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from desktop_app.app import create_application
from desktop_app.project_service import ProjectService
from desktop_app.run_controller import RunController
from desktop_app.ui.main_window import MainWindow
from desktop_app.validation_service import ValidationService


_BUNDLED_SCRIPTS = {
    "run_full_pipeline.py": "scripts.run_full_pipeline",
    "parameterize_ear_remesh.py": "scripts.parameterize_ear_remesh",
    "visualize_remesh_qc.py": "scripts.visualize_remesh_qc",
    "build_whole_ear.py": "scripts.build_whole_ear",
    "align_whole_ear.py": "scripts.align_whole_ear",
    "build_average_ear.py": "scripts.build_average_ear",
}


def dispatch_bundled_script() -> bool:
    """Run a bundled CLI script when the frozen EXE is used as its interpreter."""
    if not getattr(sys, "frozen", False) or len(sys.argv) < 2:
        return False
    script_name = Path(sys.argv[1]).name
    module_name = _BUNDLED_SCRIPTS.get(script_name)
    if module_name is None:
        return False
    sys.argv = [script_name, *sys.argv[2:]]
    module = importlib.import_module(module_name)
    module.main()
    return True


def create_main_window(argv: list[str] | None = None) -> MainWindow:
    create_application(argv)
    return MainWindow(ProjectService(), ValidationService(), RunController())


def main() -> int:
    if dispatch_bundled_script():
        return 0
    application = create_application(sys.argv[1:])
    window = create_main_window(sys.argv[1:])
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
