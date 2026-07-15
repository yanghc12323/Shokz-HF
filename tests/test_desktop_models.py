from pathlib import Path

from desktop_app.models import AttemptRecord, RunStatus


def test_attempt_record_uses_isolated_artifacts_directory(tmp_path: Path):
    attempt = AttemptRecord.create(tmp_path, "run-001", "attempt-001")

    assert attempt.artifacts_dir == (
        tmp_path
        / "runs"
        / "run-001"
        / "attempts"
        / "attempt-001"
        / "artifacts"
    )
    assert attempt.status is RunStatus.CREATED


def test_attempt_record_tracks_optional_parent_attempt(tmp_path: Path):
    attempt = AttemptRecord.create(
        tmp_path,
        "run-001",
        "attempt-002",
        parent_attempt_id="attempt-001",
    )

    assert attempt.parent_attempt_id == "attempt-001"
