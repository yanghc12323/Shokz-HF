"""Tests for the formal end-to-end batch pipeline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import trimesh


def test_discover_samples_records_ready_and_missing_pairs(tmp_path: Path):
    from ear_param.pipeline import discover_samples

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    (mesh_dir / "T001_L.ply").write_text("mesh placeholder")
    (mesh_dir / "T002_L.ply").write_text("mesh placeholder")
    (landmarks_dir / "T001_L_landmarks.csv").write_text("landmark_id,x,y,z\n")
    (landmarks_dir / "T003_L_landmarks.csv").write_text("landmark_id,x,y,z\n")

    discovered = discover_samples(mesh_dir, landmarks_dir).set_index("sample_tag")

    assert discovered.loc["T001_L", "discovery"] == "READY"
    assert discovered.loc["T002_L", "discovery"] == "MISSING_LANDMARKS"
    assert discovered.loc["T003_L", "discovery"] == "MISSING_MESH"
    assert discovered.loc["T002_L", "reason"] == "missing_landmarks"
    assert discovered.loc["T003_L", "reason"] == "missing_mesh"


def test_pipeline_continues_after_one_sample_remesh_error(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    for sample_tag in ("T001_L", "T002_L"):
        (mesh_dir / f"{sample_tag}.ply").write_text("mesh placeholder")
        (landmarks_dir / f"{sample_tag}_landmarks.csv").write_text("landmark_id,x,y,z\n")

    processed: list[str] = []

    def remesh_sample(sample_tag: str) -> dict[str, str]:
        processed.append(sample_tag)
        if sample_tag == "T001_L":
            raise RuntimeError("bad landmarks")
        return {"remesh": "PASS", "salvage": "PASS"}

    def remesh_qc(sample_tag: str) -> str:
        return "PASS"

    stages = StageFunctions(
        remesh_sample=remesh_sample,
        remesh_qc=remesh_qc,
        weld_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status", "pca_ready"]),
        alignment_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status"]),
        pca_batch=lambda: {"status": "PASS", "included_tags": []},
    )
    result = run_pipeline(
        PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir),
        stage_functions=stages,
    )

    records = result.records.set_index("sample_tag")
    assert processed == ["T001_L", "T002_L"]
    assert records.loc["T001_L", "remesh"] == "ERROR"
    assert records.loc["T001_L", "salvage"] == "SKIPPED"
    assert records.loc["T002_L", "remesh"] == "PASS"
    assert records.loc["T002_L", "remesh_qc"] == "PASS"


def test_pipeline_allows_raw_remesh_warning_when_salvage_passes(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    for sample_tag in ("T001_L", "T002_L"):
        (mesh_dir / f"{sample_tag}.ply").write_text("mesh placeholder")
        (landmarks_dir / f"{sample_tag}_landmarks.csv").write_text("landmark_id,x,y,z\n")

    stages = StageFunctions(
        remesh_sample=lambda tag: {"remesh": "WARNING", "salvage": "PASS"},
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame({
            "sample_tag": tags,
            "status": ["PASS", "PASS"],
            "pca_ready": [True, True],
        }),
        alignment_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": ["PASS", "PASS"]}),
        pca_batch=lambda: {"status": "PASS", "included_tags": ["T001_L", "T002_L"]},
    )

    result = run_pipeline(
        PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir),
        stage_functions=stages,
    )

    records = result.records.set_index("sample_tag")
    assert records.loc["T001_L", "remesh"] == "WARNING"
    assert records.loc["T001_L", "remesh_qc"] == "PASS"
    assert records.loc["T001_L", "weld"] == "PASS"
    assert records.loc["T001_L", "alignment"] == "PASS"
    assert records.loc["T001_L", "pca_included"] == "YES"


def test_pipeline_visualizes_remesh_qc_when_salvage_fails(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    (mesh_dir / "T001_L.ply").write_text("mesh placeholder")
    (landmarks_dir / "T001_L_landmarks.csv").write_text("landmark_id,x,y,z\n")

    visualized: list[str] = []
    stages = StageFunctions(
        remesh_sample=lambda tag: {"remesh": "FAIL", "salvage": "FAIL"},
        remesh_qc=lambda tag: visualized.append(tag) or "FAIL",
        weld_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status", "pca_ready"]),
        alignment_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status"]),
        pca_batch=lambda: {"status": "PASS", "included_tags": []},
    )

    result = run_pipeline(
        PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir),
        stage_functions=stages,
    )

    record = result.records.iloc[0]
    assert visualized == ["T001_L"]
    assert record["salvage"] == "FAIL"
    assert record["remesh_qc"] == "FAIL"
    assert record["weld"] == "SKIPPED"


def test_pipeline_writes_summary_and_skips_pca_under_two_aligned_samples(tmp_path: Path):
    from ear_param.pipeline import (
        PipelineConfig,
        StageFunctions,
        run_pipeline,
        write_pipeline_outputs,
    )

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    (mesh_dir / "T001_L.ply").write_text("mesh placeholder")
    (landmarks_dir / "T001_L_landmarks.csv").write_text("landmark_id,x,y,z\n")

    stages = StageFunctions(
        remesh_sample=lambda tag: {"remesh": "PASS", "salvage": "PASS"},
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame({
            "sample_tag": tags,
            "status": ["PASS"],
            "pca_ready": [True],
        }),
        alignment_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": ["PASS"]}),
        pca_batch=lambda: {"status": "PASS", "included_tags": ["T001_L"]},
    )
    result = run_pipeline(
        PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir),
        stage_functions=stages,
    )
    run_dir = tmp_path / "pipeline_run"

    write_pipeline_outputs(result, run_dir)

    assert result.pca_status == "SKIPPED_INSUFFICIENT_SAMPLES"
    assert (run_dir / "pipeline_batch_summary.csv").is_file()
    assert (run_dir / "pipeline_run_summary.csv").is_file()
    assert (run_dir / "pipeline_run.log").is_file()


def test_pipeline_records_right_sample_canonicalization(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir, landmarks_dir = tmp_path / "clean_mesh", tmp_path / "landmarks"
    mesh_dir.mkdir(); landmarks_dir.mkdir()
    trimesh.Trimesh(vertices=[[1, 0, 0], [0, 1, 0], [0, 0, 1]], faces=[[0, 1, 2]], process=False).export(mesh_dir / "T001_R.ply")
    pd.DataFrame({"landmark_id": ["L7"], "x": [1.], "y": [0.], "z": [0.]}).to_csv(landmarks_dir / "T001_R_landmarks.csv", index=False)
    stages = StageFunctions(lambda tag: {"remesh": "PASS", "salvage": "FAIL"}, lambda tag: "PASS", lambda tags: pd.DataFrame(), lambda tags: pd.DataFrame(), lambda: {})

    result = run_pipeline(PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir, canonical_dir=tmp_path / "canonical", disable_side_normalization=False), stage_functions=stages)

    record = result.records.iloc[0]
    assert record["source_side"] == "R"
    assert record["canonical_side"] == "L"
    assert bool(record["mirrored"])


def test_pipeline_runs_isolated_fixed_reference_pca_branch(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir, landmarks_dir = tmp_path / "clean_mesh", tmp_path / "landmarks"
    mesh_dir.mkdir(); landmarks_dir.mkdir()
    for sample_tag in ("T001_L", "T002_L"):
        (mesh_dir / f"{sample_tag}.ply").write_text("mesh placeholder")
        (landmarks_dir / f"{sample_tag}_landmarks.csv").write_text("landmark_id,x,y,z\n")

    calls: list[tuple[str, object]] = []
    stages = StageFunctions(
        remesh_sample=lambda tag: {"remesh": "PASS", "salvage": "PASS"},
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": "PASS", "pca_ready": True}),
        alignment_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": "PASS"}),
        pca_batch=lambda: {"status": "PASS", "included_tags": ["T001_L", "T002_L"]},
        fixed_reference_alignment_batch=lambda tags, reference: (
            calls.append(("alignment", (tags, reference)))
            or pd.DataFrame({"sample_tag": tags, "status": "PASS"})
        ),
        fixed_reference_pca_batch=lambda: (
            calls.append(("pca", None))
            or {"status": "PASS", "included_tags": ["T001_L", "T002_L"]}
        ),
    )

    result = run_pipeline(
        PipelineConfig(
            mesh_dir=mesh_dir,
            landmarks_dir=landmarks_dir,
            reference_sample="T001_L",
        ),
        stage_functions=stages,
    )

    records = result.records.set_index("sample_tag")
    assert calls == [
        ("alignment", (["T001_L", "T002_L"], "T001_L")),
        ("pca", None),
    ]
    assert records.loc["T001_L", "alignment"] == "PASS"
    assert records.loc["T001_L", "reference_alignment"] == "PASS"
    assert records.loc["T001_L", "pca_included"] == "YES"
    assert records.loc["T001_L", "reference_pca_included"] == "YES"
    assert result.pca_status == "PASS"
    assert result.reference_pca_status == "PASS"
