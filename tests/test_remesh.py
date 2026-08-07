#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for patch-based remesh building blocks."""

from contextlib import nullcontext
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
import trimesh

import ear_param.remesh as remesh
from ear_param.remesh_backend import BackendComputationError, resolve_remesh_backend
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


def test_remesh_context_reuses_template_and_reverses_shared_path(
    single_triangle_mesh, triangle_landmarks
):
    regions = [
        {"region_id": "R1", "region_name": "one", "lm_a": "L10", "lm_b": "L20", "lm_c": "L30", "resolution": 2},
        {"region_id": "R2", "region_name": "two", "lm_a": "L30", "lm_b": "L20", "lm_c": "L10", "resolution": 2},
    ]
    context = remesh.prepare_remesh_context(single_triangle_mesh, triangle_landmarks, regions)
    first = build_region_remesh(single_triangle_mesh, triangle_landmarks, regions[0], context)
    second = build_region_remesh(single_triangle_mesh, triangle_landmarks, regions[1], context)

    assert first.template is second.template
    assert first.boundary_paths.path_ab == list(reversed(second.boundary_paths.path_bc))


def test_remesh_context_reuses_one_dijkstra_tree_for_multiple_paths(
    monkeypatch, center_patch_mesh, triangle_landmarks
):
    calls: list[int] = []
    original = remesh.dijkstra

    def tracked(graph, *, directed, indices, return_predecessors):
        calls.append(int(indices))
        return original(
            graph,
            directed=directed,
            indices=indices,
            return_predecessors=return_predecessors,
        )

    monkeypatch.setattr(remesh, "dijkstra", tracked)
    regions = [
        {
            "region_id": "R1",
            "region_name": "one",
            "lm_a": "L10",
            "lm_b": "L20",
            "lm_c": "L30",
            "resolution": 2,
        },
        {
            "region_id": "R2",
            "region_name": "two",
            "lm_a": "L10",
            "lm_b": "L30",
            "lm_c": "L20",
            "resolution": 2,
        },
    ]

    context = remesh.prepare_remesh_context(
        center_patch_mesh, triangle_landmarks, regions
    )
    for region in regions:
        remesh.build_region_remesh(
            center_patch_mesh, triangle_landmarks, region, context
        )

    assert calls.count(context.snapped_landmarks["L10"].vertex_id) == 1


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


def test_build_region_remesh_routes_uv_work_through_selected_backend(
    center_patch_mesh, triangle_landmarks
):
    class TrackingBackend:
        def __init__(self):
            self.delegate = resolve_remesh_backend("cpu")
            self.name = "tracking"
            self.requested = "tracking"
            self.fallback_reason = ""
            self.calls = {"solve": 0, "locate": 0, "map": 0}

        def solve_harmonic(self, matrix, rhs):
            self.calls["solve"] += 1
            return self.delegate.solve_harmonic(matrix, rhs)

        def locate(self, uv, faces, sample_uv, tol):
            self.calls["locate"] += 1
            return self.delegate.locate(uv, faces, sample_uv, tol)

        def map_to_3d(self, vertices, faces, face_ids, barycentric):
            self.calls["map"] += 1
            return self.delegate.map_to_3d(vertices, faces, face_ids, barycentric)

        def region_scope(self):
            return nullcontext()

    backend = TrackingBackend()
    region = {
        "region_id": "T900",
        "region_name": "test triangle region",
        "lm_a": "L10",
        "lm_b": "L20",
        "lm_c": "L30",
        "resolution": 2,
    }

    result = build_region_remesh(
        center_patch_mesh,
        triangle_landmarks,
        region,
        backend=backend,
    )

    assert backend.calls == {"solve": 1, "locate": 1, "map": 1}
    assert result.located_samples.unmapped_count == 0


def test_explicit_cpu_backend_matches_default_region_result(
    center_patch_mesh, triangle_landmarks
):
    region = {
        "region_id": "T900",
        "region_name": "test triangle region",
        "lm_a": "L10",
        "lm_b": "L20",
        "lm_c": "L30",
        "resolution": 2,
    }

    default_result = build_region_remesh(center_patch_mesh, triangle_landmarks, region)
    cpu_result = build_region_remesh(
        center_patch_mesh,
        triangle_landmarks,
        region,
        backend=resolve_remesh_backend("cpu"),
    )

    np.testing.assert_array_equal(
        cpu_result.located_samples.face_indices,
        default_result.located_samples.face_indices,
    )
    np.testing.assert_allclose(
        cpu_result.located_samples.barycentric,
        default_result.located_samples.barycentric,
        atol=0.0,
        rtol=0.0,
    )
    np.testing.assert_allclose(
        cpu_result.sample_points_3d,
        default_result.sample_points_3d,
        atol=0.0,
        rtol=0.0,
    )


