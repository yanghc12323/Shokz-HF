#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch-based remesh primitives for cross-parameterisation.

This module implements the first half of the full remesh workflow:
landmark snapping, surface paths, patch extraction, harmonic UV
parameterisation, regular subdivision, and UV-face sample lookup.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import trimesh
from scipy.sparse import csr_matrix, lil_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.sparse.linalg import spsolve
from scipy.spatial import cKDTree


def make_barycentric_grid(resolution: int) -> np.ndarray:
    """Return a stable triangular barycentric grid for one region template."""
    if resolution < 1:
        raise ValueError(f"resolution must be >= 1, got: {resolution}")

    n_points = (resolution + 1) * (resolution + 2) // 2
    grid = np.empty((n_points, 3), dtype=float)
    index = 0
    inverse_resolution = 1.0 / resolution
    for i in range(resolution + 1):
        for j in range(resolution - i + 1):
            lambda_b = i * inverse_resolution
            lambda_c = j * inverse_resolution
            grid[index] = [1.0 - lambda_b - lambda_c, lambda_b, lambda_c]
            index += 1
    return grid


@dataclass(frozen=True)
class SnappedLandmark:
    """A landmark bound to the nearest mesh vertex."""

    landmark_id: str
    original_xyz: np.ndarray
    snapped_xyz: np.ndarray
    vertex_id: int
    distance: float


@dataclass(frozen=True)
class BoundaryPaths:
    """Three directed mesh-vertex paths around one triangular region."""

    lm_a: str
    lm_b: str
    lm_c: str
    path_ab: list[int]
    path_bc: list[int]
    path_ca: list[int]

    @property
    def boundary_vertex_ids(self) -> set[int]:
        return set(self.path_ab) | set(self.path_bc) | set(self.path_ca)

    @property
    def boundary_edges(self) -> set[tuple[int, int]]:
        edges: set[tuple[int, int]] = set()
        for path in (self.path_ab, self.path_bc, self.path_ca):
            for u, v in zip(path[:-1], path[1:]):
                edges.add(_edge_key(u, v))
        return edges


@dataclass(frozen=True)
class PatchExtraction:
    """A connected patch extracted from a source mesh."""

    face_ids: np.ndarray
    local_faces: np.ndarray
    local_vertices: np.ndarray
    local_to_global: np.ndarray


@dataclass(frozen=True)
class PatchParameterization:
    """Harmonic UV coordinates for a patch submesh."""

    uv: np.ndarray
    local_faces: np.ndarray
    local_vertices: np.ndarray
    local_to_global: np.ndarray
    original_face_ids: np.ndarray
    flipped_face_count: int
    degenerate_face_count: int


@dataclass(frozen=True)
class SubdivisionTemplate:
    """Fixed sampling points and local faces in the standard triangle."""

    resolution: int
    barycentric: np.ndarray
    uv: np.ndarray
    faces: np.ndarray


@dataclass
class RemeshContext:
    """Immutable-per-sample inputs reused by every region remesh."""

    adjacency: csr_matrix
    snapped_landmarks: dict[str, SnappedLandmark]
    path_cache: dict[tuple[int, int], list[int]]
    templates: dict[int, SubdivisionTemplate]


@dataclass(frozen=True)
class LocatedSamples:
    """Location of UV sample points inside source UV faces."""

    sample_uv: np.ndarray
    face_indices: np.ndarray
    barycentric: np.ndarray
    unmapped_mask: np.ndarray

    @property
    def unmapped_count(self) -> int:
        return int(self.unmapped_mask.sum())


@dataclass(frozen=True)
class RegionRemeshResult:
    """Stage 1-8 result for one landmark-defined region."""

    region_id: str
    region_name: str
    snapped_landmarks: dict[str, SnappedLandmark]
    boundary_paths: BoundaryPaths
    patch: PatchExtraction
    parameterization: PatchParameterization
    template: SubdivisionTemplate
    located_samples: LocatedSamples
    sample_points_3d: np.ndarray


@dataclass(frozen=True)
class RepairedSamples:
    """Post-processed samples for export while preserving raw QC."""

    points_3d: np.ndarray
    repaired_mask: np.ndarray
    repair_methods: np.ndarray
    raw_status: str
    status: str
    exportable: bool
    repaired_unmapped_count: int
    salvage_attempted: bool = False
    salvage_accepted: bool = False
    salvage_rejection_reason: str = ""
    degenerate_ratio: float = 0.0
    degenerate_before: int = 0
    degenerate_after: int = 0
    degenerate_salvage_attempted: bool = False
    degenerate_salvage_accepted: bool = False
    degenerate_salvage_method: str = ""
    degenerate_salvage_rejection_reason: str = ""
    repaired_uv: np.ndarray | None = None

    @property
    def repaired_count(self) -> int:
        return int(self.repaired_mask.sum())


@dataclass(frozen=True)
class DegenerateUVRepair:
    """Auditable local repair result for collapsed source UV faces."""

    uv: np.ndarray
    degenerate_before: int
    degenerate_after: int
    method: str
    rejection_reason: str = ""


def classify_remesh_qc_status(
    sample_point_count: int,
    unmapped_count: int,
    degenerate_face_count: int,
    *,
    fail_unmapped_ratio: float = 0.2,
) -> str:
    """Classify one remesh region with the shared W2 QC policy."""
    n_samples = max(int(sample_point_count), 1)
    n_unmapped = int(unmapped_count)
    n_degenerate = int(degenerate_face_count)
    if n_unmapped / n_samples > fail_unmapped_ratio or n_degenerate > 0:
        return "FAIL"
    if n_unmapped > 0:
        return "WARNING"
    return "PASS"


