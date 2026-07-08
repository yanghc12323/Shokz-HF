#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for patch-based remesh building blocks."""

import numpy as np
import pandas as pd
import pytest
import trimesh

import ear_param.remesh as remesh
from ear_param.remesh import (
    build_mesh_adjacency,
    build_region_remesh,
    build_region_remesh_mesh,
    build_triangle_boundary_paths,
    compute_region_feature_values,
    extract_patch_faces,
    harmonic_parameterize_patch,
    locate_uv_samples_in_faces,
    make_subdivision_template,
    map_samples_to_3d,
    snap_landmarks_to_vertices,
)


@pytest.fixture
def single_triangle_mesh() -> trimesh.Trimesh:
    vertices = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ])
    faces = np.array([[0, 1, 2]])
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


@pytest.fixture
def center_patch_mesh() -> trimesh.Trimesh:
    vertices = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.35, 0.30, 0.0],
    ])
    faces = np.array([
        [0, 1, 3],
        [1, 2, 3],
        [2, 0, 3],
    ])
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


@pytest.fixture
def split_patch_mesh() -> trimesh.Trimesh:
    vertices = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [1.2, -0.2, 0.0],
        [1.2, 1.2, 0.0],
        [-0.2, 1.2, 0.0],
    ])
    faces = np.array([
        [0, 1, 2],
        [0, 3, 1],
        [1, 3, 4],
        [1, 4, 2],
        [2, 4, 5],
        [2, 5, 0],
        [0, 5, 3],
    ])
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


@pytest.fixture
def triangle_landmarks() -> pd.DataFrame:
    return pd.DataFrame([
        {"landmark_id": "L10", "x": 0.01, "y": 0.01, "z": 0.0},
        {"landmark_id": "L20", "x": 0.99, "y": 0.02, "z": 0.0},
        {"landmark_id": "L30", "x": 0.02, "y": 0.98, "z": 0.0},
    ]).set_index("landmark_id")


def test_snap_landmarks_to_vertices_returns_nearest_vertex_ids(
    single_triangle_mesh, triangle_landmarks
):
    snapped = snap_landmarks_to_vertices(
        single_triangle_mesh, triangle_landmarks, ["L10", "L20", "L30"]
    )

    assert snapped["L10"].vertex_id == 0
    assert snapped["L20"].vertex_id == 1
    assert snapped["L30"].vertex_id == 2
    assert snapped["L10"].distance < 0.02


def test_boundary_paths_follow_mesh_edges(single_triangle_mesh, triangle_landmarks):
    snapped = snap_landmarks_to_vertices(
        single_triangle_mesh, triangle_landmarks, ["L10", "L20", "L30"]
    )
    adjacency = build_mesh_adjacency(single_triangle_mesh)

    paths = build_triangle_boundary_paths(
        single_triangle_mesh, adjacency, snapped, "L10", "L20", "L30"
    )

    assert paths.path_ab == [0, 1]
    assert paths.path_bc == [1, 2]
    assert paths.path_ca == [2, 0]
    assert paths.boundary_vertex_ids == {0, 1, 2}


def test_extract_patch_faces_uses_boundary_paths(single_triangle_mesh, triangle_landmarks):
    snapped = snap_landmarks_to_vertices(
        single_triangle_mesh, triangle_landmarks, ["L10", "L20", "L30"]
    )
    adjacency = build_mesh_adjacency(single_triangle_mesh)
    paths = build_triangle_boundary_paths(
        single_triangle_mesh, adjacency, snapped, "L10", "L20", "L30"
    )

    patch = extract_patch_faces(single_triangle_mesh, paths)

    assert patch.face_ids.tolist() == [0]
    np.testing.assert_array_equal(patch.local_faces, np.array([[0, 1, 2]]))
    assert patch.local_to_global.tolist() == [0, 1, 2]


def test_extract_patch_faces_prefers_smaller_boundary_component(
    split_patch_mesh, triangle_landmarks, monkeypatch
):
    snapped = snap_landmarks_to_vertices(
        split_patch_mesh, triangle_landmarks, ["L10", "L20", "L30"]
    )
    adjacency = build_mesh_adjacency(split_patch_mesh)
    paths = build_triangle_boundary_paths(
        split_patch_mesh, adjacency, snapped, "L10", "L20", "L30"
    )
    monkeypatch.setattr(remesh, "_find_seed_face", lambda _mesh, _paths: 1)

    patch = extract_patch_faces(split_patch_mesh, paths)

    assert patch.face_ids.tolist() == [0]