def test_auto_cuda_backend_recomputes_the_entire_region_on_cpu_after_backend_error(
    center_patch_mesh, triangle_landmarks
):
    class FailingCudaBackend:
        name = "cuda"
        requested = "auto"
        fallback_reason = ""

        def region_scope(self):
            return nullcontext()

        def solve_harmonic(self, matrix, rhs):
            raise BackendComputationError("simulated CUDA failure")

        def locate(self, uv, faces, sample_uv, tol):
            raise AssertionError("the harmonic solve must fail first")

        def map_to_3d(self, vertices, faces, face_ids, barycentric):
            raise AssertionError("the harmonic solve must fail first")

    region = {
        "region_id": "T900",
        "region_name": "test triangle region",
        "lm_a": "L10",
        "lm_b": "L20",
        "lm_c": "L30",
        "resolution": 2,
    }
    reference = build_region_remesh(center_patch_mesh, triangle_landmarks, region)

    result = build_region_remesh(
        center_patch_mesh,
        triangle_landmarks,
        region,
        backend=FailingCudaBackend(),
    )

    np.testing.assert_allclose(result.sample_points_3d, reference.sample_points_3d)
    np.testing.assert_array_equal(
        result.located_samples.unmapped_mask,
        reference.located_samples.unmapped_mask,
    )


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


def test_dense_uv_validation_distinguishes_coverage_from_3d_degeneracy():
    faces = np.array([[0, 1, 2]], dtype=int)
    valid_uv = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    valid_vertices = np.column_stack([valid_uv, np.zeros(3)])

    passed = remesh._inspect_dense_uv_mapping(valid_uv, faces, valid_vertices, validation_resolution=4)
    assert passed.failure_type == "pass"
    assert passed.unmapped_count == 0
    assert passed.degenerate_face_count == 0
    assert passed.min_triangle_area_3d > 0.0

    uncovered = remesh._inspect_dense_uv_mapping(
        valid_uv * 0.5,
        faces,
        valid_vertices,
        validation_resolution=4,
    )
    assert uncovered.failure_type == "r48_unmapped"
    assert uncovered.unmapped_count > 0

    collinear_vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    collapsed = remesh._inspect_dense_uv_mapping(
        valid_uv,
        faces,
        collinear_vertices,
        validation_resolution=4,
    )
    assert collapsed.failure_type == "r48_3d_degenerate"
    assert collapsed.unmapped_count == 0
    assert collapsed.degenerate_face_count > 0
    assert collapsed.min_triangle_area_3d == pytest.approx(0.0)


def test_degenerate_uv_salvage_uses_later_valid_candidate(monkeypatch):
    result = _uv_degenerate_salvage_result(10)
    baseline = remesh._repair_degenerate_uv_faces(result)
    assert baseline.degenerate_after == 0
    rejected = replace(
        baseline,
        uv=result.parameterization.uv.copy(),
        degenerate_after=1,
        method="candidate_rejected",
        rejection_reason="degenerate_repair_incomplete",
    )
    accepted = replace(baseline, method="candidate_reparameterized")
    monkeypatch.setattr(
        remesh,
        "_degenerate_uv_repair_candidates",
        lambda _result, **_kwargs: [rejected, accepted],
    )
    monkeypatch.setattr(
        remesh,
        "_repair_degenerate_uv_components",
        lambda _result, candidate, **_kwargs: remesh.DegenerateUVComponentRepair(
            candidate,
            remesh.DegenerateUVComponentProfile(1, 1, False, 1),
            attempted=False,
        ),
    )

    repaired = repair_unmapped_samples(
        result,
        allow_raw_fail_repair=True,
        max_raw_fail_repair_unmapped_ratio=0.4,
    )

    assert repaired.status == "PASS"
    assert repaired.degenerate_salvage_method == "candidate_reparameterized"
    assert repaired.degenerate_salvage_accepted is True


def test_small_dense_coverage_gap_eligibility_is_limited_to_18_r48_points():
    eligible = remesh.DenseUVValidation(48, 18, 0, 0.01, "r48_unmapped")
    too_large = remesh.DenseUVValidation(48, 19, 0, 0.01, "r48_unmapped")
    degenerate = remesh.DenseUVValidation(48, 1, 1, 0.0, "r48_3d_degenerate")

    assert remesh._is_small_dense_coverage_gap(eligible) is True
    assert remesh._is_small_dense_coverage_gap(too_large) is False
    assert remesh._is_small_dense_coverage_gap(degenerate) is False