def repair_unmapped_samples(
    result: RegionRemeshResult,
    *,
    fail_unmapped_ratio: float = 0.2,
    allow_raw_fail_repair: bool = False,
    max_raw_fail_repair_unmapped_ratio: float = 0.35,
    max_raw_fail_repair_degenerate_ratio: float = 0.015,
    vertex_ring_steps: int = 2,
    smoothing_iterations: int = 80,
) -> RepairedSamples:
    """Repair unmapped samples without changing raw QC semantics.

    By default only raw WARNING regions are repaired.  Set
    allow_raw_fail_repair=True for the conservative salvage layer. A raw FAIL
    with a small degenerate-UV ratio can be locally reparameterized before the
    existing unmapped-point repair is applied.
    """
    points = np.asarray(result.sample_points_3d, dtype=float).copy()
    raw_unmapped = np.asarray(result.located_samples.unmapped_mask, dtype=bool)
    n_samples = len(points)
    n_raw_unmapped = int(raw_unmapped.sum())
    n_degenerate = int(result.parameterization.degenerate_face_count)
    patch_face_count = max(int(len(result.patch.face_ids)), 1)
    degenerate_ratio = float(n_degenerate / patch_face_count)
    raw_status = classify_remesh_qc_status(
        n_samples,
        n_raw_unmapped,
        n_degenerate,
        fail_unmapped_ratio=fail_unmapped_ratio,
    )
    repair_methods = np.full(n_samples, "mapped", dtype=object)
    repair_methods[raw_unmapped] = "unrepaired"
    repaired_mask = np.zeros(n_samples, dtype=bool)
    salvage_attempted = False
    salvage_rejection_reason = ""
    degenerate_after = n_degenerate
    degenerate_salvage_attempted = False
    degenerate_salvage_method = ""
    degenerate_salvage_rejection_reason = ""
    repaired_uv: np.ndarray | None = None

    if max_raw_fail_repair_degenerate_ratio < 0.0:
        raise ValueError("max_raw_fail_repair_degenerate_ratio must be >= 0")

    if raw_status == "FAIL":
        raw_unmapped_ratio = n_raw_unmapped / max(n_samples, 1)
        if not allow_raw_fail_repair:
            salvage_rejection_reason = "raw_fail_repair_disabled"
        elif n_degenerate > 0 and degenerate_ratio > float(max_raw_fail_repair_degenerate_ratio):
            salvage_rejection_reason = "degenerate_ratio"
            degenerate_salvage_rejection_reason = salvage_rejection_reason
        elif raw_unmapped_ratio > float(max_raw_fail_repair_unmapped_ratio):
            salvage_rejection_reason = "unmapped_ratio"

        if salvage_rejection_reason:
            return RepairedSamples(
                points_3d=points,
                repaired_mask=repaired_mask,
                repair_methods=repair_methods,
                raw_status=raw_status,
                status="FAIL",
                exportable=False,
                repaired_unmapped_count=n_raw_unmapped,
                salvage_attempted=False,
                salvage_accepted=False,
                salvage_rejection_reason=salvage_rejection_reason,
                degenerate_ratio=degenerate_ratio,
                degenerate_before=n_degenerate,
                degenerate_after=degenerate_after,
                degenerate_salvage_attempted=False,
                degenerate_salvage_accepted=False,
                degenerate_salvage_method=degenerate_salvage_method,
                degenerate_salvage_rejection_reason=degenerate_salvage_rejection_reason,
            )
        salvage_attempted = True

        if n_degenerate > 0:
            degenerate_salvage_attempted = True
            uv_repair = _repair_degenerate_uv_faces(result)
            repaired_uv = uv_repair.uv
            degenerate_after = uv_repair.degenerate_after
            degenerate_salvage_method = uv_repair.method
            if degenerate_after > 0:
                salvage_rejection_reason = uv_repair.rejection_reason or "degenerate_repair_incomplete"
                degenerate_salvage_rejection_reason = salvage_rejection_reason
                return RepairedSamples(
                    points_3d=points,
                    repaired_mask=repaired_mask,
                    repair_methods=repair_methods,
                    raw_status=raw_status,
                    status="FAIL",
                    exportable=False,
                    repaired_unmapped_count=n_raw_unmapped,
                    salvage_attempted=True,
                    salvage_accepted=False,
                    salvage_rejection_reason=salvage_rejection_reason,
                    degenerate_ratio=degenerate_ratio,
                    degenerate_before=n_degenerate,
                    degenerate_after=degenerate_after,
                    degenerate_salvage_attempted=True,
                    degenerate_salvage_accepted=False,
                    degenerate_salvage_method=degenerate_salvage_method,
                    degenerate_salvage_rejection_reason=degenerate_salvage_rejection_reason,
                    repaired_uv=repaired_uv,
                )

            remapped = locate_uv_samples_in_faces_indexed(
                repaired_uv,
                result.parameterization.local_faces,
                result.template.uv,
            )
            points = map_samples_to_3d(
                result.parameterization.local_vertices,
                result.parameterization.local_faces,
                remapped,
            )
            if not _dense_uv_mapping_is_valid(
                repaired_uv,
                result.parameterization.local_faces,
                result.parameterization.local_vertices,
            ):
                salvage_rejection_reason = "dense_validation_failed"
                degenerate_salvage_rejection_reason = salvage_rejection_reason
                return RepairedSamples(
                    points_3d=points,
                    repaired_mask=repaired_mask,
                    repair_methods=repair_methods,
                    raw_status=raw_status,
                    status="FAIL",
                    exportable=False,
                    repaired_unmapped_count=int((~np.isfinite(points).all(axis=1)).sum()),
                    salvage_attempted=True,
                    salvage_accepted=False,
                    salvage_rejection_reason=salvage_rejection_reason,
                    degenerate_ratio=degenerate_ratio,
                    degenerate_before=n_degenerate,
                    degenerate_after=degenerate_after,
                    degenerate_salvage_attempted=True,
                    degenerate_salvage_accepted=False,
                    degenerate_salvage_method=degenerate_salvage_method,
                    degenerate_salvage_rejection_reason=degenerate_salvage_rejection_reason,
                    repaired_uv=repaired_uv,
                )

            remapped_raw_unmapped = raw_unmapped & np.isfinite(points).all(axis=1)
            repaired_mask[remapped_raw_unmapped] = True
            repair_methods[remapped_raw_unmapped] = "uv_reparameterized"

    if raw_status == "PASS":
        return RepairedSamples(
            points_3d=points,
            repaired_mask=repaired_mask,
            repair_methods=repair_methods,
            raw_status=raw_status,
            status="PASS",
            exportable=True,
            repaired_unmapped_count=0,
            degenerate_ratio=degenerate_ratio,
            degenerate_before=n_degenerate,
            degenerate_after=degenerate_after,
        )

    bary = np.asarray(result.template.barycentric, dtype=float)
    lm_ids = [
        result.boundary_paths.lm_a,
        result.boundary_paths.lm_b,
        result.boundary_paths.lm_c,
    ]
    for corner_id, lm_id in enumerate(lm_ids):
        corner_rows = np.where(np.isclose(bary[:, corner_id], 1.0))[0]
        if len(corner_rows) != 1:
            continue
        sample_id = int(corner_rows[0])
        if not np.isfinite(points[sample_id]).all() and lm_id in result.snapped_landmarks:
            points[sample_id] = result.snapped_landmarks[lm_id].snapped_xyz
            repaired_mask[sample_id] = True
            repair_methods[sample_id] = "landmark_vertex"

    remaining = ~np.isfinite(points).all(axis=1)
    if remaining.any():
        _smooth_fill_unmapped_samples(
            points,
            result.template.faces,
            result.template.uv,
            remaining,
            fixed_mask=np.isfinite(points).all(axis=1),
            iterations=smoothing_iterations,
        )
        near_vertex = bary.max(axis=1) >= 1.0 - (float(vertex_ring_steps) / result.template.resolution)
        repaired_mask[remaining] = np.isfinite(points[remaining]).all(axis=1)
        repair_methods[remaining & near_vertex] = "smooth_near_vertex"
        repair_methods[remaining & ~near_vertex] = "smooth_internal"
        repair_methods[remaining & ~repaired_mask] = "unrepaired"

    repaired_unmapped = ~np.isfinite(points).all(axis=1)
    status = "PASS" if not repaired_unmapped.any() and degenerate_after == 0 else classify_remesh_qc_status(
        n_samples,
        int(repaired_unmapped.sum()),
        degenerate_after,
        fail_unmapped_ratio=fail_unmapped_ratio,
    )
    if status == "PASS" and not _template_points_are_valid(points, result.template.faces):
        status = "FAIL"
        salvage_rejection_reason = "final_template_degenerate"
        if degenerate_salvage_attempted:
            degenerate_salvage_rejection_reason = salvage_rejection_reason
    salvage_accepted = bool(salvage_attempted and status == "PASS")
    if salvage_attempted and not salvage_accepted and not salvage_rejection_reason:
        salvage_rejection_reason = "repair_incomplete"
    return RepairedSamples(
        points_3d=points,
        repaired_mask=repaired_mask,
        repair_methods=repair_methods,
        raw_status=raw_status,
        status=status,
        exportable=status == "PASS",
        repaired_unmapped_count=int(repaired_unmapped.sum()),
        salvage_attempted=salvage_attempted,
        salvage_accepted=salvage_accepted,
        salvage_rejection_reason=salvage_rejection_reason,
        degenerate_ratio=degenerate_ratio,
        degenerate_before=n_degenerate,
        degenerate_after=degenerate_after,
        degenerate_salvage_attempted=degenerate_salvage_attempted,
        degenerate_salvage_accepted=bool(degenerate_salvage_attempted and status == "PASS"),
        degenerate_salvage_method=degenerate_salvage_method,
        degenerate_salvage_rejection_reason=degenerate_salvage_rejection_reason,
        repaired_uv=repaired_uv,
    )


