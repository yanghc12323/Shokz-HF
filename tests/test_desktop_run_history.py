import json
from pathlib import Path

from desktop_app.project_service import ProjectService
from desktop_app.recovery_service import RecoveryService
from desktop_app.run_controller import RunController
from desktop_app.ui.main_window import MainWindow
from desktop_app.ui.run_history import RunHistoryPanel
from desktop_app.validation_service import ValidationService


class FakeProcess:
    def setProgram(self, program: str) -> None: pass
    def setArguments(self, arguments: list[str]) -> None: pass
    def setWorkingDirectory(self, path: str) -> None: pass
    def start(self) -> None: pass


def _failed_attempt(project_root: Path) -> None:
    root = project_root / "runs" / "run-001" / "attempts" / "attempt-001"
    salvaged = root / "artifacts" / "remesh_r24" / "salvaged"
    salvaged.mkdir(parents=True)
    (root / "desktop_state.json").write_text(
        json.dumps({"logical_run_id": "run-001", "attempt_id": "attempt-001", "parent_attempt_id": None, "status": "FAILED"}),
        encoding="utf-8",
    )
    (root / "artifacts" / "manifest.json").write_text(
        json.dumps({"status": "ERROR", "error": "weld failed", "outputs": {"salvaged_dir": "remesh_r24/salvaged"}}),
        encoding="utf-8",
    )


def test_history_panel_enables_expert_recovery_for_valid_failed_attempt(qtbot, tmp_path: Path):
    project = ProjectService().create(tmp_path / "project", "项目")
    _failed_attempt(project.root)
    panel = RunHistoryPanel(RecoveryService())
    qtbot.addWidget(panel)

    panel.set_project(project)
    panel.history_table.selectRow(0)
    panel._update_selection()

    assert panel.history_table.rowCount() == 1
    assert panel.recover_button.isEnabled()
    assert "weld failed" in panel.reason_label.text()


def test_history_recovery_button_opens_expert_mode_with_selected_parent(qtbot, tmp_path: Path):
    project = ProjectService().create(tmp_path / "project", "项目")
    _failed_attempt(project.root)
    window = MainWindow(ProjectService(), ValidationService(), RunController(process_factory=FakeProcess))
    qtbot.addWidget(window)

    window.open_project(project)
    window._navigate(4)
    window.run_history.history_table.selectRow(0)
    window.run_history._update_selection()
    window.run_history.recover_button.click()

    assert window.content_stack.currentWidget() is window.expert_mode
    assert window.expert_mode.parent is not None
    assert window.expert_mode.parent.attempt_id == "attempt-001"


def test_starting_recovery_returns_to_monitor_with_controls_disabled(qtbot, tmp_path: Path):
    project = ProjectService().create(tmp_path / "project", "项目")
    project.mesh_dir.mkdir(parents=True)
    project.landmarks_dir.mkdir(parents=True)
    project.config_dir.mkdir(parents=True)
    (project.mesh_dir / "T001_L.ply").write_text("mesh", encoding="utf-8")
    (project.landmarks_dir / "T001_L_landmarks.csv").write_text("landmark_id,x,y,z\n", encoding="utf-8")
    project.region_table_path.write_text("region_id,resolution\nR01,24\n", encoding="utf-8")
    _failed_attempt(project.root)
    controller = RunController(process_factory=FakeProcess)
    window = MainWindow(ProjectService(), ValidationService(), controller)
    qtbot.addWidget(window)

    window.open_project(project)
    window._navigate(4)
    window.run_history.history_table.selectRow(0)
    window.run_history._update_selection()
    window.run_history.recover_button.click()
    window.expert_mode.option_button("WELD").click()

    assert window.wizard.stack.currentWidget() is window.run_monitor
    assert controller.active_attempt is not None
    assert controller.active_attempt.parent_attempt_id == "attempt-001"
    assert not window.run_monitor.pause_button.isEnabled()
    assert not window.run_monitor.cancel_button.isEnabled()
