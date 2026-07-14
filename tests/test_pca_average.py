"""Tests for W3 PCA inputs, average-ear computation, and artifacts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SAMPLE_TAGS = ("S001_L", "S002_L", "S003_L")
FACES = np.array([[0, 1, 2], [0, 2, 3]], dtype=int)
BASE_POINTS = np.array([
    [0.0, 0.0, 0.0],
    [1.0, 0.0, 0.0],
    [1.0, 1.0, 0.0],
    [0.0, 1.0, 0.0],
])


def _write_input_fixture(tmp_path: Path) -> tuple[Path, Path]:
    aligned_dir = tmp_path / "aligned_weld_repaired"
    weld_dir = tmp_path / "weld_repaired"
    aligned_dir.mkdir(parents=True)
    weld_dir.mkdir(parents=True)

    alignment_rows = []
    for index, sample_tag in enumerate(SAMPLE_TAGS):
        points = BASE_POINTS.copy()
        points[:, 0] += (-2.0, 0.0, 2.0)[index]
        points[:, 1] += (0.0, 0.2, 0.0)[index]
        point_order = np.array([2, 0, 3, 1], dtype=int)
        pd.DataFrame({
            "global_vertex_id": point_order,
            "x": points[point_order, 0],
            "y": points[point_order, 1],
            "z": points[point_order, 2],
        }).to_csv(
            aligned_dir / f"{sample_tag}_aligned_whole_ear_points.csv", index=False
        )
        pd.DataFrame({
            "global_face_id": [1, 0],
            "global_v0": FACES[[1, 0], 0],
            "global_v1": FACES[[1, 0], 1],
            "global_v2": FACES[[1, 0], 2],
        }).to_csv(
            aligned_dir / f"{sample_tag}_aligned_whole_ear_faces.csv", index=False
        )
        pd.DataFrame([{
            "sample_tag": sample_tag,
            "status": "PASS",
            "pca_ready": True,
            "input_layer": "weld_repaired",
        }]).to_csv(weld_dir / f"{sample_tag}_weld_qc_summary.csv", index=False)
        alignment_rows.append({
            "sample_tag": sample_tag,
            "status": "PASS" if sample_tag != "S003_L" else "FAIL",
            "input_layer": "weld_repaired",
        })
    pd.DataFrame(alignment_rows).to_csv(aligned_dir / "alignment_qc_summary.csv", index=False)
    return aligned_dir, weld_dir


def test_load_pca_inputs_sorts_vertex_ids_and_records_exclusions(tmp_path: Path):
    from ear_param.pca_average import load_pca_inputs

    aligned_dir, weld_dir = _write_input_fixture(tmp_path)
    inputs = load_pca_inputs(aligned_dir, weld_dir)

    assert inputs.sample_tags == ("S001_L", "S002_L")
    assert inputs.vertex_ids.tolist() == [0, 1, 2, 3]
    np.testing.assert_allclose(inputs.points[0], BASE_POINTS + [-2.0, 0.0, 0.0])
    rejected = inputs.manifest.set_index("sample_tag").loc["S003_L"]
    assert not bool(rejected["included"])
    assert rejected["exclusion_reason"] == "alignment_status_not_pass"


def test_load_pca_inputs_rejects_non_repaired_weld_provenance(tmp_path: Path):
    from ear_param.pca_average import load_pca_inputs

    aligned_dir, weld_dir = _write_input_fixture(tmp_path)
    summary_path = weld_dir / "S002_L_weld_qc_summary.csv"
    summary = pd.read_csv(summary_path)
    summary.loc[0, "input_layer"] = "salvaged"
    summary.to_csv(summary_path, index=False)
    alignment = pd.read_csv(aligned_dir / "alignment_qc_summary.csv")
    alignment["status"] = "PASS"
    alignment.to_csv(aligned_dir / "alignment_qc_summary.csv", index=False)

    inputs = load_pca_inputs(aligned_dir, weld_dir)

    rejected = inputs.manifest.set_index("sample_tag").loc["S002_L"]
    assert not bool(rejected["included"])
    assert rejected["exclusion_reason"] == "weld_input_layer_not_repaired"


def test_load_pca_inputs_rejects_duplicate_vertex_ids(tmp_path: Path):
    from ear_param.pca_average import load_pca_inputs

    aligned_dir, weld_dir = _write_input_fixture(tmp_path)
    point_path = aligned_dir / "S002_L_aligned_whole_ear_points.csv"
    points = pd.read_csv(point_path)
    points.loc[0, "global_vertex_id"] = 0
    points.to_csv(point_path, index=False)

    with pytest.raises(ValueError, match="duplicate global_vertex_id"):
        load_pca_inputs(aligned_dir, weld_dir)


def test_load_pca_inputs_rejects_nonfinite_coordinates(tmp_path: Path):
    from ear_param.pca_average import load_pca_inputs

    aligned_dir, weld_dir = _write_input_fixture(tmp_path)
    point_path = aligned_dir / "S002_L_aligned_whole_ear_points.csv"
    points = pd.read_csv(point_path)
    points.loc[0, "x"] = np.nan
    points.to_csv(point_path, index=False)

    with pytest.raises(ValueError, match="non-finite coordinates"):
        load_pca_inputs(aligned_dir, weld_dir)


def test_load_pca_inputs_rejects_face_topology_difference(tmp_path: Path):
    from ear_param.pca_average import load_pca_inputs

    aligned_dir, weld_dir = _write_input_fixture(tmp_path)
    face_path = aligned_dir / "S002_L_aligned_whole_ear_faces.csv"
    faces = pd.read_csv(face_path)
    faces.loc[0, "global_v2"] = 1
    faces.to_csv(face_path, index=False)

    with pytest.raises(ValueError, match="global face topology mismatch"):
        load_pca_inputs(aligned_dir, weld_dir)


def test_load_pca_inputs_rejects_faces_referencing_missing_vertices(tmp_path: Path):
    from ear_param.pca_average import load_pca_inputs

    aligned_dir, weld_dir = _write_input_fixture(tmp_path)
    face_path = aligned_dir / "S002_L_aligned_whole_ear_faces.csv"
    faces = pd.read_csv(face_path)
    faces.loc[0, "global_v2"] = 99
    faces.to_csv(face_path, index=False)

    with pytest.raises(ValueError, match="faces reference missing vertices"):
        load_pca_inputs(aligned_dir, weld_dir)


def test_fit_pca_selects_smallest_component_count_reaching_threshold(tmp_path: Path):
    from ear_param.pca_average import fit_pca, load_pca_inputs

    aligned_dir, weld_dir = _write_input_fixture(tmp_path)
    alignment = pd.read_csv(aligned_dir / "alignment_qc_summary.csv")
    alignment["status"] = "PASS"
    alignment.to_csv(aligned_dir / "alignment_qc_summary.csv", index=False)
    inputs = load_pca_inputs(aligned_dir, weld_dir)

    result = fit_pca(inputs, variance_threshold=0.75)

    assert result.n_components_75 == 1
    np.testing.assert_allclose(result.mean_points, BASE_POINTS + [0.0, 1.0 / 15.0, 0.0])
    assert result.scores.shape == (3, 2)
    assert result.cumulative_explained_variance_ratio[0] >= 0.75


def test_write_pca_outputs_creates_mean_mesh_and_statistics(tmp_path: Path):
    from ear_param.pca_average import fit_pca, load_pca_inputs, write_pca_outputs

    aligned_dir, weld_dir = _write_input_fixture(tmp_path / "inputs")
    alignment = pd.read_csv(aligned_dir / "alignment_qc_summary.csv")
    alignment["status"] = "PASS"
    alignment.to_csv(aligned_dir / "alignment_qc_summary.csv", index=False)
    inputs = load_pca_inputs(aligned_dir, weld_dir)
    result = fit_pca(inputs, variance_threshold=0.75)
    out_dir = tmp_path / "pca"

    write_pca_outputs(inputs, result, out_dir, variance_threshold=0.75)

    assert (out_dir / "mean_whole_ear.ply").is_file()
    assert (out_dir / "mean_whole_ear_points.csv").is_file()
    assert (out_dir / "mean_whole_ear_faces.csv").is_file()
    assert (out_dir / "pca_input_manifest.csv").is_file()
    assert (out_dir / "explained_variance.csv").is_file()
    assert (out_dir / "components.npy").is_file()
    assert (out_dir / "pc_modes" / "PC01_plus_2sd.ply").is_file()
    scores = pd.read_csv(out_dir / "scores.csv")
    assert scores.columns.tolist() == ["sample_tag", "PC01", "PC02"]