def build_region_remesh(
    mesh: trimesh.Trimesh,
    landmarks: pd.DataFrame,
    region: dict[str, object],
    context: RemeshContext | None = None,
) -> RegionRemeshResult:
    """Run remesh stages 1-8 for a single triangular region."""
    lm_a = str(region["lm_a"])
    lm_b = str(region["lm_b"])
    lm_c = str(region["lm_c"])
    if context is None:
        snapped = snap_landmarks_to_vertices(mesh, landmarks, [lm_a, lm_b, lm_c])
        adjacency = build_mesh_adjacency(mesh)
        boundary_paths = build_triangle_boundary_paths(mesh, adjacency, snapped, lm_a, lm_b, lm_c)
        template = make_subdivision_template(int(region["resolution"]))
    else:
        snapped = {key: context.snapped_landmarks[key] for key in (lm_a, lm_b, lm_c)}
        boundary_paths = _cached_boundary_paths(context, snapped, lm_a, lm_b, lm_c)
        template = context.templates[int(region["resolution"])]
    patch = extract_patch_faces(mesh, boundary_paths)
    parameterization = harmonic_parameterize_patch(mesh, patch, boundary_paths)
    located = locate_uv_samples_in_faces(
        parameterization.uv,
        parameterization.local_faces,
        template.uv,
    )
    sample_points_3d = map_samples_to_3d(
        parameterization.local_vertices,
        parameterization.local_faces,
        located,
    )

    return RegionRemeshResult(
        region_id=str(region["region_id"]),
        region_name=str(region["region_name"]),
        snapped_landmarks=snapped,
        boundary_paths=boundary_paths,
        patch=patch,
        parameterization=parameterization,
        template=template,
        located_samples=located,
        sample_points_3d=sample_points_3d,
    )


def compute_region_feature_values(
    landmarks: pd.DataFrame,
    snapped: dict[str, SnappedLandmark],
    lm_a: str,
    lm_b: str,
    lm_c: str,
) -> dict[str, float | str]:
    """Compute landmark-defined geometric features for one region."""
    coords = landmarks.loc[[lm_a, lm_b, lm_c], ["x", "y", "z"]].to_numpy(dtype=float)
    a, b, c = coords
    ab = b - a
    bc = c - b
    ca = a - c

    edge_ab = float(np.linalg.norm(ab))
    edge_bc = float(np.linalg.norm(bc))
    edge_ca = float(np.linalg.norm(ca))
    normal_vec = np.cross(ab, c - a)
    normal_norm = float(np.linalg.norm(normal_vec))
    normal = normal_vec / normal_norm if normal_norm > 1e-12 else np.zeros(3)
    snap_distances = [
        float(snapped[lm_id].distance)
        for lm_id in (lm_a, lm_b, lm_c)
        if lm_id in snapped
    ]

    return {
        "lm_a": lm_a,
        "lm_b": lm_b,
        "lm_c": lm_c,
        "edge_ab": edge_ab,
        "edge_bc": edge_bc,
        "edge_ca": edge_ca,
        "perimeter": edge_ab + edge_bc + edge_ca,
        "triangle_area": 0.5 * normal_norm,
        "angle_a_deg": _angle_degrees(b - a, c - a),
        "angle_b_deg": _angle_degrees(a - b, c - b),
        "angle_c_deg": _angle_degrees(a - c, b - c),
        "centroid_x": float(coords[:, 0].mean()),
        "centroid_y": float(coords[:, 1].mean()),
        "centroid_z": float(coords[:, 2].mean()),
        "normal_x": float(normal[0]),
        "normal_y": float(normal[1]),
        "normal_z": float(normal[2]),
        "snap_distance_a": float(snapped[lm_a].distance),
        "snap_distance_b": float(snapped[lm_b].distance),
        "snap_distance_c": float(snapped[lm_c].distance),
        "snap_distance_mean": float(np.mean(snap_distances)),
        "snap_distance_max": float(np.max(snap_distances)),
    }


