import json
from pathlib import Path
from unittest.mock import patch

import pytest
import numpy as np
import pandas as pd


def test_create_run_manifest_records_inputs_parameters_and_outputs(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig
    from ear_param.run_artifacts import PipelineOutputLayout
    from ear_param.run_manifest import create_run_manifest, write_manifest

    mesh_dir = tmp_path / "data" / "clean_mesh"
    landmarks_dir = tmp_path / "data" / "landmarks"
    config_dir = tmp_path / "config"
    mesh_dir.mkdir(parents=True)
    landmarks_dir.mkdir(parents=True)
    config_dir.mkdir()
    (mesh_dir / "T076_L.ply").write_bytes(b"ply")
    (landmarks_dir / "T076_L_landmarks.csv").write_text(
        "landmark_id,x,y,z\nL7,0,0,0\n", encoding="utf-8"
    )
    regions = config_dir / "region_table.csv"
    regions.write_text(
        "region_id,lm_a,lm_b,lm_c,resolution\n"
        "T001,L1,L2,L3,12\n"
        "T002,L2,L3,L4,24\n",
        encoding="utf-8",
    )
    (config_dir / "edge_control_points.csv").write_text(
        "edge_start,edge_end,control_point\nL1,L2,M1\n", encoding="utf-8"
    )
    run_dir = tmp_path / "output" / "pipeline_runs" / "run_001"
    layout = PipelineOutputLayout.from_output_root(run_dir, reference_sample="T076_L")
    config = PipelineConfig(
        mesh_dir=mesh_dir,
        landmarks_dir=landmarks_dir,
        regions=regions,
        sample_tags=("T076_L",),
        reference_sample="T076_L",
        disable_side_normalization=False,
        max_salvage_unmapped_ratio=0.31,
        max_salvage_degenerate_ratio=0.012,
        pca_variance_threshold=0.8,
        **layout.pipeline_config_kwargs(),
    )

    manifest = create_run_manifest(
        config=config,
        run_dir=run_dir,
        output_root=run_dir,
        project_root=tmp_path,
        argv=["--reference-sample", "T076_L"],
    )
    write_manifest(run_dir / "manifest.json", manifest)
    saved = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert saved["schema_version"] == 1
    assert saved["status"] == "RUNNING"
    assert saved["run_id"] == "run_001"
    assert saved["parameters"]["reference_sample"] == "T076_L"
    assert saved["parameters"]["canonical_side"] == "L"
    assert saved["parameters"]["disable_side_normalization"] is False
    assert saved["parameters"]["region_resolution"] == {
        "region_count": 2,
        "unique_values": [12, 24],
        "by_region": {"T001": 12, "T002": 24},
    }
    assert saved["parameters"]["max_salvage_unmapped_ratio"] == 0.31
    assert saved["parameters"]["max_salvage_degenerate_ratio"] == 0.012
    assert saved["parameters"]["pca_variance_threshold"] == 0.8
    assert saved["parameters"]["raw_qc_policy"] == {
        "fail_unmapped_ratio": 0.2,
        "fail_on_any_degenerate_face": True,
        "warning_on_any_unmapped_point": True,
    }
    assert saved["inputs"][0]["sample_tag"] == "T076_L"
    assert saved["inputs"][0]["mesh"]["size_bytes"] == 3
    assert saved["config_files"]["region_table"]["exists"] is True
    assert saved["config_files"]["edge_control_points"]["exists"] is True
    assert saved["outputs"]["raw_dir"] == str(Path("parameterized_points_r24") / "raw")
    assert saved["outputs"]["reference_pca_dir"] == "pca_reference_T076_L_r24"
    assert saved["runtime"]["python"]
    assert saved["code"]["commit"]


def test_create_run_manifest_makes_legacy_outputs_project_relative_when_possible(
    tmp_path: Path,
):
    from ear_param.pipeline import PipelineConfig
    from ear_param.run_artifacts import PipelineOutputLayout
    from ear_param.run_manifest import create_run_manifest

    project_root = tmp_path / "project"
    mesh_dir = project_root / "data" / "clean_mesh"
    landmarks_dir = project_root / "data" / "landmarks"
    config_dir = project_root / "config"
    mesh_dir.mkdir(parents=True)
    landmarks_dir.mkdir(parents=True)
    config_dir.mkdir()
    regions = config_dir / "region_table.csv"
    regions.write_text(
        "region_id,lm_a,lm_b,lm_c,resolution\nT001,L1,L2,L3,24\n",
        encoding="utf-8",
    )
    layout = PipelineOutputLayout.from_output_root(project_root / "legacy_outputs")
    output_paths = layout.pipeline_config_kwargs()
    output_paths["raw_dir"] = tmp_path / "outside_project" / "raw"
    config = PipelineConfig(
        mesh_dir=mesh_dir,
        landmarks_dir=landmarks_dir,
        regions=regions,
        **output_paths,
    )

    manifest = create_run_manifest(
        config=config,
        run_dir=project_root / "output" / "pipeline_runs" / "run_legacy",
        output_root=None,
        project_root=project_root,
        argv=[],
    )

    assert manifest["outputs"]["weld_dir"] == str(
        Path("legacy_outputs") / "whole_ear_r24" / "weld_repaired"
    )
    assert manifest["outputs"]["raw_dir"] == str(
        (tmp_path / "outside_project" / "raw").resolve()
    )


def test_create_run_manifest_reads_gbk_region_table(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig
    from ear_param.run_manifest import create_run_manifest

    regions = tmp_path / "region_table_gbk.csv"
    regions.write_bytes(
        (
            "region_id,region_name,resolution\n"
            "T001,耳甲腔,12\n"
            "T002,耳轮,24\n"
        ).encode("gbk")
    )
    config = PipelineConfig(
        mesh_dir=tmp_path / "clean_mesh",
        landmarks_dir=tmp_path / "landmarks",
        regions=regions,
    )

    manifest = create_run_manifest(
        config=config,
        run_dir=tmp_path / "run_gbk",
        output_root=None,
        project_root=tmp_path,
        argv=[],
    )

    assert manifest["parameters"]["region_resolution"] == {
        "region_count": 2,
        "unique_values": [12, 24],
        "by_region": {"T001": 12, "T002": 24},
    }


def test_git_code_state_falls_back_when_git_is_unavailable(tmp_path: Path):
    from ear_param.run_manifest import _git_code_state

    with patch(
        "ear_param.run_manifest.subprocess.run",
        side_effect=FileNotFoundError("git is unavailable"),
    ):
        state = _git_code_state(tmp_path)

    assert state == {"commit": "unknown", "dirty": False}


def test_write_manifest_rejects_nonfinite_float_values(tmp_path: Path):
    from ear_param.run_manifest import write_manifest

    with pytest.raises(ValueError):
        write_manifest(tmp_path / "manifest.json", {"value": float("nan")})


def test_finish_manifest_records_completed_pipeline_summary(tmp_path: Path):
    from ear_param.pipeline import PipelineResult
    from ear_param.run_manifest import finish_manifest, write_manifest

    path = tmp_path / "manifest.json"
    write_manifest(path, {
        "status": "RUNNING", "finished_at": None, "result": None, "error": ""
    })
    result = PipelineResult(
        records=pd.DataFrame({
            "discovery": ["READY", "READY"],
            "salvage": ["PASS", "FAIL"],
            "weld": ["PASS", "SKIPPED"],
            "alignment": ["PASS", "SKIPPED"],
            "pca_included": ["YES", "NO"],
            "reference_alignment": ["PASS", "SKIPPED"],
            "reference_pca_included": ["YES", "NO"],
        }),
        pca_status="PASS",
        pca_result={
            "retained_component_count": 3,
            "explained_variance": float("nan"),
            "component_values": np.array([np.int64(3), np.nan]),
        },
        reference_pca_status="PASS",
        reference_pca_result={"retained_component_count": 3},
    )

    saved = finish_manifest(path, status="COMPLETED", result=result)

    assert saved["status"] == "COMPLETED"
    assert saved["finished_at"]
    assert saved["result"]["sample_count"] == 2
    assert saved["result"]["salvage_pass_count"] == 1
    assert saved["result"]["pca_included_count"] == 1
    assert saved["result"]["pca_status"] == "PASS"
    assert saved["result"]["pca_result"]["explained_variance"] is None
    assert saved["result"]["pca_result"]["component_values"] == [3, None]
    assert json.loads(path.read_text(encoding="utf-8"))["result"]["pca_result"]["explained_variance"] is None


def test_finish_manifest_records_top_level_error(tmp_path: Path):
    from ear_param.run_manifest import finish_manifest, write_manifest

    path = tmp_path / "manifest.json"
    write_manifest(path, {
        "status": "RUNNING", "finished_at": None, "result": None, "error": ""
    })

    saved = finish_manifest(path, status="ERROR", error="pipeline exploded")

    assert saved["status"] == "ERROR"
    assert saved["error"] == "pipeline exploded"
    assert saved["finished_at"]
