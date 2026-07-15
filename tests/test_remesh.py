#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for patch-based remesh building blocks."""

import numpy as np
import pandas as pd
import pytest
import trimesh

import ear_param.remesh as remesh
from ear_param.remesh import (
    BoundaryPaths,
    LocatedSamples,
    PatchExtraction,
    PatchParameterization,
    RegionRemeshResult,
    SnappedLandmark,
    SubdivisionTemplate,
    build_mesh_adjacency,
    build_region_remesh,
    build_region_remesh_mesh,
    classify_remesh_qc_status,
    build_triangle_boundary_paths,
    compute_region_feature_values,
    extract_patch_faces,
    harmonic_parameterize_patch,
    locate_uv_samples_in_faces_indexed,
    locate_uv_samples_in_faces,
    make_subdivision_template,
    map_samples_to_3d,
    repair_unmapped_samples,
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


def test_make_barycentric_grid_is_owned_by_remesh_and_keeps_point_order():
    grid = remesh.make_barycentric_grid(2)

    assert remesh.make_barycentric_grid.__module__ == "ear_param.remesh"
    np.testing.assert_allclose(
        grid,
        np.array([
            [1.0, 0.0, 0.0],
            [0.5, 0.0, 0.5],
            [0.0, 0.0, 1.0],
            [0.5, 0.5, 0.0],
            [0.0, 0.5, 0.5],
            [0.0, 1.0, 0.0],
        ]),
    )


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


def test_indexed_uv_lookup_matches_reference_locator():
    source = make_subdivision_template(10)
    sample = make_subdivision_template(24)

    reference = locate_uv_samples_in_faces(source.uv, source.faces, sample.uv)
    indexed = locate_uv_samples_in_faces_indexed(source.uv, source.faces, sample.uv)

    np.testing.assert_array_equal(indexed.face_indices, reference.face_indices)
    np.testing.assert_allclose(indexed.barycentric, reference.barycentric)
    np.testing.assert_array_equal(indexed.unmapped_mask, reference.unmapped_mask)


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


def test_classify_remesh_qc_status_uses_shared_policy():
    assert classify_remesh_qc_status(45, 0, 0) == "PASS"
    assert classify_remesh_qc_status(45, 1, 0) == "WARNING"
    assert classify_remesh_qc_status(45, 10, 0) == "FAIL"
    assert classify_remesh_qc_status(45, 0, 1) == "FAIL"


def _repair_test_result(
    unmapped_ids: list[int],
    *,
    degenerate_face_count: int = 0,
) -> RegionRemeshResult:
    template = make_subdivision_template(3)
    vertices = np.column_stack([
        template.uv[:, 0],
        template.uv[:, 1],
        np.zeros(len(template.uv)),
    ])
    points = vertices.copy()
    unmapped = np.zeros(len(points), dtype=bool)
    unmapped[unmapped_ids] = True
    points[unmapped] = np.nan

    boundary = BoundaryPaths("L1", "L2", "L3", [0, 1], [1, 2], [2, 0])
    snapped = {
        "L1": SnappedLandmark("L1", np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.0]), 0, 0.0),
        "L2": SnappedLandmark("L2", np.array([1.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]), 1, 0.0),
        "L3": SnappedLandmark("L3", np.array([0.0, 1.0, 0.0]), np.array([0.0, 1.0, 0.0]), 2, 0.0),
    }
    patch = PatchExtraction(
        face_ids=np.arange(len(template.faces)),
        local_faces=template.faces,
        local_vertices=vertices,
        local_to_global=np.arange(len(vertices)),
    )
    parameterization = PatchParameterization(
        uv=template.uv,
        local_faces=template.faces,
        local_vertices=vertices,
        local_to_global=np.arange(len(vertices)),
        original_face_ids=np.arange(len(template.faces)),
        flipped_face_count=0,
        degenerate_face_count=degenerate_face_count,
    )
    located = LocatedSamples(
        sample_uv=template.uv,
        face_indices=np.where(unmapped, -1, 0),
        barycentric=template.barycentric,
        unmapped_mask=unmapped,
    )
    return RegionRemeshResult(
        region_id="R001",
        region_name="repair-test",
        snapped_landmarks=snapped,
        boundary_paths=boundary,
        patch=patch,
        parameterization=parameterization,
        template=template,
        located_samples=located,
        sample_points_3d=points,
    )


