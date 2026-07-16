from pathlib import Path
import json

from PySide6.QtWidgets import QApplication, QFileDialog

from desktop_app.app import create_application
from desktop_app.project_service import ProjectService
from desktop_app.run_controller import RunController
from desktop_app.ui.main_window import MainWindow
from desktop_app.validation_service import ValidationService


class FakeProcess:
    def setProgram(self, program: str) -> None:
        self.program = program

    def setArguments(self, arguments: list[str]) -> None:
        self.arguments = arguments

    def setWorkingDirectory(self, path: str) -> None:
        self.working_directory = path

    def start(self) -> None:
        pass


def invalid_project(tmp_path: Path):
    return ProjectService().create(tmp_path / "invalid-project", "无效项目")


def test_create_application_reuses_existing_qapplication():
    app = create_application([])

    assert app is QApplication.instance()


def test_application_loads_bundled_chinese_font():
    app = create_application([])

    assert app.font().family() == "Noto Sans SC"


def test_new_project_page_browses_for_workspace_and_explains_fields(qtbot, monkeypatch, tmp_path: Path):
    window = MainWindow(ProjectService(), ValidationService(), RunController(process_factory=FakeProcess))
    qtbot.addWidget(window)
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(tmp_path / "workspace"),
    )

    window.wizard.browse_project_root_button.click()

    assert window.wizard.project_root.text() == str(tmp_path / "workspace")
    assert window.wizard.project_root.isReadOnly()
    assert "项目名称" in window.wizard.project_name.toolTip()
    assert "工作目录" in window.wizard.project_root.toolTip()


def test_project_fields_use_a_dark_text_color(qtbot):
    window = MainWindow(ProjectService(), ValidationService(), RunController(process_factory=FakeProcess))
    qtbot.addWidget(window)

    assert "QLineEdit { color: #19242d;" in window.styleSheet()


def test_creating_project_moves_to_import_page(qtbot, tmp_path: Path):
    window = MainWindow(ProjectService(), ValidationService(), RunController(process_factory=FakeProcess))
    qtbot.addWidget(window)

    window.create_project(str(tmp_path / "workspace"), "项目")

    assert window.workflow.current_page == "import"


def test_project_creation_error_is_shown_in_the_page(qtbot, tmp_path: Path):
    workspace = tmp_path / "nonempty-workspace"
    workspace.mkdir()
    (workspace / "existing.txt").write_text("occupied", encoding="utf-8")
    window = MainWindow(ProjectService(), ValidationService(), RunController(process_factory=FakeProcess))
    qtbot.addWidget(window)
    window.wizard.project_root.setText(str(workspace))
    window.wizard.project_name.setText("项目")

    window.wizard.create_project_button.click()

    assert not window.wizard.project_error_label.isHidden()
    assert "目录" in window.wizard.project_error_label.text()


def test_options_page_is_blocked_by_validation_error(qtbot, tmp_path: Path):
    window = MainWindow(
        ProjectService(),
        ValidationService(),
        RunController(process_factory=FakeProcess),
    )
    qtbot.addWidget(window)

    window.open_project(invalid_project(tmp_path))

    assert not window.workflow.can_advance_to("options")
    assert not window.workflow.go_to("options")
    assert "错误" in window.validation_page.summary_label.text()


def test_import_inputs_runs_validation_and_opens_options_when_valid(qtbot, tmp_path: Path):
    source = tmp_path / "source"
    mesh_dir = source / "mesh"
    landmarks_dir = source / "landmarks"
    mesh_dir.mkdir(parents=True)
    landmarks_dir.mkdir()
    (mesh_dir / "T001_L.ply").write_bytes(b"ply\nformat ascii 1.0\nend_header\n")
    (landmarks_dir / "T001_L_landmarks.csv").write_text("name,x,y,z\nL1,0,0,0\n", encoding="utf-8")
    region_table = source / "region_table.csv"
    edge_controls = source / "edge_control_points.csv"
    region_table.write_text("region_id,resolution\nR01,24\n", encoding="utf-8")
    edge_controls.write_text("edge_start,edge_end,control_point\nL1,L1,L1\n", encoding="utf-8")
    window = MainWindow(ProjectService(), ValidationService(), RunController(process_factory=FakeProcess))
    qtbot.addWidget(window)
    project = window.create_project(str(tmp_path / "project"), "项目")

    window.import_project_inputs(mesh_dir, landmarks_dir, region_table, edge_controls)

    assert project.mesh_dir.is_dir()
    assert window.workflow.can_advance_to("options")
    assert window.workflow.current_page == "options"

    window.wizard.start_analysis_button.click()

    assert window.run_controller.active_attempt is not None
    assert window.workflow.current_page == "monitor"
    assert "RUNNING" in window.run_monitor.status_label.text()

    window.run_controller.event_received.emit(
        {"event": "sample_started", "stage": "REMESH", "sample_tag": "T001_L"}
    )

    assert "T001_L" in window.run_monitor.event_label.text()

    window.run_controller.event_path.write_text(
        '{"event":"stage_started","stage":"WELD"}\n', encoding="utf-8"
    )
    window.run_monitor.poll_events()

    assert "WELD" in window.run_monitor.event_label.text()

    attempt = window.run_controller.active_attempt
    attempt.artifacts_dir.mkdir()
    (attempt.artifacts_dir / "manifest.json").write_text(
        json.dumps({"status": "COMPLETED", "output_scope": "isolated", "outputs": {}}),
        encoding="utf-8",
    )
    (attempt.artifacts_dir / "pipeline_batch_summary.csv").write_text(
        "sample_tag,discovery,remesh,salvage,weld,alignment,pca_included,reason\n"
        "T001_L,READY,PASS,PASS,PASS,PASS,YES,\n",
        encoding="utf-8",
    )
    window.run_controller.refresh_terminal_status()

    assert window.result_workbench.index is not None


def test_guided_pages_follow_the_approved_sequence(qtbot):
    window = MainWindow(
        ProjectService(),
        ValidationService(),
        RunController(process_factory=FakeProcess),
    )
    qtbot.addWidget(window)

    assert window.workflow.page_ids == (
        "project", "import", "validation", "options", "monitor"
    )
    assert window.navigation_labels == ("项目", "分析流程", "结果复核", "专家模式", "运行记录")
    assert window.wizard.stack.widget(4) is window.run_monitor
    assert window.content_stack.widget(1) is window.result_workbench
    assert window.content_stack.widget(2) is window.expert_mode