def test_degenerate_uv_salvage_accepts_valid_small_coverage_repair(monkeypatch):
    result = _uv_degenerate_salvage_result(10)
    baseline = remesh._repair_degenerate_uv_faces(result)
    coverage_candidate = replace(baseline, method="local_uv_coverage_repair")
    calls = iter((
        remesh.DenseUVValidation(48, 2, 0, 0.01, "r48_unmapped"),
        remesh.DenseUVValidation(48, 0, 0, 0.01, "pass"),
    ))
    monkeypatch.setattr(remesh, "_degenerate_uv_repair_candidates", lambda _result, **_kwargs: [baseline])
    monkeypatch.setattr(remesh, "_inspect_dense_uv_mapping", lambda *_args, **_kwargs: next(calls))
    monkeypatch.setattr(
        remesh,
        "_repair_small_dense_uv_gaps",
        lambda _result, _candidate, _validation, **_kwargs: coverage_candidate,
    )

    repaired = repair_unmapped_samples(
        result,
        allow_raw_fail_repair=True,
        max_raw_fail_repair_unmapped_ratio=0.4,
    )

    assert repaired.status == "PASS"
    assert repaired.dense_coverage_repair_attempted is True
    assert repaired.dense_coverage_repair_accepted is True
    assert repaired.dense_coverage_repair_before == 2
    assert repaired.dense_coverage_repair_after == 0
    assert repaired.degenerate_salvage_method == "local_uv_coverage_repair"


def test_degenerate_component_profile_distinguishes_internal_from_boundary_components():
    internal = _uv_degenerate_salvage_result(10)
    internal_profile = remesh._profile_degenerate_uv_components(
        internal,
        internal.parameterization.uv,
    )
    assert internal_profile.component_count == 1
    assert internal_profile.largest_component_face_count == 1
    assert internal_profile.touches_boundary is False

    template = internal.template
    boundary_face = next(
        face for face in template.faces
        if any(np.isclose(template.barycentric[int(vertex_id)].min(), 0.0) for vertex_id in face)
    )
    boundary_uv = internal.parameterization.uv.copy()
    boundary_uv[int(boundary_face[2])] = (
        boundary_uv[int(boundary_face[0])] + boundary_uv[int(boundary_face[1])]
    ) / 2.0
    boundary = replace(
        internal,
        parameterization=replace(internal.parameterization, uv=boundary_uv),
    )
    boundary_profile = remesh._profile_degenerate_uv_components(boundary, boundary_uv)
    assert boundary_profile.component_count >= 1
    assert boundary_profile.touches_boundary is True
    boundary_repair = remesh._repair_degenerate_uv_components(
        boundary,
        remesh.DegenerateUVRepair(
            uv=boundary_uv,
            degenerate_before=boundary_profile.largest_component_face_count,
            degenerate_after=boundary_profile.largest_component_face_count,
            method="baseline",
        ),
    )
    assert boundary_repair.attempted is False


def test_component_harmonic_repair_resolves_internal_degeneracy():
    result = _uv_degenerate_salvage_result(10)
    base = remesh.DegenerateUVRepair(
        uv=result.parameterization.uv,
        degenerate_before=1,
        degenerate_after=1,
        method="baseline",
    )

    repaired = remesh._repair_degenerate_uv_components(result, base)

    assert repaired.profile.touches_boundary is False
    assert repaired.attempted is True
    assert repaired.uv_repair.degenerate_after == 0


def test_component_harmonic_repair_checks_only_faces_changed_by_component(monkeypatch):
    result = _uv_degenerate_salvage_result(10)
    base = remesh.DegenerateUVRepair(
        uv=result.parameterization.uv,
        degenerate_before=1,
        degenerate_after=1,
        method="baseline",
    )
    monkeypatch.setattr(
        remesh,
        "_uv_candidate_preserves_face_quality",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("global check used")),
    )

    repaired = remesh._repair_degenerate_uv_components(result, base)

    assert repaired.uv_repair.degenerate_after == 0


def test_degenerate_salvage_records_phase_timings():
    result = _uv_degenerate_salvage_result(10)

    repaired = repair_unmapped_samples(
        result,
        allow_raw_fail_repair=True,
        max_raw_fail_repair_unmapped_ratio=0.4,
    )

    assert repaired.repair_timing.degenerate_relaxation_seconds >= 0.0
    assert repaired.repair_timing.component_repair_seconds >= 0.0
    assert repaired.repair_timing.dense_validation_seconds >= 0.0
    assert repaired.repair_timing.total_seconds >= (
        repaired.repair_timing.degenerate_relaxation_seconds
        + repaired.repair_timing.component_repair_seconds
    )


def test_repair_unmapped_samples_refuses_high_ratio_uv_degenerate_region():
    result = _uv_degenerate_salvage_result(7)

    repaired = repair_unmapped_samples(
        result,
        allow_raw_fail_repair=True,
        max_raw_fail_repair_unmapped_ratio=0.4,
        max_raw_fail_repair_degenerate_ratio=0.015,
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
