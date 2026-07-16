"""Chinese-only engineering workbench window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_app.models import ProjectRecord
from desktop_app.artifact_indexer import ArtifactIndexer
from desktop_app.project_service import ProjectService
from desktop_app.run_controller import RunController
from desktop_app.ui.project_wizard import ProjectWizard
from desktop_app.ui.expert_mode import ExpertMode
from desktop_app.ui.result_workbench import ResultWorkbench
from desktop_app.ui.run_monitor import RunMonitor
from desktop_app.validation_service import ValidationService
from desktop_app.recovery_service import RecoveryService


class MainWindow(QMainWindow):
    """The app shell keeps the default path visible and expert work isolated."""

    navigation_labels = ("项目", "分析流程", "结果复核", "专家模式", "运行记录")

    def __init__(
        self,
        project_service: ProjectService,
        validation_service: ValidationService,
        run_controller: RunController,
    ) -> None:
        super().__init__()
        self.project_service = project_service
        self.validation_service = validation_service
        self.run_controller = run_controller
        self.project: ProjectRecord | None = None
        self.setWindowTitle("耳廓工程分析")
        self.resize(1280, 800)
        self.setMinimumSize(1024, 680)

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_sidebar())
        self.content_stack = QStackedWidget()
        self.wizard = ProjectWizard()
        self.workflow = self.wizard.workflow
        self.validation_page = self.wizard.validation_page
        self.run_monitor = RunMonitor(run_controller)
        self.wizard.stack.removeWidget(self.wizard.monitor_placeholder)
        self.wizard.monitor_placeholder.deleteLater()
        self.wizard.stack.insertWidget(4, self.run_monitor)
        self.result_workbench = ResultWorkbench()
        self.expert_mode = ExpertMode(RecoveryService(), run_controller)
        self.content_stack.addWidget(self.wizard)
        self.content_stack.addWidget(self.result_workbench)
        self.content_stack.addWidget(self.expert_mode)
        self.content_stack.addWidget(self._placeholder("运行记录", "查看本项目的运行、失败原因和恢复尝试。"))
        root_layout.addWidget(self.content_stack, 1)
        self.setCentralWidget(root)
        self.wizard.project_requested.connect(self.create_project)
        self.wizard.import_requested.connect(
            lambda mesh, landmarks, regions: self.import_project_inputs(
                Path(mesh), Path(landmarks), Path(regions)
            )
        )
        self.wizard.start_requested.connect(self.start_analysis)
        self.run_controller.run_finished.connect(self.load_completed_attempt)
        self._apply_style()

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 18)
        brand = QLabel("耳廓工程分析")
        brand.setObjectName("brand")
        caption = QLabel("LOCAL ENGINEERING")
        caption.setObjectName("caption")
        layout.addWidget(brand)
        layout.addWidget(caption)
        layout.addSpacing(28)
        for index, label in enumerate(self.navigation_labels):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.clicked.connect(lambda _checked=False, value=index: self._navigate(value))
            layout.addWidget(button)
        layout.addStretch(1)
        offline = QLabel("● 本机离线运行")
        offline.setObjectName("offline")
        layout.addWidget(offline)
        return sidebar

    @staticmethod
    def _placeholder(title: str, message: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 30, 34, 34)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        description = QLabel(message)
        description.setObjectName("pageSubtitle")
        description.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addStretch(1)
        return page

    def _navigate(self, index: int) -> None:
        if index == 1:
            self.content_stack.setCurrentWidget(self.wizard)
            return
        if index == 0:
            self.workflow.go_to("project")
            self.content_stack.setCurrentWidget(self.wizard)
            return
        self.content_stack.setCurrentIndex(index - 1)

    def create_project(self, root: str, name: str) -> ProjectRecord | None:
        try:
            project = self.project_service.create(Path(root), name.strip() or "未命名项目")
        except (OSError, ValueError) as error:
            self.wizard.show_project_error(self._project_creation_error(error))
            return None
        self.project = project
        self.expert_mode.set_project(project)
        self.wizard.clear_project_error()
        self.workflow.begin_import(project)
        self.content_stack.setCurrentWidget(self.wizard)
        return project

    @staticmethod
    def _project_creation_error(error: Exception) -> str:
        if "not empty" in str(error):
            return "无法创建项目：所选工作目录不是空文件夹。请选择空文件夹或新建一个文件夹。"
        return f"无法创建项目：{error}"

    def open_project(self, project: ProjectRecord) -> None:
        self.project = project
        self.expert_mode.set_project(project)
        issues = self.validation_service.validate(project)
        self.validation_page.set_issues(issues)
        self.workflow.set_project(project, issues)
        self.content_stack.setCurrentWidget(self.wizard)

    def import_project_inputs(
        self,
        mesh_dir: Path,
        landmarks_dir: Path,
        region_table: Path,
    ) -> ProjectRecord:
        if self.project is None:
            raise RuntimeError("请先创建或打开项目")
        project = self.project_service.import_inputs(
            self.project,
            mesh_dir=mesh_dir,
            landmarks_dir=landmarks_dir,
            region_table=region_table,
        )
        self.project = project
        issues = self.validation_service.validate(project)
        self.validation_page.set_issues(issues)
        self.workflow.set_project(project, issues)
        if self.workflow.can_advance_to("options"):
            self.workflow.go_to("options")
        return project

    def start_analysis(self, options) -> None:
        if self.project is None or not self.workflow.can_advance_to("monitor"):
            raise RuntimeError("当前项目未通过自动校验，无法开始分析")
        self.run_controller.start(self.project, options)
        self.workflow.go_to("monitor")

    def load_completed_attempt(self, attempt) -> None:
        if str(attempt.status) != "COMPLETED":
            return
        self.result_workbench.set_attempt(ArtifactIndexer().index(attempt))
        self.content_stack.setCurrentWidget(self.result_workbench)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow { background: #f3f6f8; color: #19242d; }
            #sidebar { background: #17242f; color: #dce6eb; }
            #brand { color: #f4f8fa; font-size: 19px; font-weight: 700; }
            #caption { color: #7f9aa8; font-size: 10px; letter-spacing: 1px; }
            #navButton { border: 0; border-radius: 5px; color: #c4d2d9; padding: 10px 12px; text-align: left; background: transparent; }
            #navButton:hover { background: #243945; color: #ffffff; }
            #offline { color: #83c8ae; font-size: 11px; }
            #pageTitle { color: #17242f; font-size: 25px; font-weight: 700; }
            #pageSubtitle { color: #657782; font-size: 13px; }
            #contentCard { background: #ffffff; border: 1px solid #d9e2e7; border-radius: 7px; padding: 16px; }
            #validationSummary { color: #8e4b1f; background: #fff7ed; border: 1px solid #fed7aa; border-radius: 5px; padding: 10px; }
            #validationIssues { color: #5a6972; padding: 8px 2px; }
            #runStatus { color: #0d5e6f; font-size: 14px; font-weight: 600; }
            #fieldLabel { color: #263843; font-weight: 600; }
            #fieldHint { color: #657782; font-size: 12px; padding: 0 0 6px 0; }
            #progressCaption { color: #657782; font-size: 12px; }
            #progressValue { color: #17242f; font-size: 16px; font-weight: 700; }
            QLineEdit { color: #19242d; background: #fbfcfd; border: 1px solid #cfdbe1; border-radius: 4px; padding: 7px; min-width: 320px; }
            QLineEdit:read-only { color: #334955; background: #f4f7f8; }
            QLineEdit::selection { color: #ffffff; background: #0d6674; }
            #projectError { color: #9b2c2c; background: #fff5f5; border: 1px solid #fecaca; border-radius: 4px; padding: 8px; }
            QPushButton { background: #0d6674; color: white; border: 0; border-radius: 4px; padding: 8px 14px; }
            QPushButton:disabled { background: #a8b6bc; color: #eaf0f2; }
        """)
