from __future__ import annotations

import json
from pathlib import Path

from desktop_app.models import RunOptions, RunStatus
from desktop_app.project_service import ProjectService
from desktop_app.run_controller import RunController


class FakeProcess:
    def __init__(self) -> None:
        self.program = ""
        self.arguments: list[str] = []
        self.working_directory = ""
        self.started = False

    def setProgram(self, program: str) -> None:
        self.program = program

    def setArguments(self, arguments: list[str]) -> None:
        self.arguments = arguments

    def setWorkingDirectory(self, path: str) -> None:
        self.working_directory = path

    def start(self) -> None:
        self.started = True


def _project(tmp_path: Path):
    project = ProjectService().create(tmp_path / "project", "项目")
    project.mesh_dir.mkdir(parents=True)
    project.landmarks_dir.mkdir(parents=True)
    project.config_dir.mkdir(parents=True)
    project.region_table_path.write_text(
        "region_id,lm_a,lm_b,lm_c,resolution\nT001,L1,L2,L3,24\n",
        encoding="utf-8",
    )
    return project


def test_start_uses_only_project_scoped_paths_and_empty_artifacts(tmp_path: Path):
    controller = RunController(process_factory=FakeProcess)
    attempt = controller.start(_project(tmp_path), RunOptions())

    assert attempt.status is RunStatus.RUNNING
    assert "--output-root" in controller.last_command
    assert str(attempt.artifacts_dir) in controller.last_command
    assert not attempt.artifacts_dir.exists()
    assert controller.process.started
    assert controller.process.working_directory == str(attempt.project_root)


def test_pause_resume_cancel_write_atomic_control_status(tmp_path: Path):
    controller = RunController(process_factory=FakeProcess)
    controller.start(_project(tmp_path), RunOptions())

    controller.request_pause()
    assert controller.active_attempt.status is RunStatus.PAUSE_REQUESTED
    assert json.loads(controller.control_path.read_text(encoding="utf-8"))["status"] == "PAUSE_REQUESTED"
    controller.resume()
    assert json.loads(controller.control_path.read_text(encoding="utf-8"))["status"] == "RUNNING"
    controller.cancel()
    assert json.loads(controller.control_path.read_text(encoding="utf-8"))["status"] == "CANCEL_REQUESTED"


def test_refresh_terminal_status_requires_manifest_and_maps_completed(tmp_path: Path):
    controller = RunController(process_factory=FakeProcess)
    attempt = controller.start(_project(tmp_path), RunOptions())

    assert controller.refresh_terminal_status() is attempt
    attempt.artifacts_dir.mkdir()
    (attempt.artifacts_dir / "manifest.json").write_text(
        '{"status":"COMPLETED"}', encoding="utf-8"
    )

    completed = controller.refresh_terminal_status()

    assert completed.status is RunStatus.COMPLETED


def test_read_new_events_returns_each_jsonl_event_once(tmp_path: Path):
    controller = RunController(process_factory=FakeProcess)
    controller.start(_project(tmp_path), RunOptions())
    controller.event_path.write_text(
        '{"event":"stage_started","stage":"REMESH"}\n',
        encoding="utf-8",
    )

    assert controller.read_new_events() == [{"event": "stage_started", "stage": "REMESH"}]
    assert controller.read_new_events() == []


def test_read_new_events_waits_for_a_complete_final_jsonl_line(tmp_path: Path):
    controller = RunController(process_factory=FakeProcess)
    controller.start(_project(tmp_path), RunOptions())
    controller.event_path.write_text('{"event":"stage_started"', encoding="utf-8")

    assert controller.read_new_events() == []

    with controller.event_path.open("a", encoding="utf-8") as stream:
        stream.write(',"stage":"REMESH"}\n')
    assert controller.read_new_events() == [{"event": "stage_started", "stage": "REMESH"}]


def test_start_recovery_runs_weld_from_parent_artifacts_only(tmp_path: Path):
    from desktop_app.models import AttemptRecord
    from desktop_app.recovery_service import RecoveryOption

    project = _project(tmp_path)
    parent = AttemptRecord.create(project.root, "run-parent", "attempt-001")
    parent_salvaged = parent.artifacts_dir / "remesh_r24" / "salvaged"
    parent_salvaged.mkdir(parents=True)
    (parent.artifacts_dir / "manifest.json").write_text(
        '{"status":"ERROR","output_scope":"isolated","outputs":{"salvaged_dir":"remesh_r24/salvaged"}}',
        encoding="utf-8",
    )
    controller = RunController(process_factory=FakeProcess)

    child = controller.start_recovery(project, parent, RecoveryOption.WELD)

    assert child.parent_attempt_id == parent.attempt_id
    assert str(parent_salvaged) in controller.last_command
    assert str(child.artifacts_dir / "whole_ear_r24" / "weld_repaired") in controller.last_command
    assert controller.process.started

    controller._finish_recovery(1)

    manifest = json.loads((child.artifacts_dir / "manifest.json").read_text(encoding="utf-8"))
    assert controller.active_attempt.status is RunStatus.FAILED
    assert manifest["status"] == "ERROR"
    assert manifest["recovery"]["parent_attempt"] == parent.attempt_id
