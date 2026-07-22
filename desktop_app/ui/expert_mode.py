"""Restricted stage recovery controls for validated parent attempts."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from desktop_app.models import AttemptRecord, ProjectRecord
from desktop_app.recovery_service import RecoveryOption, RecoveryService


class ExpertMode(QWidget):
    recovery_started = Signal(object)

    def __init__(self, recovery_service: RecoveryService, controller) -> None:
        super().__init__()
        self.recovery_service = recovery_service
        self.controller = controller
        self.project: ProjectRecord | None = None
        self.parent: AttemptRecord | None = None
        layout = QVBoxLayout(self)
        self.summary_label = QLabel(
            "专家恢复：仅用于失败或取消的运行。从“运行记录”选择一次运行后，"
            "可在不改写原结果的前提下重跑已验证的后续阶段。"
        )
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        self._buttons: dict[RecoveryOption, QPushButton] = {}
        for option in RecoveryOption:
            button = QPushButton(option)
            button.clicked.connect(lambda _checked=False, value=option: self.start_option(value))
            self._buttons[option] = button
            layout.addWidget(button)
        layout.addStretch(1)
        self._set_options([])

    def set_project(self, project: ProjectRecord) -> None:
        self.project = project

    def set_attempt(self, parent: AttemptRecord) -> None:
        self.parent = parent
        options = self.recovery_service.plan(parent)
        self._set_options(options)
        self.summary_label.setText("可恢复阶段：" + ("、".join(options) if options else "无（父产物未通过完整性校验）"))

    def option_button(self, option: RecoveryOption | str) -> QPushButton:
        return self._buttons[RecoveryOption(option)]

    def start_option(self, option: RecoveryOption) -> None:
        if self.project is None or self.parent is None:
            raise RuntimeError("请先选择项目和失败运行")
        if option not in self.recovery_service.plan(self.parent):
            raise ValueError("该阶段缺少已验证的父运行输入")
        attempt = self.controller.start_recovery(self.project, self.parent, option)
        self.recovery_started.emit(attempt)

    def _set_options(self, available: list[RecoveryOption]) -> None:
        for option, button in self._buttons.items():
            enabled = option in available
            button.setEnabled(enabled)
            button.setToolTip("执行隔离恢复" if enabled else "缺少经过完整性校验的上游输出")
