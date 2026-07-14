"""Left/right ear detection and geometry mirroring."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import trimesh


AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def detect_side_from_filename(path: str | Path) -> str:
    """Detect an exact ``L`` or ``R`` filename token (case-insensitive)."""

    tokens = [token for token in re.split(r"[-_.\s]+", Path(path).stem.upper()) if token]
    sides = {token for token in tokens if token in {"L", "R"}}
    if len(sides) != 1:
        raise ValueError(
            f"cannot determine a unique side from filename {path!s}; "
            "use a token such as S001_L.stl or S001_R.obj"
        )
    return sides.pop()


def _axis_index(axis: str) -> int:
    try:
        return AXIS_INDEX[axis.lower()]
    except KeyError as exc:
        raise ValueError("mirror_axis must be one of: x, y, z") from exc


def mirror_points(points: np.ndarray, axis: str = "x") -> np.ndarray:
    mirrored = np.asarray(points, dtype=float).copy()
    if mirrored.ndim != 2 or mirrored.shape[1] != 3:
        raise ValueError(f"points must have shape (N, 3), got {mirrored.shape}")
    mirrored[:, _axis_index(axis)] *= -1.0
    return mirrored


def mirror_mesh(mesh: trimesh.Trimesh, axis: str = "x") -> trimesh.Trimesh:
    """Mirror vertices and reverse every face winding to preserve orientation."""

    mirrored = mesh.copy()
    mirrored.vertices = mirror_points(np.asarray(mirrored.vertices), axis)
    mirrored.faces = np.asarray(mirrored.faces)[:, ::-1]
    return mirrored