def build_region_remesh_mesh(
    result: RegionRemeshResult,
    drop_invalid_faces: bool = True,
    vertices_override: np.ndarray | None = None,
) -> trimesh.Trimesh:
    """Build a remesh patch from mapped 3D samples and template faces."""
    source_vertices = result.sample_points_3d if vertices_override is None else vertices_override
    vertices = np.asarray(source_vertices, dtype=float)
    faces = np.asarray(result.template.faces, dtype=int)
    if drop_invalid_faces:
        valid_vertices = np.isfinite(vertices).all(axis=1)
        faces = faces[np.all(valid_vertices[faces], axis=1)]
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def snap_landmarks_to_vertices(
    mesh: trimesh.Trimesh,
    landmarks: pd.DataFrame,
    landmark_ids: list[str],
) -> dict[str, SnappedLandmark]:
    """Snap named landmarks to their nearest mesh vertices."""
    missing = set(landmark_ids) - set(landmarks.index)
    if missing:
        raise ValueError(f"missing landmarks: {sorted(missing)}")

    vertices = np.asarray(mesh.vertices, dtype=float)
    tree = cKDTree(vertices)
    query_points = landmarks.loc[landmark_ids, ["x", "y", "z"]].to_numpy(dtype=float)
    distances, vertex_ids = tree.query(query_points, k=1)

    snapped: dict[str, SnappedLandmark] = {}
    for lm_id, original, dist, vid in zip(landmark_ids, query_points, distances, vertex_ids):
        vertex_id = int(vid)
        snapped[lm_id] = SnappedLandmark(
            landmark_id=lm_id,
            original_xyz=original.astype(float, copy=True),
            snapped_xyz=vertices[vertex_id].astype(float, copy=True),
            vertex_id=vertex_id,
            distance=float(dist),
        )
    return snapped


def build_mesh_adjacency(mesh: trimesh.Trimesh) -> csr_matrix:
    """Build a weighted undirected vertex graph from mesh faces."""
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=int)
    edge_weights: dict[tuple[int, int], float] = {}

    for face in faces:
        for u, v in _face_edges(face):
            key = _edge_key(int(u), int(v))
            weight = float(np.linalg.norm(vertices[key[0]] - vertices[key[1]]))
            previous = edge_weights.get(key)
            if previous is None or weight < previous:
                edge_weights[key] = weight

    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    for (u, v), weight in edge_weights.items():
        rows.extend([u, v])
        cols.extend([v, u])
        data.extend([weight, weight])

    n_vertices = len(vertices)
    return csr_matrix((data, (rows, cols)), shape=(n_vertices, n_vertices))


def prepare_remesh_context(
    mesh: trimesh.Trimesh,
    landmarks: pd.DataFrame,
    regions: list[dict[str, object]],
) -> RemeshContext:
    """Prepare deterministic shared Remesh inputs once for one sample."""
    landmark_ids = sorted({str(region[key]) for region in regions for key in ("lm_a", "lm_b", "lm_c")})
    resolutions = {int(region["resolution"]) for region in regions}
    return RemeshContext(
        adjacency=build_mesh_adjacency(mesh),
        snapped_landmarks=snap_landmarks_to_vertices(mesh, landmarks, landmark_ids),
        path_cache={},
        templates={resolution: make_subdivision_template(resolution) for resolution in resolutions},
    )


def _cached_boundary_paths(
    context: RemeshContext,
    snapped: dict[str, SnappedLandmark],
    lm_a: str,
    lm_b: str,
    lm_c: str,
) -> BoundaryPaths:
    def path(start: int, end: int) -> list[int]:
        key = (min(start, end), max(start, end))
        stored = context.path_cache.get(key)
        if stored is None:
            stored = _shortest_vertex_path(context.adjacency, key[0], key[1])
            context.path_cache[key] = stored
        return stored if start == key[0] else list(reversed(stored))

    return BoundaryPaths(
        lm_a=lm_a, lm_b=lm_b, lm_c=lm_c,
        path_ab=path(snapped[lm_a].vertex_id, snapped[lm_b].vertex_id),
        path_bc=path(snapped[lm_b].vertex_id, snapped[lm_c].vertex_id),
        path_ca=path(snapped[lm_c].vertex_id, snapped[lm_a].vertex_id),
    )


def build_triangle_boundary_paths(
    mesh: trimesh.Trimesh,
    adjacency: csr_matrix,
    snapped: dict[str, SnappedLandmark],
    lm_a: str,
    lm_b: str,
    lm_c: str,
) -> BoundaryPaths:
    """Find three shortest mesh-edge paths around a landmark triangle."""
    del mesh  # mesh kept in signature for a clear workflow-level API.
    return BoundaryPaths(
        lm_a=lm_a,
        lm_b=lm_b,
        lm_c=lm_c,
        path_ab=_shortest_vertex_path(adjacency, snapped[lm_a].vertex_id, snapped[lm_b].vertex_id),
        path_bc=_shortest_vertex_path(adjacency, snapped[lm_b].vertex_id, snapped[lm_c].vertex_id),
        path_ca=_shortest_vertex_path(adjacency, snapped[lm_c].vertex_id, snapped[lm_a].vertex_id),
    )


def extract_patch_faces(
    mesh: trimesh.Trimesh,
    boundary_paths: BoundaryPaths,
) -> PatchExtraction:
    """Extract a connected face patch bounded by three surface paths."""
    faces = np.asarray(mesh.faces, dtype=int)
    if faces.size == 0:
        raise ValueError("mesh has no faces")

    seed_face = _find_seed_face(mesh, boundary_paths)
    neighbors = _build_face_neighbors(faces, boundary_paths.boundary_edges)
    component = _select_patch_component(
        faces,
        _connected_face_components(neighbors),
        boundary_paths.boundary_edges,
        seed_face,
    )

    face_ids = np.array(sorted(component), dtype=int)
    local_to_global = _ordered_unique(faces[face_ids].ravel())
    global_to_local = {int(g): i for i, g in enumerate(local_to_global)}
    local_faces = np.array(
        [[global_to_local[int(v)] for v in faces[face_id]] for face_id in face_ids],
        dtype=int,
    )
    local_vertices = np.asarray(mesh.vertices, dtype=float)[local_to_global]

    return PatchExtraction(
        face_ids=face_ids,
        local_faces=local_faces,
        local_vertices=local_vertices,
        local_to_global=local_to_global,
    )