def test_harmonic_parameterization_pins_boundary_and_solves_internal_vertex(
    center_patch_mesh,
):
    paths = build_triangle_boundary_paths(
        center_patch_mesh,
        build_mesh_adjacency(center_patch_mesh),
        {
            "A": type("S", (), {"vertex_id": 0})(),
            "B": type("S", (), {"vertex_id": 1})(),
            "C": type("S", (), {"vertex_id": 2})(),
        },
        "A",
        "B",
        "C",
    )
    patch = extract_patch_faces(center_patch_mesh, paths)

    param = harmonic_parameterize_patch(center_patch_mesh, patch, paths)

    uv_by_global = {
        int(gid): param.uv[local_id]
        for local_id, gid in enumerate(param.local_to_global)
    }
    np.testing.assert_allclose(uv_by_global[0], [0.0, 0.0])
    np.testing.assert_allclose(uv_by_global[1], [1.0, 0.0])
    np.testing.assert_allclose(uv_by_global[2], [0.0, 1.0])
    assert np.all(uv_by_global[3] > 0.0)
    assert uv_by_global[3].sum() < 1.0
    assert param.flipped_face_count == 0


def test_make_subdivision_template_returns_stable_points_and_faces():
    template = make_subdivision_template(2)

    assert template.barycentric.shape == (6, 3)
    assert template.uv.shape == (6, 2)
    assert template.faces.shape == (4, 3)
    np.testing.assert_allclose(template.barycentric[0], [1.0, 0.0, 0.0])
    np.testing.assert_allclose(template.barycentric[-1], [0.0, 1.0, 0.0])


def test_locate_uv_samples_and_map_back_to_3d(single_triangle_mesh):
    patch_vertices = single_triangle_mesh.vertices
    patch_faces = single_triangle_mesh.faces
    patch_uv = np.array([
        [0.0, 0.0],
        [1.0, 0.0],
        [0.0, 1.0],
    ])
    template = make_subdivision_template(2)

    located = locate_uv_samples_in_faces(patch_uv, patch_faces, template.uv)
    mapped = map_samples_to_3d(patch_vertices, patch_faces, located)

    assert located.unmapped_count == 0
    assert mapped.shape == (6, 3)
    np.testing.assert_allclose(mapped[:, :2], template.uv)
    np.testing.assert_allclose(mapped[:, 2], np.zeros(6))


def test_build_region_remesh_runs_stages_1_to_8(single_triangle_mesh, triangle_landmarks):
    region = {
        "region_id": "T900",
        "region_name": "test triangle region",
        "lm_a": "L10",
        "lm_b": "L20",
        "lm_c": "L30",
        "resolution": 2,
    }

    result = build_region_remesh(single_triangle_mesh, triangle_landmarks, region)

    assert result.patch.face_ids.tolist() == [0]
    assert result.template.faces.shape == (4, 3)
    assert result.located_samples.unmapped_count == 0
    assert result.sample_points_3d.shape == (6, 3)
    np.testing.assert_allclose(result.sample_points_3d[:, :2], result.template.uv)


def test_compute_region_feature_values_uses_selected_landmarks(
    single_triangle_mesh, triangle_landmarks
):
    snapped = snap_landmarks_to_vertices(
        single_triangle_mesh, triangle_landmarks, ["L10", "L20", "L30"]
    )

    features = compute_region_feature_values(
        triangle_landmarks,
        snapped,
        "L10",
        "L20",
        "L30",
    )

    assert features["lm_a"] == "L10"
    assert features["lm_b"] == "L20"
    assert features["lm_c"] == "L30"
    assert features["edge_ab"] == pytest.approx(0.9802, rel=1e-3)
    assert features["edge_bc"] == pytest.approx(1.3640, rel=1e-3)
    assert features["edge_ca"] == pytest.approx(0.9701, rel=1e-3)
    assert features["triangle_area"] == pytest.approx(0.4754, rel=1e-3)
    assert features["perimeter"] == pytest.approx(3.3143, rel=1e-3)
    assert features["snap_distance_max"] < 0.03


def test_build_region_remesh_mesh_uses_template_faces(single_triangle_mesh, triangle_landmarks):
    region = {
        "region_id": "T900",
        "region_name": "test triangle region",
        "lm_a": "L10",
        "lm_b": "L20",
        "lm_c": "L30",
        "resolution": 2,
    }
    result = build_region_remesh(single_triangle_mesh, triangle_landmarks, region)

    mesh = build_region_remesh_mesh(result)

    assert len(mesh.vertices) == len(result.sample_points_3d)
    assert len(mesh.faces) == len(result.template.faces)
    np.testing.assert_array_equal(mesh.faces, result.template.faces)
