"""End-to-end ear mesh alignment and artifact export."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

from .alignment import RigidTransform, kabsch
from .io import Landmarks, load_mesh, read_landmarks, write_json, write_landmarks
from .mirroring import detect_side_from_filename, mirror_mesh, mirror_points


DEFAULT_LANDMARK_IDS = ("L7", "L13", "L15", "L26")


@dataclass(frozen=True)
class AlignmentResult:
    mesh: trimesh.Trimesh
    landmarks: Landmarks
    transform: RigidTransform
    metrics: dict[str, object]
    mirrored: bool
    output_obj_path: Path
    output_stl_path: Path
    output_landmarks_path: Path
    transform_path: Path
    metrics_path: Path
    reference_centroid: np.ndarray
    output_reference_obj_path: Path | None
    output_reference_stl_path: Path | None
    output_reference_landmarks_path: Path | None


def _select_landmarks(
    reference: Landmarks, moving: Landmarks, landmark_ids: tuple[str, ...]
) -> tuple[np.ndarray, np.ndarray]:
    landmark_ids = tuple(item.strip().upper() for item in landmark_ids)
    if len(set(landmark_ids)) != len(landmark_ids):
        raise ValueError("landmark_ids must not contain duplicates")
    missing_reference = [item for item in landmark_ids if item not in reference]
    missing_moving = [item for item in landmark_ids if item not in moving]
    if missing_reference or missing_moving:
        details: list[str] = []
        if missing_reference:
            details.append(f"missing from reference: {', '.join(missing_reference)}")
        if missing_moving:
            details.append(f"missing from moving: {', '.join(missing_moving)}")
        raise ValueError("required landmarks unavailable (" + "; ".join(details) + ")")
    return (
        np.vstack([reference[item] for item in landmark_ids]),
        np.vstack([moving[item] for item in landmark_ids]),
    )


def _default_sidecar(output_obj_path: Path, filename: str) -> Path:
    return output_obj_path.parent / filename


def align_and_export_mesh(
    ref_mesh_path: str | Path,
    moving_mesh_path: str | Path,
    ref_landmark_csv: str | Path,
    moving_landmark_csv: str | Path,
    output_obj_path: str | Path,
    output_stl_path: str | Path,
    landmark_ids: tuple[str, ...] = DEFAULT_LANDMARK_IDS,
    auto_mirror: bool = True,
    mirror_axis: str = "x",
    output_landmarks_path: str | Path | None = None,
    transform_path: str | Path | None = None,
    metrics_path: str | Path | None = None,
    center_reference: bool = True,
    output_reference_obj_path: str | Path | None = None,
    output_reference_stl_path: str | Path | None = None,
    output_reference_landmarks_path: str | Path | None = None,
    export_centered_reference: bool = True,
) -> AlignmentResult:
    """Align a moving ear and export it in the reference coordinate frame.

    By default, the centroid of the selected reference landmarks becomes the
    origin. This keeps the reference orientation while giving every processed
    ear the same PCA-friendly coordinate origin.
    """

    output_obj = Path(output_obj_path)
    output_stl = Path(output_stl_path)
    if output_obj.suffix.lower() != ".obj":
        raise ValueError("output_obj_path must end in .obj")
    if output_stl.suffix.lower() != ".stl":
        raise ValueError("output_stl_path must end in .stl")

    reference_mesh = load_mesh(ref_mesh_path)
    moving_mesh = load_mesh(moving_mesh_path)
    reference_landmarks = read_landmarks(ref_landmark_csv)
    moving_landmarks = read_landmarks(moving_landmark_csv)

    mirrored = False
    reference_side: str | None = None
    moving_side: str | None = None
    if auto_mirror:
        reference_side = detect_side_from_filename(ref_mesh_path)
        moving_side = detect_side_from_filename(moving_mesh_path)
        if reference_side != moving_side:
            moving_mesh = mirror_mesh(moving_mesh, mirror_axis)
            moving_landmarks = {
                landmark_id: point
                for landmark_id, point in zip(
                    moving_landmarks.keys(),
                    mirror_points(np.vstack(list(moving_landmarks.values())), mirror_axis),
                    strict=True,
                )
            }
            mirrored = True

    selected_ids = tuple(item.strip().upper() for item in landmark_ids)
    reference_selected, moving_selected = _select_landmarks(
        reference_landmarks, moving_landmarks, selected_ids
    )
    transform_to_reference = kabsch(moving_selected, reference_selected)
    reference_centroid = reference_selected.mean(axis=0)
    origin_shift = reference_centroid if center_reference else np.zeros(3, dtype=float)
    transform = RigidTransform(
        rotation=transform_to_reference.rotation,
        translation=transform_to_reference.translation - origin_shift,
    )

    aligned_mesh = moving_mesh.copy()
    original_faces = np.asarray(moving_mesh.faces).copy()
    aligned_mesh.vertices = transform.apply(np.asarray(moving_mesh.vertices))
    if not np.array_equal(np.asarray(aligned_mesh.faces), original_faces):
        raise RuntimeError("face topology changed while applying the rigid transform")

    landmark_names = list(moving_landmarks.keys())
    aligned_points = transform.apply(np.vstack(list(moving_landmarks.values())))
    aligned_landmarks = {
        landmark_id: point
        for landmark_id, point in zip(landmark_names, aligned_points, strict=True)
    }

    aligned_selected = np.vstack([aligned_landmarks[item] for item in selected_ids])
    reference_selected_standard = reference_selected - origin_shift
    errors = np.linalg.norm(aligned_selected - reference_selected_standard, axis=1)
    metrics: dict[str, object] = {
        "landmark_ids": list(selected_ids),
        "per_landmark_error": {
            landmark_id: float(error)
            for landmark_id, error in zip(selected_ids, errors, strict=True)
        },
        "mean_error": float(np.mean(errors)),
        "rms_error": float(np.sqrt(np.mean(np.square(errors)))),
        "max_error": float(np.max(errors)),
    }

    output_landmarks = Path(output_landmarks_path) if output_landmarks_path else _default_sidecar(output_obj, "moving_landmarks_aligned.csv")
    transform_json = Path(transform_path) if transform_path else _default_sidecar(output_obj, "transform.json")
    metrics_json = Path(metrics_path) if metrics_path else _default_sidecar(output_obj, "metrics.json")
    reference_obj: Path | None = None
    reference_stl: Path | None = None
    reference_landmarks_output: Path | None = None
    if center_reference and export_centered_reference:
        reference_stem = Path(ref_mesh_path).stem
        reference_obj = Path(output_reference_obj_path) if output_reference_obj_path else _default_sidecar(output_obj, f"{reference_stem}_centered.obj")
        reference_stl = Path(output_reference_stl_path) if output_reference_stl_path else _default_sidecar(output_obj, f"{reference_stem}_centered.stl")
        reference_landmarks_output = Path(output_reference_landmarks_path) if output_reference_landmarks_path else _default_sidecar(output_obj, f"{reference_stem}_landmarks_centered.csv")

    output_paths = [output_obj, output_stl, output_landmarks, transform_json, metrics_json]
    output_paths.extend(path for path in (reference_obj, reference_stl, reference_landmarks_output) if path is not None)
    for path in output_paths:
        path.parent.mkdir(parents=True, exist_ok=True)

    aligned_mesh.export(output_obj)
    aligned_mesh.export(output_stl)
    write_landmarks(output_landmarks, aligned_landmarks)
    if center_reference and export_centered_reference:
        centered_reference_mesh = reference_mesh.copy()
        centered_reference_mesh.vertices = np.asarray(reference_mesh.vertices) - reference_centroid
        centered_reference_landmarks = {
            landmark_id: point - reference_centroid
            for landmark_id, point in reference_landmarks.items()
        }
        assert reference_obj is not None
        assert reference_stl is not None
        assert reference_landmarks_output is not None
        centered_reference_mesh.export(reference_obj)
        centered_reference_mesh.export(reference_stl)
        write_landmarks(reference_landmarks_output, centered_reference_landmarks)
    write_json(
        transform_json,
        {
            "R": transform.rotation.tolist(),
            "t": transform.translation.tolist(),
            "matrix": transform.matrix.tolist(),
            "det_R": transform.determinant,
            "t_to_original_reference": transform_to_reference.translation.tolist(),
            "center_reference": center_reference,
            "reference_landmark_centroid_original": reference_centroid.tolist(),
            "origin_landmark_ids": list(selected_ids),
            "origin_definition": "centroid of selected reference landmarks" if center_reference else "original reference origin",
            "mirrored": mirrored,
            "mirror_axis": mirror_axis if mirrored else None,
            "reference_side": reference_side,
            "moving_side": moving_side,
        },
    )
    write_json(metrics_json, metrics)

    return AlignmentResult(
        mesh=aligned_mesh,
        landmarks=aligned_landmarks,
        transform=transform,
        metrics=metrics,
        mirrored=mirrored,
        output_obj_path=output_obj,
        output_stl_path=output_stl,
        output_landmarks_path=output_landmarks,
        transform_path=transform_json,
        metrics_path=metrics_json,
        reference_centroid=reference_centroid,
        output_reference_obj_path=reference_obj,
        output_reference_stl_path=reference_stl,
        output_reference_landmarks_path=reference_landmarks_output,
    )