def harmonic_parameterize_patch(
    mesh: trimesh.Trimesh,
    patch: PatchExtraction,
    boundary_paths: BoundaryPaths,
) -> PatchParameterization:
    """Compute a harmonic UV map for one extracted patch."""
    boundary_uv_global = _boundary_uv(mesh, boundary_paths)
    local_to_global = patch.local_to_global
    global_to_local = {int(g): i for i, g in enumerate(local_to_global)}

    boundary_uv_local: dict[int, np.ndarray] = {}
    for global_id, uv in boundary_uv_global.items():
        if global_id in global_to_local:
            boundary_uv_local[global_to_local[global_id]] = uv

    n_vertices = len(local_to_global)
    uv = np.full((n_vertices, 2), np.nan, dtype=float)
    for local_id, value in boundary_uv_local.items():
        uv[local_id] = value

    internal_ids = [i for i in range(n_vertices) if i not in boundary_uv_local]
    if internal_ids:
        uv = _solve_harmonic_uv(patch.local_faces, uv, boundary_uv_local, internal_ids)

    flipped, degenerate = _count_uv_face_quality(uv, patch.local_faces)
    return PatchParameterization(
        uv=uv,
        local_faces=patch.local_faces,
        local_vertices=patch.local_vertices,
        local_to_global=patch.local_to_global,
        original_face_ids=patch.face_ids,
        flipped_face_count=flipped,
        degenerate_face_count=degenerate,
    )


def make_subdivision_template(resolution: int) -> SubdivisionTemplate:
    """Create fixed points and small-triangle connectivity for one region."""
    barycentric = make_barycentric_grid(resolution)
    uv = barycentric[:, 1:3].copy()
    index: dict[tuple[int, int], int] = {}
    cursor = 0
    for i in range(resolution + 1):
        for j in range(resolution - i + 1):
            index[(i, j)] = cursor
            cursor += 1

    faces: list[list[int]] = []
    for i in range(resolution):
        for j in range(resolution - i):
            faces.append([index[(i, j)], index[(i + 1, j)], index[(i, j + 1)]])
            if j < resolution - i - 1:
                faces.append([
                    index[(i + 1, j)],
                    index[(i + 1, j + 1)],
                    index[(i, j + 1)],
                ])

    return SubdivisionTemplate(
        resolution=resolution,
        barycentric=barycentric,
        uv=uv,
        faces=np.asarray(faces, dtype=int),
    )


def locate_uv_samples_in_faces(
    uv: np.ndarray,
    faces: np.ndarray,
    sample_uv: np.ndarray,
    tol: float = 1e-9,
) -> LocatedSamples:
    """Locate each UV sample point inside a UV face."""
    uv = np.asarray(uv, dtype=float)
    faces = np.asarray(faces, dtype=int)
    sample_uv = np.asarray(sample_uv, dtype=float)

    face_indices = np.full(len(sample_uv), -1, dtype=int)
    bary = np.full((len(sample_uv), 3), np.nan, dtype=float)
    unmapped = np.ones(len(sample_uv), dtype=bool)

    tri_uvs = uv[faces]
    for sample_id, point in enumerate(sample_uv):
        for face_id, tri_uv in enumerate(tri_uvs):
            weights = _barycentric_2d(point, tri_uv)
            if weights is None:
                continue
            if np.all(weights >= -tol) and np.all(weights <= 1.0 + tol):
                clipped = np.clip(weights, 0.0, 1.0)
                total = clipped.sum()
                bary[sample_id] = clipped / total if total > 0 else clipped
                face_indices[sample_id] = face_id
                unmapped[sample_id] = False
                break

    return LocatedSamples(
        sample_uv=sample_uv,
        face_indices=face_indices,
        barycentric=bary,
        unmapped_mask=unmapped,
    )


def locate_uv_samples_in_faces_indexed(
    uv: np.ndarray,
    faces: np.ndarray,
    sample_uv: np.ndarray,
    tol: float = 1e-9,
) -> LocatedSamples:
    """Locate UV samples with an axis-aligned face-grid acceleration index."""
    uv = np.asarray(uv, dtype=float)
    faces = np.asarray(faces, dtype=int)
    sample_uv = np.asarray(sample_uv, dtype=float)
    tri_uvs = uv[faces]

    face_indices = np.full(len(sample_uv), -1, dtype=int)
    bary = np.full((len(sample_uv), 3), np.nan, dtype=float)
    unmapped = np.ones(len(sample_uv), dtype=bool)
    if len(faces) == 0:
        return LocatedSamples(sample_uv, face_indices, bary, unmapped)

    grid = _build_uv_face_grid(tri_uvs, tol)
    for sample_id, point in enumerate(sample_uv):
        candidates = grid.candidates(point)
        for face_id in candidates:
            weights = _barycentric_2d(point, tri_uvs[face_id])
            if weights is None or not np.all(weights >= -tol) or not np.all(weights <= 1.0 + tol):
                continue
            clipped = np.clip(weights, 0.0, 1.0)
            total = clipped.sum()
            bary[sample_id] = clipped / total if total > 0 else clipped
            face_indices[sample_id] = face_id
            unmapped[sample_id] = False
            break

        if unmapped[sample_id]:
            # Grid binning is an accelerator, never a change in lookup semantics.
            for face_id, tri_uv in enumerate(tri_uvs):
                weights = _barycentric_2d(point, tri_uv)
                if weights is None or not np.all(weights >= -tol) or not np.all(weights <= 1.0 + tol):
                    continue
                clipped = np.clip(weights, 0.0, 1.0)
                total = clipped.sum()
                bary[sample_id] = clipped / total if total > 0 else clipped
                face_indices[sample_id] = face_id
                unmapped[sample_id] = False
                break

    return LocatedSamples(sample_uv, face_indices, bary, unmapped)


@dataclass(frozen=True)
class _UVFaceGrid:
    lower: np.ndarray
    upper: np.ndarray
    bin_count: int
    cells: dict[tuple[int, int], list[int]]

    def candidates(self, point: np.ndarray) -> list[int]:
        cell = self._cell(point)
        return self.cells.get(cell, [])

    def _cell(self, point: np.ndarray) -> tuple[int, int]:
        span = np.maximum(self.upper - self.lower, 1e-12)
        scaled = (np.asarray(point, dtype=float) - self.lower) / span
        indices = np.floor(scaled * self.bin_count).astype(int)
        indices = np.clip(indices, 0, self.bin_count - 1)
        return int(indices[0]), int(indices[1])


