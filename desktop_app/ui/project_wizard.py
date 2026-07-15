"""Guided project, import, validation and run-options pages."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_app.models import ProjectRecord, ValidationIssue


def _page(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 26, 28, 28)
    layout.setSpacing(10)
    heading = QLabel(title)
    heading.setObjectName("pageTitle")
    note = QLabel(subtitle)
    note.setObjectName("pageSubtitle")
    note.setWordWrap(True)
    layout.addWidget(heading)
    layout.addWidget(note)
    return page, layout


class ValidationPage(QWidget):
    """Shows every preflight issue before an attempt can be allocated."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 28)
        heading = QLabel("自动校验")
        heading.setObjectName("pageTitle")
        self.summary_label = QLabel("尚未导入项目输入。")
        self.summary_label.setObjectName("validationSummary")
        self.issue_list = QLabel()
        self.issue_list.setObjectName("validationIssues")
        self.issue_list.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.issue_list)
        layout.addStretch(1)

    def set_issues(self, issues: list[ValidationIssue]) -> None:
        errors = [issue for issue in issues if issue.severity.upper() == "ERROR"]
        if not issues:
            self.summary_label.setText("校验通过：可以配置参数并开始全流程分析。")
            self.issue_list.setText("所有网格、地标和配置文件均已成对且可读取。")
            return
        self.summary_label.setText(f"发现 {len(errors)} 项错误，必须处理后才能进入运行参数。")
        self.issue_list.setText("\n".join(f"• {issue.message}" for issue in issues))


class Workflow:
    """Minimal state machine for the non-skippable guided route."""

    page_ids = ("project", "import", "validation", "options", "monitor")

    def __init__(self, stack: QStackedWidget) -> None:
        self._stack = stack
        self.project: ProjectRecord | None = None
        self.issues: list[ValidationIssue] = []
        self.current_page = "project"

    def set_project(self, project: ProjectRecord, issues: list[ValidationIssue]) -> None:
        self.project = project
        self.issues = issues
        self.go_to("validation")

    def can_advance_to(self, page_id: str) -> bool:
        if page_id not in self.page_ids:
            return False
        if page_id in {"options", "monitor"}:
            return self.project is not None and not any(
                issue.severity.upper() == "ERROR" for issue in self.issues
            )
        return True

    def go_to(self, page_id: str) -> bool:
        if not self.can_advance_to(page_id):
            return False
        self.current_page = page_id
        self._stack.setCurrentIndex(self.page_ids.index(page_id))
        return True


class ProjectWizard(QWidget):
    """Visible guided sequence, intentionally separate from expert mode."""

    project_requested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.project_page = self._build_project_page()
        self.import_page = self._build_import_page()
        self.validation_page = ValidationPage()
        self.options_page = self._build_options_page()
        self.monitor_placeholder = self._build_monitor_placeholder()
        for page in (
            self.project_page,
            self.import_page,
            self.validation_page,
            self.options_page,
            self.monitor_placeholder,
        ):
            self.stack.addWidget(page)
        layout.addWidget(self.stack)
        self.workflow = Workflow(self.stack)

    def _build_project_page(self) -> QWidget:
        page, layout = _page("新建项目", "选择一个独立的工作目录；软件会在其中保存输入副本、运行记录和结果。")
        card = QFrame()
        card.setObjectName("contentCard")
        form = QFormLayout(card)
        self.project_name = QLineEdit()
        self.project_name.setPlaceholderText("例如：2026 年 7 月耳廓批次")
        self.project_root = QLineEdit()
        self.project_root.setPlaceholderText("选择空的项目工作目录")
        button = QPushButton("创建项目")
        button.clicked.connect(lambda: self.project_requested.emit(self.project_root.text(), self.project_name.text()))
        form.addRow("项目名称", self.project_name)
        form.addRow("工作目录", self.project_root)
        form.addRow("", button)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    @staticmethod
    def _build_import_page() -> QWidget:
        page, layout = _page("导入数据", "导入后软件只使用项目目录中的副本，原始数据不会被改写。")
        card = QFrame()
        card.setObjectName("contentCard")
        form = QFormLayout(card)
        for title, placeholder in (
            ("网格目录", "包含 .ply 网格的目录"),
            ("地标目录", "包含 *_landmarks.csv 的目录"),
            ("区域表", "region_table.csv"),
            ("边界控制点", "edge_control_points.csv"),
        ):
            input_box = QLineEdit()
            input_box.setPlaceholderText(placeholder)
            form.addRow(title, input_box)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    @staticmethod
    def _build_options_page() -> QWidget:
        page, layout = _page("运行参数", "第一版仅允许选择现有配置并调整少量运行参数；配置表请在项目文件夹中维护。")
        card = QFrame()
        card.setObjectName("contentCard")
        form = QFormLayout(card)
        for title, value in (
            ("最大 Salvage 未映射比例", "0.35"),
            ("最大 Salvage 退化比例", "0.015"),
            ("PCA 累积解释方差", "0.75"),
            ("固定参考耳（可选）", ""),
        ):
            editor = QLineEdit(value)
            form.addRow(title, editor)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    @staticmethod
    def _build_monitor_placeholder() -> QWidget:
        page, layout = _page("一键全流程分析", "任务启动后将显示实时阶段、样本进度和可恢复的运行记录。")
        layout.addStretch(1)
        return page
