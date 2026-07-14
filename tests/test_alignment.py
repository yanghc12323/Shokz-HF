"""Tests for rigid whole-ear alignment."""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path
import subprocess
import sys
from uuid import uuid4


def _landmarks() -> np.ndarray:
    return np.array([
        [0.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
        [0.0, 3.0, 0.0],
        [0.5, 0.5, 2.0],
    ])


def _rotation_z(angle: float) -> np.ndarray:
    cosine = np.cos(angle)
    sine = np.sin(angle)
    return np.array([
        [cosine, -sine, 0.0],
        [sine, cosine, 0.0],
        [0.0, 0.0, 1.0],
    ])


def test_rigid_kabsch_recovers_known_rotation_and_translation():
    from ear_param.alignment import apply_rigid_transform, rigid_kabsch

    source = _landmarks()
    rotation = _rotation_z(np.deg2rad(37.0))
    translation = np.array([4.0, -3.0, 2.5])
    target = (rotation @ source.T).T + translation

    transform = rigid_kabsch(source, target)
    aligned = apply_rigid_transform(source, transform)

    np.testing.assert_allclose(aligned, target, atol=1e-10)
    np.testing.assert_allclose(transform.rotation, rotation, atol=1e-10)
    np.testing.assert_allclose(transform.translation, translation, atol=1e-10)
    assert np.linalg.det(transform.rotation) == pytest.approx(1.0)


def test_rigid_kabsch_does_not_turn_a_reflection_into_rotation():
    from ear_param.alignment import apply_rigid_transform, rigid_kabsch

    source = _landmarks()
    target = source.copy()
    target[:, 0] *= -1.0

    transform = rigid_kabsch(source, target)
    aligned = apply_rigid_transform(source, transform)

    assert np.linalg.det(transform.rotation) == pytest.approx(1.0)
    assert np.max(np.linalg.norm(aligned - target, axis=1)) > 0.1


def test_rigid_kabsch_rejects_collinear_landmarks():
    from ear_param.alignment import rigid_kabsch

    source = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])

    with pytest.raises(ValueError, match="collinear"):
        rigid_kabsch(source, source)


def test_generalized_procrustes_aligns_samples_without_changing_size():
    from ear_param.alignment import generalized_procrustes

    base = _landmarks()
    sample_sets = {
        "S1_L": base,
        "S2_L": (_rotation_z(0.6) @ base.T).T + np.array([3.0, -2.0, 4.0]),
        "S3_L": (_rotation_z(-0.8) @ base.T).T + np.array([-5.0, 1.0, -3.0]),
    }

    result = generalized_procrustes(sample_sets, tolerance=1e-10, max_iterations=20)

    assert result.converged
    assert result.iterations <= 20
    for aligned in result.aligned_landmarks.values():
        np.testing.assert_allclose(aligned, result.mean_landmarks, atol=1e-9)
    original_distance = np.linalg.norm(sample_sets["S2_L"][0] - sample_sets["S2_L"][1])
    aligned_distance = np.linalg.norm(
        result.aligned_landmarks["S2_L"][0] - result.aligned_landmarks["S2_L"][1]
    )
    assert aligned_distance == pytest.approx(original_distance)


def test_fixed_reference_alignment_maps_every_sample_to_named_reference():
    from ear_param.alignment import fixed_reference_alignment

    reference = _landmarks()
    rotation = _rotation_z(0.55)
    translated = (rotation @ reference.T).T + np.array([3.0, -2.5, 1.0])
    sample_sets = {"REF_L": reference, "MOVING_L": translated}

    result = fixed_reference_alignment(sample_sets, reference_sample="REF_L")

    np.testing.assert_allclose(result.reference_landmarks, reference, atol=1e-10)
    for aligned in result.aligned_landmarks.values():
        np.testing.assert_allclose(aligned, reference, atol=1e-10)
    assert result.transforms["REF_L"].rms_residual == pytest.approx(0.0, abs=1e-10)
    assert np.linalg.det(result.transforms["MOVING_L"].rotation) == pytest.approx(1.0)


