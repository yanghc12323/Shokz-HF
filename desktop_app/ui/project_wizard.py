"""Guided project, import, validation and run-options pages."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QComboBox,
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

    def show_import_error(self, message: str) -> None:
        self.import_error_label.setText(message)
        self.import_error_label.show()

    def clear_import_error(self) -> None:
        self.import_error_label.clear()
        self.import_error_label.hide()

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
        self.import_error_label = QLabel()
        self.import_error_label.setObjectName("projectError")
        self.import_error_label.setWordWrap(True)
        self.import_error_label.hide()
        form.addRow("", button)
        form.addRow("", self.import_error_label)
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
        ) = editors
        self.alignment_mode = QComboBox()
        self.alignment_mode.setObjectName("alignmentMode")
        self.alignment_mode.addItem("GPA 配准（默认，推荐）", "gpa")
        self.alignment_mode.addItem("固定参考耳配准", "fixed-reference")
        self.alignment_mode.setToolTip("选择本次分析采用的刚性配准路径；固定参考耳模式必须填写一个通过 Weld 的样本标签。")
        alignment_label = QLabel("刚性配准方式")
        alignment_label.setObjectName("fieldLabel")
        self.option_labels.append(alignment_label)
        alignment_hint = QLabel("GPA 使用全体合格耳进行广义 Procrustes 配准；固定参考耳将所有合格耳配准到指定样本。")
        alignment_hint.setObjectName("fieldHint")
        alignment_hint.setWordWrap(True)
        form.addRow(alignment_label, self.alignment_mode)
        form.addRow("", alignment_hint)
        self.reference_sample = QLineEdit()
        self.reference_sample.setPlaceholderText("例如 MQ_S076L（当前固定参考耳）")
        self.reference_sample.setToolTip("固定参考耳模式下必填；填写要作为参考耳的样本标签。该样本必须通过 Weld。")
        self.reference_sample.setEnabled(False)
        reference_label = QLabel("固定参考耳样本")
        reference_label.setObjectName("fieldLabel")
        self.option_labels.append(reference_label)
        reference_hint = QLabel("仅在“固定参考耳配准”模式下启用。GPA 模式不会使用此项。")
        reference_hint.setObjectName("fieldHint")
        reference_hint.setWordWrap(True)
        form.addRow(reference_label, self.reference_sample)
        form.addRow("", reference_hint)
        self.alignment_mode.currentIndexChanged.connect(self._update_reference_sample_state)
        self.qc_figure_mode = QComboBox()
        self.qc_figure_mode.setObjectName("qcFigureMode")
        self.qc_figure_mode.addItem("全部生成（耗时最长）", "all")
        self.qc_figure_mode.addItem("仅生成修复后 FAIL 区域（推荐）", "repaired-fail")
        self.qc_figure_mode.addItem("不生成 QC 图（最快）", "none")
        self.qc_figure_mode.setCurrentIndex(1)
        self.qc_figure_mode.setToolTip("只影响 Region QC PNG，不影响 QC 判定、CSV 或后续门禁。")
        qc_label = QLabel("Region QC 图生成")
        qc_label.setObjectName("fieldLabel")
        self.option_labels.append(qc_label)
        form.addRow(qc_label, self.qc_figure_mode)
        self.parallel_workers = QComboBox()
        self.parallel_workers.setObjectName("parallelWorkers")
        self.parallel_workers.addItem("自动（推荐，最多 4 个）", 0)
        self.parallel_workers.addItem("1 个（串行）", 1)
        self.parallel_workers.addItem("2 个", 2)
        self.parallel_workers.addItem("4 个", 4)
        self.parallel_workers.setToolTip("仅并行处理相互独立的样本 Remesh/QC；Weld、对齐和 PCA 保持串行。")
        workers_label = QLabel("并行处理数")
        workers_label.setObjectName("fieldLabel")
        self.option_labels.append(workers_label)
        workers_hint = QLabel("自动模式按本机 CPU 核心数选择 1–4 个任务；内存不足或电脑较慢时可改为 1 或 2。")
        workers_hint.setObjectName("fieldHint")
        workers_hint.setWordWrap(True)
        form.addRow(workers_label, self.parallel_workers)
        form.addRow("", workers_hint)
        self.start_analysis_button = QPushButton("一键开始分析")
        self.start_analysis_button.clicked.connect(self._emit_run_options)
        self.options_error_label = QLabel()
        self.options_error_label.setObjectName("projectError")
        self.options_error_label.setWordWrap(True)
        self.options_error_label.hide()
        form.addRow("", self.start_analysis_button)
        form.addRow("", self.options_error_label)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _update_reference_sample_state(self) -> None:
        fixed_reference = self.alignment_mode.currentData() == "fixed-reference"
        self.reference_sample.setEnabled(fixed_reference)
        if not fixed_reference:
            self.reference_sample.clear()

    def _emit_run_options(self) -> None:
        try:
            max_unmapped_ratio = float(self.max_unmapped_ratio.text())
            max_degenerate_ratio = float(self.max_degenerate_ratio.text())
            pca_variance_threshold = float(self.pca_variance_threshold.text())
            if not all(0 <= value <= 1 for value in (
                max_unmapped_ratio,
                max_degenerate_ratio,
                pca_variance_threshold,
            )):
                raise ValueError
        except ValueError:
            self.options_error_label.setText("运行参数必须填写为 0 到 1 之间的数字，请检查后重试。")
            self.options_error_label.show()
            return
        alignment_mode = str(self.alignment_mode.currentData())
        reference_sample = self.reference_sample.text().strip()
        if alignment_mode == "fixed-reference" and not reference_sample:
            self.options_error_label.setText("固定参考耳模式必须填写参考耳样本标签，例如 MQ_S001L。")
            self.options_error_label.show()
            return
        self.options_error_label.hide()
        self.start_requested.emit(
            RunOptions(
                max_salvage_unmapped_ratio=max_unmapped_ratio,
                max_salvage_degenerate_ratio=max_degenerate_ratio,
                pca_variance_threshold=pca_variance_threshold,
                reference_sample=reference_sample or None,
                qc_figure_mode=str(self.qc_figure_mode.currentData()),
                alignment_mode=alignment_mode,
                parallel_workers=int(self.parallel_workers.currentData()),
            )
        )

    @staticmethod
    def _build_monitor_placeholder() -> QWidget:
        page, layout = _page("一键全流程分析", "任务启动后将显示实时阶段、样本进度和可恢复的运行记录。")
        layout.addStretch(1)
        return page
