"""Guided project, import, validation and run-options pages."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_app.models import ProjectRecord, RunOptions, ValidationIssue


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

    def begin_import(self, project: ProjectRecord) -> None:
        """Enter the required import step for a newly created project."""
        self.project = project
        self.issues = []
        self.go_to("import")

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
    import_requested = Signal(str, str, str)
    start_requested = Signal(object)

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
        self.project_name.setToolTip("项目名称：用于在软件中识别这一批分析，不会修改原始文件名。")
        self.project_root = QLineEdit()
        self.project_root.setReadOnly(True)
        self.project_root.setPlaceholderText("点击“浏览文件夹”选择一个空目录")
        self.project_root.setToolTip("项目工作目录：软件会在此保存输入副本、运行记录和分析结果。")
        self.browse_project_root_button = QPushButton("浏览文件夹…")
        self.browse_project_root_button.clicked.connect(self._browse_project_root)
        root_picker = QWidget()
        root_layout = QHBoxLayout(root_picker)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.project_root, 1)
        root_layout.addWidget(self.browse_project_root_button)
        self.create_project_button = QPushButton("创建项目")
        self.create_project_button.clicked.connect(
            lambda: self.project_requested.emit(self.project_root.text(), self.project_name.text())
        )
        self.project_error_label = QLabel()
        self.project_error_label.setObjectName("projectError")
        self.project_error_label.setWordWrap(True)
        self.project_error_label.hide()
        form.addRow("项目名称", self.project_name)
        form.addRow("说明", QLabel("项目名称用于区分分析批次；可以使用中文，不会影响样本文件名。"))
        form.addRow("工作目录", root_picker)
        form.addRow("说明", QLabel("请选择空文件夹。软件将在其中建立项目、复制输入并保存全部结果。"))
        form.addRow("", self.project_error_label)
        form.addRow("", self.create_project_button)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _browse_project_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择项目工作目录")
        if selected:
            self.project_root.setText(selected)

    def show_project_error(self, message: str) -> None:
        self.project_error_label.setText(message)
        self.project_error_label.show()

    def clear_project_error(self) -> None:
        self.project_error_label.clear()
        self.project_error_label.hide()

    def _build_import_page(self) -> QWidget:
        page, layout = _page("导入数据", "导入后软件只使用项目目录中的副本，原始数据不会被改写。")
        card = QFrame()
        card.setObjectName("contentCard")
        form = QFormLayout(card)
        self.mesh_source, self.browse_mesh_source_button = self._path_picker(
            "包含 .ply 网格的目录", "浏览文件夹…", self._browse_mesh_source
        )
        self.landmarks_source, self.browse_landmarks_source_button = self._path_picker(
            "包含 *_landmarks.csv 的目录", "浏览文件夹…", self._browse_landmarks_source
        )
        self.region_source, self.browse_region_source_button = self._path_picker(
            "选择 region_table.csv", "浏览文件…", self._browse_region_source
        )
        form.addRow("网格目录", self._picker_row(self.mesh_source, self.browse_mesh_source_button))
        form.addRow("地标目录", self._picker_row(self.landmarks_source, self.browse_landmarks_source_button))
        form.addRow("区域表", self._picker_row(self.region_source, self.browse_region_source_button))
        button = QPushButton("导入并自动校验")
        button.clicked.connect(
            lambda: self.import_requested.emit(
                self.mesh_source.text(), self.landmarks_source.text(),
                self.region_source.text(),
            )
        )
        form.addRow("", button)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    @staticmethod
    def _picker_row(field: QLineEdit, button: QPushButton) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field, 1)
        layout.addWidget(button)
        return row

    @staticmethod
    def _path_picker(placeholder: str, button_text: str, handler) -> tuple[QLineEdit, QPushButton]:
        field = QLineEdit()
        field.setReadOnly(True)
        field.setPlaceholderText(placeholder)
        button = QPushButton(button_text)
        button.clicked.connect(handler)
        return field, button

    def _browse_mesh_source(self) -> None:
        self._choose_directory(self.mesh_source, "选择网格目录")

    def _browse_landmarks_source(self) -> None:
        self._choose_directory(self.landmarks_source, "选择地标目录")

    def _browse_region_source(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "选择区域表", filter="CSV 文件 (*.csv)")
        if selected:
            self.region_source.setText(selected)

    def _choose_directory(self, field: QLineEdit, title: str) -> None:
        selected = QFileDialog.getExistingDirectory(self, title)
        if selected:
            field.setText(selected)

    def _build_options_page(self) -> QWidget:
        page, layout = _page("运行参数", "请确认以下阈值；悬停输入框可查看含义。一般情况下保留默认值即可。")
        card = QFrame()
        card.setObjectName("contentCard")
        form = QFormLayout(card)
        editors: list[QLineEdit] = []
        self.option_labels: list[QLabel] = []
        for title, value, hint in (
            ("最大 Salvage 未映射比例", "0.35", "允许 Salvage 的最大未映射比例，取值 0–1；默认 0.35。"),
            ("最大 Salvage 退化比例", "0.015", "允许 Salvage 的最大退化面比例，取值 0–1；默认 0.015。"),
            ("PCA 累积解释方差", "0.75", "PCA 保留的最小累计解释方差，取值 0–1；默认 0.75。"),
            ("固定参考耳（可选）", "", "指定一个样本标签作为固定参考耳，例如 T001_L；留空则不启用。"),
        ):
            editor = QLineEdit(value)
            editor.setToolTip(hint)
            label = QLabel(title)
            label.setObjectName("fieldLabel")
            self.option_labels.append(label)
            hint_label = QLabel(hint)
            hint_label.setObjectName("fieldHint")
            hint_label.setWordWrap(True)
            form.addRow(label, editor)
            form.addRow("", hint_label)
            editors.append(editor)
        (
            self.max_unmapped_ratio,
            self.max_degenerate_ratio,
            self.pca_variance_threshold,
            self.reference_sample,
        ) = editors
        self.start_analysis_button = QPushButton("一键开始分析")
        self.start_analysis_button.clicked.connect(self._emit_run_options)
        form.addRow("", self.start_analysis_button)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _emit_run_options(self) -> None:
        self.start_requested.emit(
            RunOptions(
                max_salvage_unmapped_ratio=float(self.max_unmapped_ratio.text()),
                max_salvage_degenerate_ratio=float(self.max_degenerate_ratio.text()),
                pca_variance_threshold=float(self.pca_variance_threshold.text()),
                reference_sample=self.reference_sample.text().strip() or None,
            )
        )

    @staticmethod
    def _build_monitor_placeholder() -> QWidget:
        page, layout = _page("一键全流程分析", "任务启动后将显示实时阶段、样本进度和可恢复的运行记录。")
        layout.addStretch(1)
        return page