def test_alignment_status_requires_gpa_convergence():
    from scripts.align_whole_ear import _alignment_status

    assert _alignment_status(True, 1.0, 1e-14) == "PASS"
    assert _alignment_status(False, 1.0, 1e-14) == "FAIL"


def test_discover_pca_ready_samples_requires_pass_and_strict_true():
    from scripts.align_whole_ear import _discover_pca_ready_samples

    whole_dir = Path(".test_artifacts") / "alignment_gate" / uuid4().hex
    whole_dir.mkdir(parents=True, exist_ok=True)
    summaries = {
        "PASS_L": {"status": "PASS", "pca_ready": True},
        "FAIL_L": {"status": "FAIL", "pca_ready": True},
        "NAN_L": {"status": "PASS", "pca_ready": np.nan},
        "FALSE_L": {"status": "PASS", "pca_ready": False},
    }
    for sample_tag, values in summaries.items():
        pd.DataFrame([values]).to_csv(
            whole_dir / f"{sample_tag}_weld_qc_summary.csv", index=False
        )

    assert _discover_pca_ready_samples(whole_dir) == ["PASS_L"]


def test_load_input_layer_rejects_blank_values():
    from scripts.align_whole_ear import _load_input_layer

    path = Path(".test_artifacts") / "alignment_layer" / uuid4().hex / "summary.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"input_layer": [" "]}).to_csv(path, index=False)

    with pytest.raises(SystemExit, match="non-empty input_layer"):
        _load_input_layer(path)


