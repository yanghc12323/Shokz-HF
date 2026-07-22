"""Project-scoped history browser and safe recovery handoff."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_app.models import AttemptRecord, ProjectRecord, RunStatus
from desktop_app.recovery_service import RecoveryService
from desktop_app.run_history_service import RunHistoryEntry, RunHistoryService


class RunHistoryPanel(QWidget):
    """Lets users select an integrity-checked failed attempt for recovery."""

    recovery_requested = Signal(object)

    def __init__(
        self,
        recovery_service: RecoveryService,
        *,
        history_service: RunHistoryService | None = None,
    ) -> None:
        super().__init__()
        self.recovery_service = recovery_service
        self.history_service = history_service or RunHistoryService()
        self.project: ProjectRecord | None = None
        self.entries: list[RunHistoryEntry] = []

        layout = QVBoxLayout(self)
        heading = QLabel("运行记录")
        heading.setObjectName("pageTitle")
        description = QLabel("选择失败或已取消的运行；仅当上游产物通过完整性校验时，才可进入专家恢复。")
        description.setObjectName("pageSubtitle")
        description.setWordWrap(True)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(("运行批次", "Attempt", "状态", "失败原因", "可恢复阶段"))
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history_table.itemSelectionChanged.connect(self._update_selection)
        self.reason_label = QLabel("请选择一条运行记录。")
        self.reason_label.setWordWrap(True)
        self.recover_button = QPushButton("进入专家恢复")
        self.recover_button.setEnabled(False)
        self.recover_button.clicked.connect(self._request_recovery)
        self.refresh_button = QPushButton("刷新运行记录")
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addWidget(self.history_table, 1)
        layout.addWidget(self.reason_label)
        layout.addWidget(self.recover_button)
        layout.addWidget(self.refresh_button)

    def set_project(self, project: ProjectRecord) -> None:
        self.project = project
        self.refresh()

    def refresh(self) -> None:
        self.entries = [] if self.project is None else self.history_service.list_attempts(self.project)
        self.history_table.setRowCount(0)
        for row, entry in enumerate(self.entries):
            options = self.recovery_service.plan(entry.attempt)
            values = (
                entry.attempt.logical_run_id,
                entry.attempt.attempt_id,
                entry.attempt.status,
                entry.failure_reason or "—",
                "、".join(options) if options else "无",
            )
            self.history_table.insertRow(row)
            for column, value in enumerate(values):
                self.history_table.setItem(row, column, QTableWidgetItem(str(value)))
        if self.entries:
            self.history_table.selectRow(0)
        else:
            self.reason_label.setText("当前项目尚无可读取的运行记录。")
            self.recover_button.setEnabled(False)

    def _selected_entry(self) -> RunHistoryEntry | None:
        row = self.history_table.currentRow()
        return self.entries[row] if 0 <= row < len(self.entries) else None

    def _update_selection(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            self.reason_label.setText("请选择一条运行记录。")
            self.recover_button.setEnabled(False)
            return
        options = self.recovery_service.plan(entry.attempt)
        recoverable = entry.attempt.status in {RunStatus.FAILED, RunStatus.CANCELLED} and bool(options)
        reason = entry.failure_reason or "未记录具体失败原因，请查看本次运行日志。"
        self.reason_label.setText(f"失败说明：{reason}")
        self.recover_button.setEnabled(recoverable)
        self.recover_button.setToolTip("进入专家模式并选择恢复阶段" if recoverable else "该运行没有可验证的恢复输入")

    def _request_recovery(self) -> None:
        entry = self._selected_entry()
        if entry is not None and self.recover_button.isEnabled():
            self.recovery_requested.emit(entry.attempt)