def _build_uv_face_grid(tri_uvs: np.ndarray, tol: float) -> _UVFaceGrid:
    finite_values = tri_uvs[np.isfinite(tri_uvs)]
    if len(finite_values) == 0:
        lower = np.zeros(2, dtype=float)
        upper = np.ones(2, dtype=float)
    else:
        lower = np.nanmin(tri_uvs.reshape(-1, 2), axis=0) - tol
        upper = np.nanmax(tri_uvs.reshape(-1, 2), axis=0) + tol
    bin_count = max(1, int(np.ceil(np.sqrt(len(tri_uvs)))))
    grid = _UVFaceGrid(lower, upper, bin_count, {})

    for face_id, tri_uv in enumerate(tri_uvs):
        if not np.isfinite(tri_uv).all():
            continue
        face_lower = tri_uv.min(axis=0) - tol
        face_upper = tri_uv.max(axis=0) + tol
        start = grid._cell(face_lower)
        end = grid._cell(face_upper)
        for i in range(start[0], end[0] + 1):
            for j in range(start[1], end[1] + 1):
                grid.cells.setdefault((i, j), []).append(face_id)
    return grid


def map_samples_to_3d(
    vertices: np.ndarray,
    faces: np.ndarray,
    located: LocatedSamples,
) -> np.ndarray:
    """Map located UV samples back to 3D using corresponding source faces."""
    vertices = np.asarray(vertices, dtype=float)
    faces = np.asarray(faces, dtype=int)
    mapped = np.full((len(located.sample_uv), 3), np.nan, dtype=float)

    for sample_id, face_id in enumerate(located.face_indices):
        if face_id < 0:
            continue
        tri = vertices[faces[int(face_id)]]
        mapped[sample_id] = located.barycentric[sample_id] @ tri
    return mapped


def _edge_key(u: int, v: int) -> tuple[int, int]:
    return (int(u), int(v)) if int(u) <= int(v) else (int(v), int(u))


def _face_edges(face: np.ndarray) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    return (
        (int(face[0]), int(face[1])),
        (int(face[1]), int(face[2])),
        (int(face[2]), int(face[0])),
    )


def _shortest_vertex_path(adjacency: csr_matrix, start: int, end: int) -> list[int]:
    if start == end:
        return [int(start)]

    distances, predecessors = dijkstra(
        adjacency,
        directed=False,
        indices=int(start),
        return_predecessors=True,
    )
    if not np.isfinite(distances[int(end)]):
        raise ValueError(f"no mesh path between vertices {start} and {end}")

    path = [int(end)]
    cursor = int(end)
    while cursor != int(start):
        cursor = int(predecessors[cursor])
        if cursor < 0:
            raise ValueError(f"no predecessor while reconstructing {start}->{end}")
        path.append(cursor)
    path.reverse()
    return path


def _find_seed_face(mesh: trimesh.Trimesh, boundary_paths: BoundaryPaths) -> int:
    vertices = np.asarray(mesh.vertices, dtype=float)
    corner_ids = [
        boundary_paths.path_ab[0],
        boundary_paths.path_ab[-1],
        boundary_paths.path_bc[-1],
    ]
    target = vertices[corner_ids].mean(axis=0)
    centroids = np.asarray(mesh.triangles_center, dtype=float)
    return int(np.argmin(np.linalg.norm(centroids - target, axis=1)))


def _build_face_neighbors(
    faces: np.ndarray,
    boundary_edges: set[tuple[int, int]],
) -> list[list[int]]:
    edge_to_faces: dict[tuple[int, int], list[int]] = {}
    for face_id, face in enumerate(faces):
        for u, v in _face_edges(face):
            edge_to_faces.setdefault(_edge_key(u, v), []).append(face_id)

    neighbors: list[list[int]] = [[] for _ in range(len(faces))]
    for edge, face_ids in edge_to_faces.items():
        if edge in boundary_edges or len(face_ids) < 2:
            continue
        for face_id in face_ids:
            neighbors[face_id].extend(other for other in face_ids if other != face_id)
    return neighbors


def _connected_face_components(neighbors: list[list[int]]) -> list[set[int]]:
    components: list[set[int]] = []
    visited: set[int] = set()

    for face_id in range(len(neighbors)):
        if face_id in visited:
            continue
        component: set[int] = {face_id}
        visited.add(face_id)
        queue: list[int] = [face_id]
        while queue:
            current = queue.pop(0)
            for nxt in neighbors[current]:
                if nxt not in visited:
                    visited.add(nxt)
                    component.add(nxt)
                    queue.append(nxt)
        components.append(component)
    return components


def _select_patch_component(
    faces: np.ndarray,
    components: list[set[int]],
    boundary_edges: set[tuple[int, int]],
    seed_face: int,
) -> set[int]:
    boundary_components = [
        component
        for component in components
        if _component_boundary_contact_count(faces, component, boundary_edges) > 0
    ]
    if len(boundary_components) > 1:
        return min(boundary_components, key=len)

    for component in components:
        if seed_face in component:
            return component
    raise ValueError(f"seed face {seed_face} is not in any face component")


def _component_boundary_contact_count(
    faces: np.ndarray,
    component: set[int],
    boundary_edges: set[tuple[int, int]],
) -> int:
    contact_count = 0
    for face_id in component:
        for u, v in _face_edges(faces[face_id]):
            if _edge_key(u, v) in boundary_edges:
                contact_count += 1
    return contact_count


def _ordered_unique(values: np.ndarray) -> np.ndarray:
    seen: set[int] = set()
    ordered: list[int] = []
    for value in values:
        item = int(value)
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return np.asarray(ordered, dtype=int)


def _boundary_uv(
    mesh: trimesh.Trimesh,
    boundary_paths: BoundaryPaths,
) -> dict[int, np.ndarray]:
    vertices = np.asarray(mesh.vertices, dtype=float)
    uv: dict[int, np.ndarray] = {}
    _assign_path_uv(vertices, boundary_paths.path_ab, np.array([0.0, 0.0]), np.array([1.0, 0.0]), uv)
    _assign_path_uv(vertices, boundary_paths.path_bc, np.array([1.0, 0.0]), np.array([0.0, 1.0]), uv)
    _assign_path_uv(vertices, boundary_paths.path_ca, np.array([0.0, 1.0]), np.array([0.0, 0.0]), uv)

    uv[boundary_paths.path_ab[0]] = np.array([0.0, 0.0])
    uv[boundary_paths.path_ab[-1]] = np.array([1.0, 0.0])
    uv[boundary_paths.path_bc[-1]] = np.array([0.0, 1.0])
    return uv


def _assign_path_uv(
    vertices: np.ndarray,
    path: list[int],
    start_uv: np.ndarray,
    end_uv: np.ndarray,
    out: dict[int, np.ndarray],
) -> None:
    if len(path) == 1:
        out[path[0]] = start_uv.copy()
        return

    lengths = [0.0]
    for u, v in zip(path[:-1], path[1:]):
        lengths.append(lengths[-1] + float(np.linalg.norm(vertices[v] - vertices[u])))
    total = lengths[-1]

    for vertex_id, distance in zip(path, lengths):
        t = distance / total if total > 1e-12 else 0.0
        out[int(vertex_id)] = (1.0 - t) * start_uv + t * end_uv


