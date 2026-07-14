"""Tests for left-canonical ear input normalization."""

from __future__ import annotations

import numpy as np
import pandas as pd
import trimesh


def test_right_sample_is_mirrored_and_faces_are_reversed(tmp_path):
    from ear_param.canonicalization import canonicalize_sample

    mesh = trimesh.Trimesh(
        vertices=np.array([[1., 2., 3.], [4., 5., 6.], [7., 8., 9.]]),
        faces=np.array([[0, 1, 2]]), process=False,
    )
    mesh_path = tmp_path / "S001_R.ply"
    mesh.export(mesh_path)
    landmark_path = tmp_path / "S001_R_landmarks.csv"
    pd.DataFrame({"landmark_id": ["L7"], "x": [1.], "y": [2.], "z": [3.]}).to_csv(landmark_path, index=False)

    result = canonicalize_sample("S001_R", mesh_path, landmark_path, tmp_path / "out")

    assert result.mirrored is True
    assert result.canonical_side == "L"
    np.testing.assert_allclose(result.mesh.vertices[:, 0], [-1., -4., -7.])
    np.testing.assert_array_equal(result.mesh.faces, [[2, 1, 0]])
    assert result.landmarks.loc[0, "x"] == -1.


def test_left_sample_is_unchanged(tmp_path):
    from ear_param.canonicalization import canonicalize_sample

    mesh = trimesh.Trimesh(vertices=[[1, 2, 3], [4, 5, 6], [7, 8, 9]], faces=[[0, 1, 2]], process=False)
    mesh_path = tmp_path / "S001_L.ply"
    mesh.export(mesh_path)
    landmark_path = tmp_path / "S001_L_landmarks.csv"
    pd.DataFrame({"landmark_id": ["L7"], "x": [1.], "y": [2.], "z": [3.]}).to_csv(landmark_path, index=False)

    result = canonicalize_sample("S001_L", mesh_path, landmark_path, tmp_path / "out")

    assert result.mirrored is False
    np.testing.assert_allclose(result.mesh.vertices, mesh.vertices)
    np.testing.assert_array_equal(result.mesh.faces, mesh.faces)
