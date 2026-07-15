import json
from pathlib import Path

from desktop_app.models import AttemptRecord
from desktop_app.recovery_service import RecoveryService
from desktop_app.ui.expert_mode import ExpertMode


class FakeRecoveryController:
    def __init__(self) -> None:
        self.calls = []

    def start_recovery(self, project, parent, option):
        self.calls.append((project, parent, option))


def failed_attempt_with_salvaged(tmp_path: Path) -> AttemptRecord:
    attempt = AttemptRecord.create(tmp_path / "project", "run-001", "attempt-001")
    (attempt.artifacts_dir / "remesh_r24" / "salvaged").mkdir(parents=True)
    (attempt.artifacts_dir / "manifest.json").write_text(
        json.dumps({"status": "ERROR", "output_scope": "isolated", "outputs": {"salvaged_dir": "remesh_r24/salvaged"}}),
        encoding="utf-8",
    )
    return attempt


def test_expert_mode_only_enables_integrity_checked_recovery_options(qtbot, tmp_path: Path):
    controller = FakeRecoveryController()
    panel = ExpertMode(RecoveryService(), controller)
    qtbot.addWidget(panel)
    parent = failed_attempt_with_salvaged(tmp_path)

    panel.set_attempt(parent)

    assert panel.option_button("WELD").isEnabled()
    assert not panel.option_button("ALIGNMENT").isEnabled()