def _solve_harmonic_uv(
    local_faces: np.ndarray,
    uv: np.ndarray,
    boundary_uv: dict[int, np.ndarray],
    internal_ids: list[int],
) -> np.ndarray:
    adjacency = _local_vertex_neighbors(local_faces, len(uv))
    internal_index = {vertex_id: i for i, vertex_id in enumerate(internal_ids)}
    matrix = lil_matrix((len(internal_ids), len(internal_ids)), dtype=float)
    rhs = np.zeros((len(internal_ids), 2), dtype=float)

    for vertex_id in internal_ids:
        row = internal_index[vertex_id]
        neighbors = sorted(adjacency[vertex_id])
        matrix[row, row] = len(neighbors)
        for neighbor in neighbors:
            if neighbor in internal_index:
                matrix[row, internal_index[neighbor]] = -1.0
            elif neighbor in boundary_uv:
                rhs[row] += boundary_uv[neighbor]

    solved = spsolve(matrix.tocsr(), rhs)
    solved = np.asarray(solved, dtype=float)
    if solved.ndim == 1:
        solved = solved.reshape(-1, 1)
    uv = uv.copy()
    for vertex_id, value in zip(internal_ids, solved):
        uv[vertex_id] = value
    return uv


def build_patch_face_adjacency(
    mesh: trimesh.Trimesh,
    boundary_paths: BoundaryPaths,
) -> list[list[int]]:
    """Build face-face adjacency for the region bounded by boundary_paths.

    Returns a list of length len(mesh.faces), where each entry is a list of
    adjacent face indices (excluding connections across boundary edges).
    Internal faces that sit outside the patch component are still included
    because boundary_edges are the only cut.
    """
    faces = np.asarray(mesh.faces, dtype=int)
    return _build_face_neighbors(faces, boundary_paths.boundary_edges)


def _local_vertex_neighbors(local_faces: np.ndarray, n_vertices: int) -> list[set[int]]:
    neighbors: list[set[int]] = [set() for _ in range(n_vertices)]
    for face in local_faces:
        for u, v in _face_edges(face):
            neighbors[u].add(v)
            neighbors[v].add(u)
    return neighbors


def _smooth_fill_unmapped_samples(
    points: np.ndarray,
    template_faces: np.ndarray,
    sample_uv: np.ndarray,
    fill_mask: np.ndarray,
    *,
    fixed_mask: np.ndarray,
    iterations: int,
) -> None:
    fixed_ids = np.where(fixed_mask)[0]
    fill_ids = np.where(fill_mask)[0]
    if len(fixed_ids) == 0:
        return

    fixed_uv = np.asarray(sample_uv, dtype=float)[fixed_ids]
    for sample_id in fill_ids:
        distances = np.linalg.norm(fixed_uv - sample_uv[sample_id], axis=1)
        points[sample_id] = points[fixed_ids[int(np.argmin(distances))]]

    neighbors = _local_vertex_neighbors(np.asarray(template_faces, dtype=int), len(points))
    fill_set = set(int(i) for i in fill_ids)
    fixed_mask = fixed_mask.copy()
    for _ in range(max(int(iterations), 0)):
        updated = points.copy()
        for sample_id in fill_ids:
            neighbor_ids = [n for n in neighbors[int(sample_id)] if np.isfinite(points[n]).all()]
            if neighbor_ids:
                updated[sample_id] = np.mean(points[neighbor_ids], axis=0)
        points[list(fill_set)] = updated[list(fill_set)]
        points[fixed_mask] = updated[fixed_mask]


def _repair_degenerate_uv_faces(result: RegionRemeshResult) -> DegenerateUVRepair:
    """Relax internal UV vertices until small collapsed faces are resolved."""
    uv = np.asarray(result.parameterization.uv, dtype=float).copy()
    faces = np.asarray(result.parameterization.local_faces, dtype=int)
    area_tolerance = 1e-12
    initial_areas = _uv_face_signed_areas(uv, faces)
    degenerate_before = int((np.abs(initial_areas) <= area_tolerance).sum())
    if degenerate_before == 0:
        return DegenerateUVRepair(uv, 0, 0, "")

    boundary_ids = _boundary_local_vertex_ids(result)
    neighbors = _local_vertex_neighbors(faces, len(uv))
    incident_faces = _vertex_incident_faces(faces, len(uv))
    dominant_sign = _dominant_uv_orientation(initial_areas, area_tolerance)
    target_area = _uv_repair_target_area(initial_areas, area_tolerance)

    for _ in range(max(degenerate_before * 3, 1)):
        current_areas = _uv_face_signed_areas(uv, faces)
        degenerate_face_ids = np.where(np.abs(current_areas) <= area_tolerance)[0]
        if len(degenerate_face_ids) == 0:
            break

        changed = False
        for face_id in degenerate_face_ids:
            proposal = _find_uv_relaxation_proposal(
                uv,
                faces,
                int(face_id),
                boundary_ids,
                neighbors,
                incident_faces,
                current_areas,
                dominant_sign,
                target_area,
                area_tolerance,
            )
            if proposal is None:
                continue
            vertex_id, value = proposal
            uv[vertex_id] = value
            changed = True
        if not changed:
            break

    degenerate_after = int((np.abs(_uv_face_signed_areas(uv, faces)) <= area_tolerance).sum())
    rejection_reason = "" if degenerate_after == 0 else "degenerate_repair_incomplete"
    return DegenerateUVRepair(
        uv=uv,
        degenerate_before=degenerate_before,
        degenerate_after=degenerate_after,
        method="local_uv_relaxation",
        rejection_reason=rejection_reason,
    )


def _boundary_local_vertex_ids(result: RegionRemeshResult) -> set[int]:
    boundary_global_ids = result.boundary_paths.boundary_vertex_ids
    return {
        local_id
        for local_id, global_id in enumerate(result.parameterization.local_to_global)
        if int(global_id) in boundary_global_ids
    }


def _vertex_incident_faces(faces: np.ndarray, n_vertices: int) -> list[list[int]]:
    incident: list[list[int]] = [[] for _ in range(n_vertices)]
    for face_id, face in enumerate(faces):
        for vertex_id in face:
            incident[int(vertex_id)].append(int(face_id))
    return incident


