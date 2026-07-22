import json
from pathlib import Path

from desktop_app.project_service import ProjectService
from desktop_app.run_history_service import RunHistoryService


def _write_attempt(project_root: Path, run_id: str, attempt_id: str, *, status: str, error: str = "") -> Path:
    root = project_root / "runs" / run_id / "attempts" / attempt_id
    root.mkdir(parents=True)
    (root / "desktop_state.json").write_text(
        json.dumps({"logical_run_id": run_id, "attempt_id": attempt_id, "parent_attempt_id": None, "status": status}),
        encoding="utf-8",
    )
    artifacts = root / "artifacts"
    artifacts.mkdir()
    (artifacts / "manifest.json").write_text(
        json.dumps({"status": "ERROR" if status == "FAILED" else status, "error": error, "outputs": {}}),
        encoding="utf-8",
    )
    return root


def test_history_lists_newest_persisted_attempts_with_manifest_error(tmp_path: Path):
    project = ProjectService().create(tmp_path / "project", "项目")
    _write_attempt(project.root, "run-001", "attempt-001", status="FAILED", error="weld failed")
    _write_attempt(project.root, "run-002", "attempt-001", status="COMPLETED")

    entries = RunHistoryService().list_attempts(project)

    assert [entry.attempt.logical_run_id for entry in entries] == ["run-002", "run-001"]
    assert entries[1].failure_reason == "weld failed"


def test_history_skips_invalid_desktop_state_files(tmp_path: Path):
    project = ProjectService().create(tmp_path / "project", "项目")
    root = project.root / "runs" / "run-001" / "attempts" / "attempt-001"
    root.mkdir(parents=True)
    (root / "desktop_state.json").write_text("not json", encoding="utf-8")

    assert RunHistoryService().list_attempts(project) == []