def _uv_degenerate_salvage_result(resolution: int) -> RegionRemeshResult:
    """Build a flat patch with one internally repairable collapsed UV face."""
    template = make_subdivision_template(resolution)
    vertices = np.column_stack([
        template.uv[:, 0],
        template.uv[:, 1],
        np.zeros(len(template.uv)),
    ])
    faces = template.faces
    target_face = next(
        face for face in faces
        if np.all(template.barycentric[face].min(axis=1) > 0.0)
    )
    uv = template.uv.copy()
    uv[int(target_face[2])] = (uv[int(target_face[0])] + uv[int(target_face[1])]) / 2.0

    boundary_ids = np.where(np.isclose(template.barycentric.min(axis=1), 0.0))[0]
    boundary = BoundaryPaths(
        "L1",
        "L2",
        "L3",
        boundary_ids.tolist(),
        boundary_ids.tolist(),
        boundary_ids.tolist(),
    )
    snapped = {
        "L1": SnappedLandmark("L1", vertices[0], vertices[0], 0, 0.0),
        "L2": SnappedLandmark("L2", vertices[1], vertices[1], 1, 0.0),
        "L3": SnappedLandmark("L3", vertices[2], vertices[2], 2, 0.0),
    }
    patch = PatchExtraction(
        face_ids=np.arange(len(faces)),
        local_faces=faces,
        local_vertices=vertices,
        local_to_global=np.arange(len(vertices)),
    )
    parameterization = PatchParameterization(
        uv=uv,
        local_faces=faces,
        local_vertices=vertices,
        local_to_global=np.arange(len(vertices)),
        original_face_ids=np.arange(len(faces)),
        flipped_face_count=0,
        degenerate_face_count=1,
    )
    located = LocatedSamples(
        sample_uv=template.uv,
        face_indices=np.zeros(len(template.uv), dtype=int),
        barycentric=np.tile(np.array([1.0, 0.0, 0.0]), (len(template.uv), 1)),
        unmapped_mask=np.zeros(len(template.uv), dtype=bool),
    )
    return RegionRemeshResult(
        region_id="R001",
        region_name="uv-degenerate-salvage",
        snapped_landmarks=snapped,
        boundary_paths=boundary,
        patch=patch,
        parameterization=parameterization,
        template=template,
        located_samples=located,
        sample_points_3d=vertices.copy(),
    )


def test_repair_unmapped_samples_fills_warning_vertex_and_internal_points():
    result = _repair_test_result([0])

    repaired = repair_unmapped_samples(result)

    assert repaired.raw_status == "WARNING"
    assert repaired.status == "PASS"
    assert repaired.exportable is True
    assert repaired.repaired_unmapped_count == 0
    assert repaired.repaired_mask[0]
    assert repaired.repair_methods[0] == "landmark_vertex"
    np.testing.assert_allclose(repaired.points_3d[0], [0.0, 0.0, 0.0])


def test_repair_unmapped_samples_does_not_repair_raw_fail_regions():
    result = _repair_test_result([0, 1, 2])

    repaired = repair_unmapped_samples(result)

    assert repaired.raw_status == "FAIL"
    assert repaired.status == "FAIL"
    assert repaired.exportable is False
    assert repaired.repaired_count == 0
    assert repaired.repaired_unmapped_count == 3


def test_repair_unmapped_samples_salvages_raw_fail_when_explicitly_allowed():
    result = _repair_test_result([0, 1, 2])

    repaired = repair_unmapped_samples(
        result,
        allow_raw_fail_repair=True,
        max_raw_fail_repair_unmapped_ratio=0.4,
    )

    assert repaired.raw_status == "FAIL"
    assert repaired.status == "PASS"
    assert repaired.exportable is True
    assert repaired.salvage_attempted is True
    assert repaired.salvage_accepted is True
    assert repaired.salvage_rejection_reason == ""
    assert repaired.repaired_unmapped_count == 0
    assert repaired.repaired_count == 3


def test_repair_unmapped_samples_salvages_low_ratio_uv_degenerate_region():
    result = _uv_degenerate_salvage_result(10)

    repaired = repair_unmapped_samples(
        result,
        allow_raw_fail_repair=True,
        max_raw_fail_repair_unmapped_ratio=0.4,
    )

    assert repaired.raw_status == "FAIL"
    assert repaired.status == "PASS"
    assert repaired.exportable is True
    assert repaired.salvage_attempted is True
    assert repaired.salvage_accepted is True
    assert repaired.degenerate_salvage_attempted is True
    assert repaired.degenerate_salvage_accepted is True
    assert repaired.degenerate_before == 1
    assert repaired.degenerate_after == 0
    assert repaired.degenerate_salvage_method == "local_uv_relaxation"
    assert repaired.salvage_rejection_reason == ""
    assert np.isfinite(repaired.points_3d).all()


def test_repair_unmapped_samples_refuses_high_ratio_uv_degenerate_region():
    result = _uv_degenerate_salvage_result(7)

    repaired = repair_unmapped_samples(
        result,
        allow_raw_fail_repair=True,
        max_raw_fail_repair_unmapped_ratio=0.4,
    )

    assert repaired.raw_status == "FAIL"
    assert repaired.status == "FAIL"
    assert repaired.exportable is False
    assert repaired.salvage_attempted is False
    assert repaired.degenerate_salvage_attempted is False
    assert repaired.degenerate_before == 1
    assert repaired.degenerate_after == 1
    assert repaired.degenerate_salvage_rejection_reason == "degenerate_ratio"
    assert repaired.salvage_rejection_reason == "degenerate_ratio"
