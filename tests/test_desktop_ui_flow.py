from pathlib import Path

from PySide6.QtWidgets import QApplication

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
