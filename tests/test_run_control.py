from __future__ import annotations

import json
from pathlib import Path
from threading import Thread
import time

import pandas as pd
import pytest

from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline
from ear_param.run_control import FileRunControl, RunCancelled


def _write_status(path: Path, status: str) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"status": status}), encoding="utf-8")
    temporary.replace(path)


def test_checkpoint_waits_until_desktop_marks_control_running(tmp_path: Path):
    control_path = tmp_path / "control.json"
    _write_status(control_path, "PAUSE_REQUESTED")

    def resume() -> None:
        time.sleep(0.01)
        _write_status(control_path, "RUNNING")

    thread = Thread(target=resume)
    thread.start()
    FileRunControl(control_path, poll_seconds=0.001).checkpoint()
    thread.join(timeout=1)

    assert not thread.is_alive()


def test_checkpoint_raises_when_desktop_requests_cancellation(tmp_path: Path):
    control_path = tmp_path / "control.json"
    _write_status(control_path, "CANCEL_REQUESTED")

    with pytest.raises(RunCancelled, match="cancelled"):
        FileRunControl(control_path).checkpoint()


def test_pipeline_calls_checkpoint_before_processing_a_ready_sample(tmp_path: Path):
    mesh_dir = tmp_path / "mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    (mesh_dir / "T001_L.ply").write_bytes(b"mesh")
    (landmarks_dir / "T001_L_landmarks.csv").write_text(
        "landmark_id,x,y,z\nL1,0,0,0\n",
        encoding="utf-8",
    )
    checkpoints: list[str] = []
    stages = StageFunctions(
        remesh_sample=lambda _: {"remesh": "PASS", "salvage": "FAIL"},
        remesh_qc=lambda _: "SKIPPED",
        weld_batch=lambda _: pd.DataFrame(),
        alignment_batch=lambda _: pd.DataFrame(),
        pca_batch=lambda: {"status": "PASS", "included_tags": []},
    )

    run_pipeline(
        PipelineConfig(
            mesh_dir=mesh_dir,
            landmarks_dir=landmarks_dir,
            checkpoint=lambda: checkpoints.append("hit"),
        ),
        stage_functions=stages,
    )

    assert checkpoints == ["hit", "hit"]
