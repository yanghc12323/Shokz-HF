#!/usr/bin/env python3
"""Rigidly align PCA-ready welded whole-ear samples."""

from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import trimesh

from ear_param.alignment import (
    apply_rigid_transform,
    fixed_reference_alignment,
    generalized_procrustes,
)
from ear_param.pipeline import landmark_tag_for_sample, split_sample_tag


DEFAULT_LANDMARKS = ("L7", "L13", "L15", "L26")


def _landmark_path(landmarks_dir: Path, sample_tag: str) -> Path:
    """Prefer canonical outputs; fall back to the source T landmark name for MQ meshes."""
    canonical_path = landmarks_dir / f"{sample_tag}_landmarks.csv"
    if canonical_path.is_file():
        return canonical_path
    return landmarks_dir / f"{landmark_tag_for_sample(sample_tag)}_landmarks.csv"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Rigid Kabsch/Generalized Procrustes alignment for welded whole ears."
    )
    parser.add_argument("--whole_ear_dir", default="output/whole_ear_r24/salvaged")
    parser.add_argument("--landmarks_dir", default="data/landmarks")
    parser.add_argument("--out_dir", default="output/whole_ear_r24/aligned")
    parser.add_argument("--alignment_landmarks", nargs="+", default=list(DEFAULT_LANDMARKS))
    parser.add_argument("--alignment_mode", choices=("gpa", "fixed_reference"), default="gpa")
    parser.add_argument("--reference_sample", help="Required fixed target for fixed_reference; optional initial target for GPA.")
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--max_iterations", type=int, default=20)
    parser.add_argument("--samples", nargs="+", help="Optional PCA-ready sample tags to align.")
    parser.add_argument("--canonical_side", choices=("L", "R"))
    args = parser.parse_args()

    whole_dir = Path(args.whole_ear_dir)
    landmarks_dir = Path(args.landmarks_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sample_tags = args.samples or _discover_pca_ready_samples(whole_dir)
    if len(sample_tags) < 2:
        raise SystemExit("At least two PCA_READY whole-ear samples are required for alignment.")
    input_layers = {
        _load_input_layer(whole_dir / f"{sample_tag}_weld_qc_summary.csv")
        for sample_tag in sample_tags
    }
    if len(input_layers) != 1:
        raise SystemExit("All aligned samples must come from one whole-ear input layer.")
    input_layer = input_layers.pop()
    sides = {args.canonical_side} if args.canonical_side else {
        split_sample_tag(sample_tag)[1] for sample_tag in sample_tags
    }
    if len(sides) != 1:
        raise SystemExit("Mixed left/right samples require an explicit mirror-normalization stage.")

    landmark_ids = tuple(str(value) for value in args.alignment_landmarks)
    landmark_sets = {
        sample_tag: _load_landmarks(
            _landmark_path(landmarks_dir, sample_tag),
            landmark_ids,
        )
        for sample_tag in sample_tags
    }
    if args.alignment_mode == "fixed_reference":
        if not args.reference_sample:
            raise SystemExit("fixed_reference alignment requires --reference_sample")
        if args.reference_sample not in landmark_sets:
            raise SystemExit("reference_sample must be among the selected PCA-ready samples")
        result = fixed_reference_alignment(
            landmark_sets,
            reference_sample=args.reference_sample,
        )
        target_landmarks = result.reference_landmarks
        target_filename = "fixed_reference_landmarks.csv"
        target_label = f"Reference: {args.reference_sample}"
        iterations, converged, final_delta = 1, True, 0.0
        reference_sample = args.reference_sample
    else:
        result = generalized_procrustes(
            landmark_sets,
            reference_sample=args.reference_sample,
            tolerance=args.tolerance,
            max_iterations=args.max_iterations,
        )
        target_landmarks = result.mean_landmarks
        target_filename = "generalized_procrustes_reference_landmarks.csv"
        target_label = "GPA mean"
        iterations, converged, final_delta = (
            result.iterations,
            result.converged,
            result.final_delta,
        )
        reference_sample = ""

    pd.DataFrame({
        "landmark_id": landmark_ids,
        "x": target_landmarks[:, 0],
        "y": target_landmarks[:, 1],
        "z": target_landmarks[:, 2],
    }).to_csv(out_dir / target_filename, index=False)

    expected_vertex_ids: np.ndarray | None = None
    expected_faces: np.ndarray | None = None
    transform_records: list[dict[str, object]] = []
    qc_records: list[dict[str, object]] = []
    aligned_for_plot: dict[str, np.ndarray] = {}
    for sample_tag in sample_tags:
        points_path = whole_dir / f"{sample_tag}_whole_ear_points.csv"
        faces_path = whole_dir / f"{sample_tag}_whole_ear_faces.csv"
        points = pd.read_csv(points_path).sort_values("global_vertex_id").reset_index(drop=True)
        faces = pd.read_csv(faces_path).sort_values("global_face_id").reset_index(drop=True)
        vertex_ids = points["global_vertex_id"].to_numpy(dtype=int)
        face_values = faces[["global_v0", "global_v1", "global_v2"]].to_numpy(dtype=int)
        if expected_vertex_ids is None:
            expected_vertex_ids = vertex_ids
            expected_faces = face_values
        else:
            if not np.array_equal(vertex_ids, expected_vertex_ids):
                raise SystemExit(f"Global vertex order mismatch: {sample_tag}")
            if not np.array_equal(face_values, expected_faces):
                raise SystemExit(f"Global face topology mismatch: {sample_tag}")

        original_xyz = points[["x", "y", "z"]].to_numpy(dtype=float)
        transform = result.transforms[sample_tag]
        aligned_xyz = apply_rigid_transform(original_xyz, transform)
        aligned_points = points.copy()
        aligned_points[["x", "y", "z"]] = aligned_xyz
        aligned_points.to_csv(
            out_dir / f"{sample_tag}_aligned_whole_ear_points.csv", index=False
        )
        faces.to_csv(out_dir / f"{sample_tag}_aligned_whole_ear_faces.csv", index=False)
        aligned_mesh = trimesh.Trimesh(
            vertices=aligned_xyz,
            faces=face_values,
            process=False,
        )
        aligned_mesh.export(out_dir / f"{sample_tag}_aligned_whole_ear.ply")
        if args.alignment_mode == "fixed_reference":
            aligned_mesh.export(out_dir / f"{sample_tag}_aligned_whole_ear.obj")
            aligned_mesh.export(out_dir / f"{sample_tag}_aligned_whole_ear.stl")
        aligned_for_plot[sample_tag] = aligned_xyz

        distance_error = _max_mesh_edge_distance_error(original_xyz, aligned_xyz, face_values)
        determinant = float(np.linalg.det(transform.rotation))
        alignment_status = _alignment_status(converged, determinant, distance_error)
        transform_records.append(_transform_record(sample_tag, transform, determinant))
        qc_records.append({
            "sample_tag": sample_tag,
            "input_layer": input_layer,
            "alignment_method": args.alignment_mode.upper(),
            "reference_sample": reference_sample,
            "landmark_count": len(landmark_ids),
            "rms_landmark_residual_mm": transform.rms_residual,
            "max_landmark_residual_mm": transform.max_residual,
            "det_rotation": determinant,
            "max_mesh_edge_distance_error_mm": distance_error,
            "gpa_iterations": iterations,
            "gpa_converged": converged,
            "gpa_final_delta": final_delta,
            "status": alignment_status,
        })

    transforms = pd.DataFrame(transform_records)
    qc_summary = pd.DataFrame(qc_records)
    transforms.to_csv(out_dir / "rigid_transforms.csv", index=False)
    qc_summary.to_csv(out_dir / "alignment_qc_summary.csv", index=False)
    _save_alignment_overlay(
        aligned_for_plot,
        result.aligned_landmarks,
        target_landmarks,
        out_dir / "alignment_qc_overlay.png",
        target_label,
    )

    print("[Alignment] PCA-ready samples:", " ".join(sample_tags))
    print("[Alignment] Method:", args.alignment_mode)
    print(
        qc_summary[[
            "sample_tag",
            "rms_landmark_residual_mm",
            "max_landmark_residual_mm",
            "det_rotation",
            "max_mesh_edge_distance_error_mm",
            "status",
        ]].to_string(index=False)
    )


def _discover_pca_ready_samples(whole_dir: Path) -> list[str]:
    suffix = "_weld_qc_summary.csv"
    sample_tags: list[str] = []
    for path in sorted(whole_dir.glob(f"*{suffix}")):
        summary = pd.read_csv(path)
        required = {"status", "pca_ready"}
        missing = required.difference(summary.columns)
        if missing:
            raise SystemExit(f"{path} missing columns: {sorted(missing)}")
        if (
            not summary.empty
            and str(summary.loc[0, "status"]).strip().upper() == "PASS"
            and _as_bool(summary.loc[0, "pca_ready"])
        ):
            sample_tags.append(path.name.removesuffix(suffix))
    return sample_tags


def _load_input_layer(path: Path) -> str:
    summary = pd.read_csv(path)
    if summary.empty or "input_layer" not in summary:
        raise SystemExit(f"{path} missing a non-empty input_layer")
    values = summary["input_layer"].dropna().astype(str).str.strip()
    if values.empty or values.eq("").any():
        raise SystemExit(f"{path} missing a non-empty input_layer")
    values = values.unique()
    if len(values) != 1:
        raise SystemExit(f"{path} must contain one input_layer")
    return values[0]


def _alignment_status(converged: bool, determinant: float, distance_error: float) -> str:
    if converged and abs(determinant - 1.0) <= 1e-8 and distance_error <= 1e-8:
        return "PASS"
    return "FAIL"


def _load_landmarks(path: Path, landmark_ids: tuple[str, ...]) -> np.ndarray:
    landmarks = pd.read_csv(path)
    required = {"landmark_id", "x", "y", "z"}
    missing_columns = required.difference(landmarks.columns)
    if missing_columns:
        raise SystemExit(f"{path} missing columns: {sorted(missing_columns)}")
    indexed = landmarks.set_index(landmarks["landmark_id"].astype(str))
    missing_ids = [landmark_id for landmark_id in landmark_ids if landmark_id not in indexed.index]
    if missing_ids:
        raise SystemExit(f"{path} missing alignment landmarks: {missing_ids}")
    return indexed.loc[list(landmark_ids), ["x", "y", "z"]].to_numpy(dtype=float)


def _transform_record(sample_tag: str, transform, determinant: float) -> dict[str, object]:
    record: dict[str, object] = {
        "sample_tag": sample_tag,
        "det_rotation": determinant,
        "rms_landmark_residual_mm": transform.rms_residual,
        "max_landmark_residual_mm": transform.max_residual,
    }
    for row in range(3):
        for column in range(3):
            record[f"r{row}{column}"] = float(transform.rotation[row, column])
    for axis in range(3):
        record[f"t{axis}"] = float(transform.translation[axis])
    return record


def _max_mesh_edge_distance_error(
    before: np.ndarray,
    after: np.ndarray,
    faces: np.ndarray,
) -> float:
    edges = np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    before_lengths = np.linalg.norm(before[edges[:, 0]] - before[edges[:, 1]], axis=1)
    after_lengths = np.linalg.norm(after[edges[:, 0]] - after[edges[:, 1]], axis=1)
    return float(np.max(np.abs(before_lengths - after_lengths)))


def _save_alignment_overlay(
    aligned_points: dict[str, np.ndarray],
    aligned_landmarks: dict[str, np.ndarray],
    mean_landmarks: np.ndarray,
    output_path: Path,
    target_label: str,
) -> None:
    fig = plt.figure(figsize=(11, 8))
    axis = fig.add_subplot(111, projection="3d")
    colors = plt.cm.tab10(np.linspace(0.0, 1.0, len(aligned_points)))
    all_plotted: list[np.ndarray] = []
    for color, (sample_tag, points) in zip(colors, sorted(aligned_points.items())):
        step = max(len(points) // 800, 1)
        shown = points[::step]
        all_plotted.append(shown)
        axis.scatter(shown[:, 0], shown[:, 1], shown[:, 2], s=2, alpha=0.18, color=color)
        landmarks = aligned_landmarks[sample_tag]
        axis.scatter(
            landmarks[:, 0], landmarks[:, 1], landmarks[:, 2],
            s=28, alpha=0.85, color=color, label=sample_tag,
        )
    axis.scatter(
        mean_landmarks[:, 0], mean_landmarks[:, 1], mean_landmarks[:, 2],
        s=80, marker="x", linewidths=2.5, color="black", label=target_label,
    )
    axis.set_title("Rigid whole-ear alignment QC")
    axis.set_xlabel("X")
    axis.set_ylabel("Y")
    axis.set_zlabel("Z")
    axis.legend(loc="best", fontsize=8)
    _set_axes_equal(axis, np.vstack(all_plotted))
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _set_axes_equal(axis, points: np.ndarray) -> None:
    center = (points.min(axis=0) + points.max(axis=0)) / 2.0
    radius = max(float(np.ptp(points, axis=0).max()) / 2.0, 1e-6)
    axis.set_xlim(center[0] - radius, center[0] + radius)
    axis.set_ylim(center[1] - radius, center[1] + radius)
    axis.set_zlim(center[2] - radius, center[2] + radius)


def _as_bool(value: object) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


if __name__ == "__main__":
    main()
