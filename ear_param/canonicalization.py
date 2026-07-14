"""Convert paired ear inputs into a canonical left-ear coordinate convention."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd
import trimesh


@dataclass(frozen=True)
class CanonicalSample:
    mesh: trimesh.Trimesh
    landmarks: pd.DataFrame
    source_side: str
    canonical_side: str
    mirrored: bool
    mirror_axis: str
    mesh_path: Path
    landmarks_path: Path
    audit_path: Path


def canonicalize_sample(
    sample_tag: str,
    mesh_path: Path,
    landmarks_path: Path,
    out_dir: Path,
    *,
    canonical_side: str = "L",
    mirror_axis: str = "x",
) -> CanonicalSample:
    """Copy L inputs or reflect R inputs into an auditable canonical layer."""
    source_side = _side_from_tag(sample_tag)
    canonical_side = canonical_side.upper()
    if canonical_side != "L":
        raise ValueError("only canonical_side='L' is supported")
    axis = _axis_index(mirror_axis)
    mesh = trimesh.load_mesh(mesh_path, process=False)
    landmarks = pd.read_csv(landmarks_path)
    required = {"x", "y", "z"}
    if missing := required.difference(landmarks.columns):
        raise ValueError(f"landmarks missing columns: {sorted(missing)}")
    vertices = np.asarray(mesh.vertices, dtype=float).copy()
    faces = np.asarray(mesh.faces, dtype=int).copy()
    if not np.isfinite(vertices).all() or not np.isfinite(landmarks[["x", "y", "z"]].to_numpy(float)).all():
        raise ValueError("mesh and landmarks must contain finite coordinates")
    mirrored = source_side != canonical_side
    if mirrored:
        vertices[:, axis] *= -1.0
        faces = faces[:, ::-1]
        landmarks = landmarks.copy()
        landmarks.loc[:, ("x", "y", "z")[axis]] *= -1.0
    canonical_mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_mesh = out_dir / f"{sample_tag}.ply"
    output_landmarks = out_dir / f"{sample_tag}_landmarks.csv"
    audit_path = out_dir / f"{sample_tag}_canonical_audit.json"
    canonical_mesh.export(output_mesh)
    landmarks.to_csv(output_landmarks, index=False)
    audit_path.write_text(json.dumps({
        "sample_tag": sample_tag, "source_side": source_side,
        "canonical_side": canonical_side, "mirrored": mirrored,
        "mirror_axis": mirror_axis.lower(),
    }, indent=2) + "\n", encoding="utf-8")
    return CanonicalSample(canonical_mesh, landmarks, source_side, canonical_side, mirrored, mirror_axis.lower(), output_mesh, output_landmarks, audit_path)


def _side_from_tag(sample_tag: str) -> str:
    if "_" not in sample_tag:
        raise ValueError(f"sample tag must end in _L or _R: {sample_tag}")
    side = sample_tag.rsplit("_", 1)[1].upper()
    if side not in {"L", "R"}:
        raise ValueError(f"sample tag must end in _L or _R: {sample_tag}")
    return side


def _axis_index(axis: str) -> int:
    try:
        return {"x": 0, "y": 1, "z": 2}[axis.lower()]
    except KeyError as exc:
        raise ValueError("mirror_axis must be x, y, or z") from exc
