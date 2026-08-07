"""Visualization helpers for remesh QC diagnosis."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.tri as mtri
import numpy as np
import trimesh
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from .remesh import RegionRemeshResult, RepairedSamples, classify_remesh_qc_status


def classify_region_qc(sample_tag: str, result: RegionRemeshResult) -> dict[str, object]:
    """Return the same QC status policy used by the remesh CLI."""
    n_samples = int(len(result.sample_points_3d))
    n_unmapped = int(result.located_samples.unmapped_count)
    n_degenerate = int(result.parameterization.degenerate_face_count)
    status = classify_remesh_qc_status(n_samples, n_unmapped, n_degenerate)

    return {
        "sample_tag": sample_tag,
        "region_id": result.region_id,
        "region_name": result.region_name,
        "sample_point_count": n_samples,
        "expected_point_count": int(len(result.template.barycentric)),
        "unmapped_count": n_unmapped,
        "unmapped_ratio": float(n_unmapped / max(n_samples, 1)),
        "flipped_faces": int(result.parameterization.flipped_face_count),
        "degenerate_faces": n_degenerate,
        "patch_face_count": int(len(result.patch.face_ids)),
        "remesh_face_count": int(len(result.template.faces)),
        "status": status,
    }


def classify_repaired_region_qc(
    sample_tag: str,
    result: RegionRemeshResult,
    repaired: RepairedSamples,
) -> dict[str, object]:
    """Return QC fields for repaired samples while preserving raw counts."""
    n_samples = int(len(repaired.points_3d))
    raw_unmapped = int(result.located_samples.unmapped_count)
    repaired_unmapped = int(repaired.repaired_unmapped_count)
    n_degenerate = int(result.parameterization.degenerate_face_count)

    return {
        "sample_tag": sample_tag,
        "region_id": result.region_id,
        "region_name": result.region_name,
        "sample_point_count": n_samples,
        "expected_point_count": int(len(result.template.barycentric)),
        "unmapped_count": repaired_unmapped,
        "unmapped_ratio": float(repaired_unmapped / max(n_samples, 1)),
        "raw_unmapped_count": raw_unmapped,
        "raw_unmapped_ratio": float(raw_unmapped / max(n_samples, 1)),
        "raw_status": repaired.raw_status,
        "repaired_unmapped_count": repaired_unmapped,
        "repair_count": int(repaired.repaired_count),
        "repair_applied": bool(repaired.repaired_count > 0),
        "salvage_attempted": bool(repaired.salvage_attempted),
        "salvage_accepted": bool(repaired.salvage_accepted),
        "salvage_rejection_reason": repaired.salvage_rejection_reason,
        "degenerate_ratio": float(repaired.degenerate_ratio),
        "degenerate_before": int(repaired.degenerate_before),
        "degenerate_after": int(repaired.degenerate_after),
        "degenerate_salvage_attempted": bool(repaired.degenerate_salvage_attempted),
        "degenerate_salvage_accepted": bool(repaired.degenerate_salvage_accepted),
        "degenerate_salvage_method": repaired.degenerate_salvage_method,
        "degenerate_salvage_rejection_reason": repaired.degenerate_salvage_rejection_reason,
        "dense_validation_resolution": int(repaired.dense_validation_resolution),
        "dense_unmapped_count": int(repaired.dense_unmapped_count),
        "dense_degenerate_face_count": int(repaired.dense_degenerate_face_count),
        "dense_min_triangle_area_3d": float(repaired.dense_min_triangle_area_3d),
        "dense_failure_type": repaired.dense_failure_type,
        "dense_coverage_repair_attempted": bool(repaired.dense_coverage_repair_attempted),
        "dense_coverage_repair_accepted": bool(repaired.dense_coverage_repair_accepted),
        "dense_coverage_repair_before": int(repaired.dense_coverage_repair_before),
        "dense_coverage_repair_after": int(repaired.dense_coverage_repair_after),
        "dense_coverage_repair_max_uv_displacement": float(repaired.dense_coverage_repair_max_uv_displacement),
        "degenerate_component_count": int(repaired.degenerate_component_count),
        "largest_degenerate_component_faces": int(repaired.largest_degenerate_component_faces),
        "degenerate_component_touches_boundary": bool(repaired.degenerate_component_touches_boundary),
        "degenerate_component_repair_attempted": bool(repaired.degenerate_component_repair_attempted),
        "degenerate_component_repair_accepted": bool(repaired.degenerate_component_repair_accepted),
        "degenerate_relaxation_seconds": float(repaired.repair_timing.degenerate_relaxation_seconds),
        "component_repair_seconds": float(repaired.repair_timing.component_repair_seconds),
        "dense_validation_seconds": float(repaired.repair_timing.dense_validation_seconds),
        "dense_coverage_repair_seconds": float(repaired.repair_timing.dense_coverage_repair_seconds),
        "repair_total_seconds": float(repaired.repair_timing.total_seconds),
        "flipped_faces": int(result.parameterization.flipped_face_count),
        "degenerate_faces": n_degenerate,
        "patch_face_count": int(len(result.patch.face_ids)),
        "remesh_face_count": int(len(result.template.faces)),
        "status": repaired.status,
    }


def save_region_qc_figure(
    mesh: trimesh.Trimesh,
    result: RegionRemeshResult,
    out_path: str | Path,
    *,
    max_patch_faces: int = 5000,
) -> Path:
    """Save one PNG showing 3D patch/boundaries and 2D unmapped samples."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(13, 6), dpi=150)
    ax_3d = fig.add_subplot(1, 2, 1, projection="3d")
    ax_uv = fig.add_subplot(1, 2, 2)

    _plot_patch_3d(ax_3d, mesh, result, max_patch_faces=max_patch_faces)
    _plot_uv_qc(ax_uv, result)

    record = classify_region_qc("", result)
    fig.suptitle(
        f"{result.region_id} | {record['status']} | "
        f"unmapped={record['unmapped_count']}/{record['sample_point_count']} | "
        f"patch_faces={record['patch_face_count']}",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def save_region_repaired_qc_figure(
    mesh: trimesh.Trimesh,
    result: RegionRemeshResult,
    repaired: RepairedSamples,
    out_path: str | Path,
    *,
    max_patch_faces: int = 5000,
) -> Path:
    """Save one PNG showing 3D patch/boundaries and repaired sample state."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(13, 6), dpi=150)
    ax_3d = fig.add_subplot(1, 2, 1, projection="3d")
    ax_uv = fig.add_subplot(1, 2, 2)

    _plot_patch_3d(ax_3d, mesh, result, max_patch_faces=max_patch_faces)
    _plot_uv_repaired_qc(ax_uv, result, repaired)

    record = classify_repaired_region_qc("", result, repaired)
    fig.suptitle(
        f"{result.region_id} | raw={record['raw_status']} -> repaired={record['status']} | "
        f"repairs={record['repair_count']} | "
        f"unmapped={record['repaired_unmapped_count']}/{record['sample_point_count']} | "
        f"degenerate={record['degenerate_before']}->{record['degenerate_after']}",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _plot_patch_3d(
    ax,
    mesh: trimesh.Trimesh,
    result: RegionRemeshResult,
    *,
    max_patch_faces: int,
) -> None:
    vertices = np.asarray(result.patch.local_vertices, dtype=float)
    faces = np.asarray(result.patch.local_faces, dtype=int)
    faces_to_plot = _sample_faces(faces, max_patch_faces)
    if len(faces_to_plot) > 0:
        collection = Poly3DCollection(
            vertices[faces_to_plot],
            facecolor="#8ecae6",
            edgecolor="#4a4a4a",
            linewidths=0.05,
            alpha=0.35,
        )
        ax.add_collection3d(collection)

    mesh_vertices = np.asarray(mesh.vertices, dtype=float)
    boundary_specs = [
        ("AB", result.boundary_paths.path_ab, "#d62828"),
        ("BC", result.boundary_paths.path_bc, "#2a9d8f"),
        ("CA", result.boundary_paths.path_ca, "#f77f00"),
    ]
    for label, path, color in boundary_specs:
        coords = mesh_vertices[np.asarray(path, dtype=int)]
        ax.plot(coords[:, 0], coords[:, 1], coords[:, 2], color=color, linewidth=1.8, label=label)

    for lm_id, snapped in result.snapped_landmarks.items():
        xyz = snapped.snapped_xyz
        ax.scatter([xyz[0]], [xyz[1]], [xyz[2]], color="black", s=24)
        ax.text(xyz[0], xyz[1], xyz[2], lm_id, fontsize=8)

    ax.set_title("3D patch, boundary paths, landmarks")
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    ax.legend(loc="upper right", fontsize=8)
    _set_axes_equal(ax, vertices)


def _plot_uv_qc(ax, result: RegionRemeshResult) -> None:
    uv = np.asarray(result.parameterization.uv, dtype=float)
    faces = np.asarray(result.parameterization.local_faces, dtype=int)
    if len(faces) > 0:
        triangulation = mtri.Triangulation(uv[:, 0], uv[:, 1], faces)
        ax.triplot(triangulation, color="#b0b0b0", linewidth=0.35, alpha=0.55)

    sample_uv = np.asarray(result.template.uv, dtype=float)
    unmapped = np.asarray(result.located_samples.unmapped_mask, dtype=bool)
    mapped = ~unmapped
    if mapped.any():
        ax.scatter(sample_uv[mapped, 0], sample_uv[mapped, 1], s=18, color="#1f77b4", label="mapped")
    if unmapped.any():
        ax.scatter(
            sample_uv[unmapped, 0],
            sample_uv[unmapped, 1],
            s=46,
            marker="x",
            linewidths=1.6,
            color="#d62828",
            label="unmapped",
        )

    triangle = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])
    ax.plot(triangle[:, 0], triangle[:, 1], color="black", linewidth=1.0)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.set_title("2D UV patch and template samples")
    ax.set_xlabel("u")
    ax.set_ylabel("v")
    ax.legend(loc="upper right", fontsize=8)


def _plot_uv_repaired_qc(
    ax,
    result: RegionRemeshResult,
    repaired: RepairedSamples,
) -> None:
    uv = np.asarray(
        result.parameterization.uv if repaired.repaired_uv is None else repaired.repaired_uv,
        dtype=float,
    )
    faces = np.asarray(result.parameterization.local_faces, dtype=int)
    if len(faces) > 0:
        triangulation = mtri.Triangulation(uv[:, 0], uv[:, 1], faces)
        ax.triplot(triangulation, color="#b0b0b0", linewidth=0.35, alpha=0.55)

    sample_uv = np.asarray(result.template.uv, dtype=float)
    raw_unmapped = np.asarray(result.located_samples.unmapped_mask, dtype=bool)
    repaired_mask = np.asarray(repaired.repaired_mask, dtype=bool)
    repaired_unmapped = ~np.isfinite(np.asarray(repaired.points_3d, dtype=float)).all(axis=1)
    mapped = ~raw_unmapped
    unrepaired = repaired_unmapped

    if mapped.any():
        ax.scatter(sample_uv[mapped, 0], sample_uv[mapped, 1], s=16, color="#1f77b4", label="raw mapped")
    if repaired_mask.any():
        ax.scatter(
            sample_uv[repaired_mask, 0],
            sample_uv[repaired_mask, 1],
            s=42,
            marker="^",
            linewidths=0.8,
            color="#f77f00",
            edgecolors="black",
            label="repaired",
        )
    if unrepaired.any():
        ax.scatter(
            sample_uv[unrepaired, 0],
            sample_uv[unrepaired, 1],
            s=46,
            marker="x",
            linewidths=1.6,
            color="#d62828",
            label="unrepaired",
        )

    triangle = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])
    ax.plot(triangle[:, 0], triangle[:, 1], color="black", linewidth=1.0)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.set_title("2D repaired template samples")
    ax.set_xlabel("u")
    ax.set_ylabel("v")
    ax.legend(loc="upper right", fontsize=8)


def _sample_faces(faces: np.ndarray, max_faces: int) -> np.ndarray:
    if len(faces) <= max_faces:
        return faces
    indices = np.linspace(0, len(faces) - 1, max_faces, dtype=int)
    return faces[indices]


def _set_axes_equal(ax, points: np.ndarray) -> None:
    if points.size == 0:
        return
    mins = np.nanmin(points, axis=0)
    maxs = np.nanmax(points, axis=0)
    center = (mins + maxs) / 2.0
    radius = float(np.max(maxs - mins) / 2.0)
    if radius <= 0:
        radius = 1.0
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)