def test_align_whole_ear_cli_exports_aligned_pca_ready_samples():
    work_dir = Path(".test_artifacts") / "alignment_cli" / uuid4().hex
    whole_dir = work_dir / "whole"
    landmarks_dir = work_dir / "landmarks"
    out_dir = work_dir / "aligned"
    whole_dir.mkdir(parents=True, exist_ok=True)
    landmarks_dir.mkdir(parents=True, exist_ok=True)

    base = _landmarks()
    rotation = _rotation_z(0.7)
    translation = np.array([4.0, -2.0, 3.0])
    sample_points = {
        "S1_L": base,
        "S2_L": (rotation @ base.T).T + translation,
    }
    faces = pd.DataFrame({
        "global_face_id": [0, 1],
        "global_v0": [0, 0],
        "global_v1": [1, 2],
        "global_v2": [2, 3],
    })
    landmark_ids = ["L7", "L13", "L15", "L26"]
    for sample_tag, xyz in sample_points.items():
        sample_id, side = sample_tag.split("_")
        pd.DataFrame({
            "sample_id": sample_id,
            "side": side,
            "global_vertex_id": range(len(xyz)),
            "x": xyz[:, 0],
            "y": xyz[:, 1],
            "z": xyz[:, 2],
        }).to_csv(whole_dir / f"{sample_tag}_whole_ear_points.csv", index=False)
        faces.assign(sample_id=sample_id, side=side).to_csv(
            whole_dir / f"{sample_tag}_whole_ear_faces.csv", index=False
        )
        pd.DataFrame({
            "sample_id": [sample_id],
            "side": [side],
            "input_layer": ["weld_repaired"],
            "status": ["PASS"],
            "pca_ready": [True],
        }).to_csv(whole_dir / f"{sample_tag}_weld_qc_summary.csv", index=False)
        pd.DataFrame({
            "landmark_id": landmark_ids,
            "x": xyz[:, 0],
            "y": xyz[:, 1],
            "z": xyz[:, 2],
        }).to_csv(landmarks_dir / f"{sample_tag}_landmarks.csv", index=False)

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/align_whole_ear.py",
            "--whole_ear_dir",
            str(whole_dir),
            "--landmarks_dir",
            str(landmarks_dir),
            "--out_dir",
            str(out_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert (out_dir / "generalized_procrustes_reference_landmarks.csv").exists()
    assert (out_dir / "rigid_transforms.csv").exists()
    assert (out_dir / "alignment_qc_summary.csv").exists()
    assert (out_dir / "alignment_qc_overlay.png").exists()
    aligned_1 = pd.read_csv(out_dir / "S1_L_aligned_whole_ear_points.csv")
    aligned_2 = pd.read_csv(out_dir / "S2_L_aligned_whole_ear_points.csv")
    np.testing.assert_allclose(
        aligned_1[["x", "y", "z"]],
        aligned_2[["x", "y", "z"]],
        atol=1e-9,
    )
    assert (out_dir / "S1_L_aligned_whole_ear.ply").exists()
    assert (out_dir / "S2_L_aligned_whole_ear.ply").exists()
    summary = pd.read_csv(out_dir / "alignment_qc_summary.csv")
    assert set(summary["input_layer"]) == {"weld_repaired"}

    pd.DataFrame({
        "sample_id": ["S2"],
        "side": ["L"],
        "input_layer": ["salvaged"],
        "status": ["PASS"],
        "pca_ready": [True],
    }).to_csv(whole_dir / "S2_L_weld_qc_summary.csv", index=False)
    mixed = subprocess.run(
        [
            sys.executable,
            "scripts/align_whole_ear.py",
            "--whole_ear_dir",
            str(whole_dir),
            "--landmarks_dir",
            str(landmarks_dir),
            "--out_dir",
            str(work_dir / "mixed_aligned"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert mixed.returncode != 0
    assert "one whole-ear input layer" in mixed.stderr


def test_align_whole_ear_cli_exports_fixed_reference_alignment():
    work_dir = Path(".test_artifacts") / "fixed_reference_cli" / uuid4().hex
    whole_dir = work_dir / "whole"
    landmarks_dir = work_dir / "landmarks"
    out_dir = work_dir / "aligned_reference"
    whole_dir.mkdir(parents=True, exist_ok=True)
    landmarks_dir.mkdir(parents=True, exist_ok=True)

    reference = _landmarks()
    transformed = (_rotation_z(0.7) @ reference.T).T + np.array([4.0, -2.0, 3.0])
    faces = pd.DataFrame({
        "global_face_id": [0, 1],
        "global_v0": [0, 0],
        "global_v1": [1, 2],
        "global_v2": [2, 3],
    })
    landmark_ids = ["L7", "L13", "L15", "L26"]
    for sample_tag, xyz in {"REF_L": reference, "MOVING_L": transformed}.items():
        sample_id, side = sample_tag.split("_")
        pd.DataFrame({
            "sample_id": sample_id,
            "side": side,
            "global_vertex_id": range(len(xyz)),
            "x": xyz[:, 0],
            "y": xyz[:, 1],
            "z": xyz[:, 2],
        }).to_csv(whole_dir / f"{sample_tag}_whole_ear_points.csv", index=False)
        faces.assign(sample_id=sample_id, side=side).to_csv(
            whole_dir / f"{sample_tag}_whole_ear_faces.csv", index=False
        )
        pd.DataFrame({
            "sample_id": [sample_id],
            "side": [side],
            "input_layer": ["weld_repaired"],
            "status": ["PASS"],
            "pca_ready": [True],
        }).to_csv(whole_dir / f"{sample_tag}_weld_qc_summary.csv", index=False)
        pd.DataFrame({
            "landmark_id": landmark_ids,
            "x": xyz[:, 0],
            "y": xyz[:, 1],
            "z": xyz[:, 2],
        }).to_csv(landmarks_dir / f"{sample_tag}_landmarks.csv", index=False)

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/align_whole_ear.py",
            "--whole_ear_dir", str(whole_dir),
            "--landmarks_dir", str(landmarks_dir),
            "--out_dir", str(out_dir),
            "--alignment_mode", "fixed_reference",
            "--reference_sample", "REF_L",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert (out_dir / "fixed_reference_landmarks.csv").exists()
    summary = pd.read_csv(out_dir / "alignment_qc_summary.csv")
    assert set(summary["alignment_method"]) == {"FIXED_REFERENCE"}
    assert set(summary["reference_sample"]) == {"REF_L"}
    aligned = pd.read_csv(out_dir / "MOVING_L_aligned_whole_ear_points.csv")
    np.testing.assert_allclose(aligned[["x", "y", "z"]], reference, atol=1e-9)
    assert (out_dir / "MOVING_L_aligned_whole_ear.obj").exists()
    assert (out_dir / "MOVING_L_aligned_whole_ear.stl").exists()