def _dominant_uv_orientation(areas: np.ndarray, area_tolerance: float) -> float:
    valid = areas[np.abs(areas) > area_tolerance]
    if len(valid) == 0:
        return 1.0
    return 1.0 if float(np.median(valid)) >= 0.0 else -1.0


def _uv_repair_target_area(areas: np.ndarray, area_tolerance: float) -> float:
    valid = np.abs(areas[np.abs(areas) > area_tolerance])
    if len(valid) == 0:
        return area_tolerance * 10.0
    return max(area_tolerance * 10.0, float(np.median(valid)) * 1e-4)


def _find_uv_relaxation_proposal(
    uv: np.ndarray,
    faces: np.ndarray,
    face_id: int,
    boundary_ids: set[int],
    neighbors: list[set[int]],
    incident_faces: list[list[int]],
    current_areas: np.ndarray,
    dominant_sign: float,
    target_area: float,
    area_tolerance: float,
) -> tuple[int, np.ndarray] | None:
    face = faces[face_id]
    movable_ids = [int(vertex_id) for vertex_id in face if int(vertex_id) not in boundary_ids]

    for vertex_id in movable_ids:
        neighbor_ids = sorted(neighbors[vertex_id])
        if not neighbor_ids:
            continue
        laplacian_value = np.mean(uv[neighbor_ids], axis=0)
        if _uv_proposal_is_valid(
            uv,
            faces,
            face_id,
            vertex_id,
            laplacian_value,
            incident_faces[vertex_id],
            current_areas,
            dominant_sign,
            area_tolerance,
        ):
            return vertex_id, laplacian_value

    candidates: list[tuple[float, int, np.ndarray]] = []
    for vertex_id in movable_ids:
        current_value = uv[vertex_id]
        gradient = _signed_area_gradient(uv, face, vertex_id)
        gradient_norm_sq = float(np.dot(gradient, gradient))
        if gradient_norm_sq <= 1e-20:
            continue
        desired_area = dominant_sign * target_area
        delta = ((desired_area - current_areas[face_id]) / gradient_norm_sq) * gradient
        candidate = current_value + delta
        if _uv_proposal_is_valid(
            uv,
            faces,
            face_id,
            vertex_id,
            candidate,
            incident_faces[vertex_id],
            current_areas,
            dominant_sign,
            area_tolerance,
        ):
            candidates.append((float(np.linalg.norm(delta)), vertex_id, candidate))

    if not candidates:
        return None
    _, vertex_id, candidate = min(candidates, key=lambda item: item[0])
    return vertex_id, candidate


def _signed_area_gradient(uv: np.ndarray, face: np.ndarray, vertex_id: int) -> np.ndarray:
    """Return the exact affine gradient of one face area for one UV vertex."""
    local_index = int(np.where(face == vertex_id)[0][0])
    base = uv[vertex_id]
    gradient = np.empty(2, dtype=float)
    for axis in range(2):
        shifted = base.copy()
        shifted[axis] += 1.0
        trial = uv[face].copy()
        trial[local_index] = shifted
        gradient[axis] = _signed_area2(trial) - _signed_area2(uv[face])
    return gradient


def _uv_proposal_is_valid(
    uv: np.ndarray,
    faces: np.ndarray,
    target_face_id: int,
    vertex_id: int,
    candidate: np.ndarray,
    incident_face_ids: list[int],
    current_areas: np.ndarray,
    dominant_sign: float,
    area_tolerance: float,
) -> bool:
    trial_uv = uv.copy()
    trial_uv[vertex_id] = candidate
    for face_id in incident_face_ids:
        previous_area = current_areas[face_id]
        proposed_area = _signed_area2(trial_uv[faces[face_id]])
        if face_id != target_face_id and abs(previous_area) <= area_tolerance:
            continue
        expected_sign = np.sign(previous_area) if abs(previous_area) > area_tolerance else dominant_sign
        if abs(proposed_area) <= area_tolerance or np.sign(proposed_area) != expected_sign:
            return False
    return True


def _dense_uv_mapping_is_valid(
    uv: np.ndarray,
    faces: np.ndarray,
    vertices: np.ndarray,
    *,
    validation_resolution: int = 48,
) -> bool:
    """Check repaired UV coverage and mapped template-face geometry at r48."""
    template = make_subdivision_template(validation_resolution)
    located = locate_uv_samples_in_faces_indexed(uv, faces, template.uv)
    if located.unmapped_count > 0:
        return False
    points = map_samples_to_3d(vertices, faces, located)
    return _template_points_are_valid(points, template.faces)


def _template_points_are_valid(points: np.ndarray, faces: np.ndarray) -> bool:
    points = np.asarray(points, dtype=float)
    faces = np.asarray(faces, dtype=int)
    if not np.isfinite(points).all():
        return False
    if len(faces) == 0:
        return False
    triangles = points[faces]
    area2 = np.linalg.norm(
        np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]),
        axis=1,
    )
    return bool(np.all(area2 > 1e-12))


def _uv_face_signed_areas(uv: np.ndarray, faces: np.ndarray) -> np.ndarray:
    triangles = np.asarray(uv, dtype=float)[np.asarray(faces, dtype=int)]
    ab = triangles[:, 1] - triangles[:, 0]
    ac = triangles[:, 2] - triangles[:, 0]
    return ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]


def _count_uv_face_quality(uv: np.ndarray, faces: np.ndarray) -> tuple[int, int]:
    areas = _uv_face_signed_areas(uv, faces)
    degenerate = int((np.abs(areas) <= 1e-12).sum())
    flipped = int((areas < -1e-12).sum())
    return flipped, degenerate


def _signed_area2(tri_uv: np.ndarray) -> float:
    ab = tri_uv[1] - tri_uv[0]
    ac = tri_uv[2] - tri_uv[0]
    return float(ab[0] * ac[1] - ab[1] * ac[0])


def _angle_degrees(u: np.ndarray, v: np.ndarray) -> float:
    denom = float(np.linalg.norm(u) * np.linalg.norm(v))
    if denom <= 1e-12:
        return 0.0
    cos_theta = float(np.dot(u, v) / denom)
    return float(np.degrees(np.arccos(np.clip(cos_theta, -1.0, 1.0))))


def _barycentric_2d(point: np.ndarray, tri_uv: np.ndarray) -> np.ndarray | None:
    a, b, c = tri_uv
    mat = np.column_stack([b - a, c - a])
    det = float(np.linalg.det(mat))
    if abs(det) <= 1e-14:
        return None
    u, v = np.linalg.solve(mat, point - a)
    return np.array([1.0 - u - v, u, v], dtype=float)
