import json
from pathlib import Path

from desktop_app.models import AttemptRecord
from desktop_app.project_service import ProjectService
from desktop_app.recovery_service import RecoveryOption, RecoveryService


def failed_weld_attempt(tmp_path: Path) -> AttemptRecord:
    attempt = AttemptRecord.create(tmp_path / "project", "run-001", "attempt-001")
    salvaged = attempt.artifacts_dir / "remesh_r24" / "salvaged"
    salvaged.mkdir(parents=True)
    (attempt.artifacts_dir / "manifest.json").write_text(
        json.dumps({"status": "ERROR", "output_scope": "isolated", "outputs": {"salvaged_dir": "remesh_r24/salvaged"}}),
        encoding="utf-8",
    )
    return attempt


def test_recovery_creates_new_attempt_and_preserves_parent_artifacts(tmp_path: Path):
    parent = failed_weld_attempt(tmp_path)
    child = RecoveryService().create_attempt(parent, RecoveryOption.WELD)

    assert child.attempt_id != "attempt-001"
    assert not child.artifacts_dir.exists()
    assert child.parent_attempt_id == "attempt-001"
    assert parent.artifacts_dir.exists()


def test_recovery_hides_weld_when_salvaged_input_fails_integrity(tmp_path: Path):
    parent = failed_weld_attempt(tmp_path)
    (parent.artifacts_dir / "manifest.json").write_text(
        json.dumps({"status": "ERROR", "output_scope": "isolated", "outputs": {"salvaged_dir": "../outside"}}),
        encoding="utf-8",
    )

    assert RecoveryOption.WELD not in RecoveryService().plan(parent)


def test_weld_recovery_command_reads_parent_salvaged_and_writes_child_only(tmp_path: Path):
    parent = failed_weld_attempt(tmp_path)
    project = ProjectService().create(tmp_path / "workspace", "项目")
    project.config_dir.mkdir(parents=True)
    project.region_table_path.write_text("region_id,resolution\nR01,24\n", encoding="utf-8")
    child = RecoveryService().create_attempt(parent, RecoveryOption.WELD)

    command = RecoveryService().build_command(project, parent, child, RecoveryOption.WELD)

    assert command[0].endswith("build_whole_ear.py")
    assert command[command.index("--input_dir") + 1] == str(parent.artifacts_dir / "remesh_r24" / "salvaged")
    assert command[command.index("--out_dir") + 1] == str(child.artifacts_dir / "whole_ear_r24" / "weld_repaired")
