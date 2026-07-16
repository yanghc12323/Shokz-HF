"""Run state controls that only expose valid actions."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from desktop_app.models import AttemptRecord, RunStatus
from desktop_app.run_controller import RunController


class RunMonitor(QWidget):
    def __init__(self, controller: RunController) -> None:
        super().__init__()
        self.controller = controller
        layout = QVBoxLayout(self)
        heading = QLabel("运行分析")
        heading.setObjectName("pageTitle")
        subtitle = QLabel("实时显示当前处理样本、分析阶段及最近一次样本结果。")
        subtitle.setObjectName("pageSubtitle")
        self.status_label = QLabel("尚未开始运行")
        self.status_label.setObjectName("runStatus")
        progress_card = QFrame()
        progress_card.setObjectName("contentCard")
        progress = QGridLayout(progress_card)
        self.current_sample_label = self._progress_value("等待样本")
        self.current_stage_label = self._progress_value("等待阶段")
        self.sample_result_label = self._progress_value("等待结果")
        for column, (caption, value) in enumerate((
            ("当前样本", self.current_sample_label),
            ("当前步骤", self.current_stage_label),
            ("样本结果", self.sample_result_label),
        )):
            label = QLabel(caption)
            label.setObjectName("progressCaption")
            progress.addWidget(label, 0, column)
            progress.addWidget(value, 1, column)
        self.event_label = QLabel("等待运行事件。")
        self.event_label.setObjectName("runEvent")
        self.event_label.setWordWrap(True)
        self.total_progress = QProgressBar()
        self.total_progress.setFormat("Region 总进度：%v / %m")
        self.total_progress.setRange(0, 0)
        self.region_table = QTableWidget(0, 7)
        self.region_table.setHorizontalHeaderLabels(["样本", "Region", "原始 QC", "修复后 QC", "Salvaged QC", "最终状态", "原因"])
        self._region_rows: dict[tuple[str, str], int] = {}
        actions = QHBoxLayout()
        self.pause_button = QPushButton("暂停")
        self.resume_button = QPushButton("继续")
        self.cancel_button = QPushButton("取消")
        self.pause_button.clicked.connect(self.controller.request_pause)
        self.resume_button.clicked.connect(self.controller.resume)
        self.cancel_button.clicked.connect(self.controller.cancel)
        for button in (self.pause_button, self.resume_button, self.cancel_button):
            actions.addWidget(button)
        layout.addWidget(heading)
        layout.addWidget(subtitle)
        layout.addWidget(self.status_label)
        layout.addWidget(progress_card)
        layout.addWidget(self.total_progress)
        layout.addWidget(self.event_label)
        layout.addWidget(self.region_table, 1)
        layout.addLayout(actions)
        layout.addStretch(1)
        controller.attempt_changed.connect(self.set_attempt)
        controller.event_received.connect(self.show_event)
        self._event_timer = QTimer(self)
        self._event_timer.setInterval(500)
        self._event_timer.timeout.connect(self.poll_events)
        self._set_actions(None)

    def set_attempt(self, attempt: AttemptRecord) -> None:
        self.status_label.setText(f"当前任务：{attempt.logical_run_id} · {attempt.status}")
        self._set_actions(attempt.status)
        if attempt.status is RunStatus.RUNNING:
            self._event_timer.start()
        elif attempt.status in {RunStatus.CANCELLED, RunStatus.COMPLETED, RunStatus.FAILED}:
            self._event_timer.stop()

    @staticmethod
    def _progress_value(initial: str) -> QLabel:
        label = QLabel(initial)
        label.setObjectName("progressValue")
        return label

    def show_event(self, event: dict[str, object]) -> None:
        stage = str(event.get("stage", "运行"))
        sample = str(event.get("sample_tag", ""))
        kind = str(event.get("event", "状态更新"))
        self.event_label.setText(" · ".join(part for part in (kind, stage, sample) if part))
        if sample:
            self.current_sample_label.setText(sample)
        if stage:
            self.current_stage_label.setText(stage)
        if kind == "region_started":
            self._set_region(event, "处理中", "", "", "", "处理中", "")
        elif kind == "region_finished":
            self._set_region(event, str(event.get("raw_status", "")), str(event.get("repaired_status", "")), str(event.get("salvaged_status", "")), str(event.get("final_status", "")), str(event.get("reason", "")))
        if kind == "sample_started":
            self.sample_result_label.setText("处理中")
        elif kind == "sample_finished":
            status = str(event.get("status", "完成")).upper()
            self.sample_result_label.setText("通过" if status in {"PASS", "YES", "COMPLETED"} else "失败" if status in {"ERROR", "FAIL", "FAILED"} else status)
        elif kind == "stage_error":
            self.sample_result_label.setText("阶段失败")

    def _set_region(self, event, raw, repaired, salvaged, final, reason) -> None:
        sample, region = str(event.get("sample_tag", "")), str(event.get("region_id", ""))
        key = (sample, region)
        row = self._region_rows.get(key)
        if row is None:
            row = self.region_table.rowCount(); self.region_table.insertRow(row); self._region_rows[key] = row
        for column, value in enumerate((sample, region, raw, repaired, salvaged, final, reason)):
            self.region_table.setItem(row, column, QTableWidgetItem(value))
        total = int(event.get("total_regions", 0) or 0)
        completed = int(event.get("completed_regions", 0) or 0)
        if total:
            self.total_progress.setRange(0, total); self.total_progress.setValue(completed)

    def poll_events(self) -> None:
        if self.controller.active_attempt is not None:
            self.controller.read_new_events()

    def _set_actions(self, status: RunStatus | None) -> None:
        self.pause_button.setEnabled(status is RunStatus.RUNNING)
        self.resume_button.setEnabled(status is RunStatus.PAUSED)
        self.cancel_button.setEnabled(status in {RunStatus.RUNNING, RunStatus.PAUSE_REQUESTED, RunStatus.PAUSED})
