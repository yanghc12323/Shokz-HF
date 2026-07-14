"""CSV, mesh, and result serialization helpers."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import trimesh


Landmarks = dict[str, np.ndarray]


def read_landmarks(path: str | Path) -> Landmarks:
    """Read a landmark CSV and reject malformed or duplicate IDs.

    The identifier column may be named ``landmark`` (the format used by the
    source data) or ``landmark_id`` (the legacy format). Header matching is
    case-insensitive and ignores surrounding whitespace. All rows are loaded;
    the alignment pipeline later selects only the requested IDs.
    """

    csv_path = Path(path)
    landmarks: Landmarks = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{csv_path} has no header row")
        columns = {
            name.strip().lower(): name
            for name in reader.fieldnames
            if name is not None and name.strip()
        }
        landmark_column = columns.get("landmark") or columns.get("landmark_id")
        coordinate_columns = [columns.get(axis) for axis in ("x", "y", "z")]
        if landmark_column is None or any(column is None for column in coordinate_columns):
            raise ValueError(
                f"{csv_path} must contain columns: landmark,x,y,z "
                "(landmark_id is also accepted)"
            )
        x_column, y_column, z_column = coordinate_columns
        for line_number, row in enumerate(reader, start=2):
            landmark_id = (row.get(landmark_column) or "").strip().upper()
            if not landmark_id:
                raise ValueError(f"{csv_path}:{line_number}: landmark is empty")
            if landmark_id in landmarks:
                raise ValueError(
                    f"{csv_path}:{line_number}: duplicate landmark_id {landmark_id!r}"
                )
            try:
                point = np.array(
                    [float(row[x_column]), float(row[y_column]), float(row[z_column])],
                    dtype=float,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{csv_path}:{line_number}: x, y and z must be numbers"
                ) from exc
            if not np.isfinite(point).all():
                raise ValueError(
                    f"{csv_path}:{line_number}: coordinates must be finite"
                )
            landmarks[landmark_id] = point
    if not landmarks:
        raise ValueError(f"{csv_path} contains no landmarks")
    return landmarks


def write_landmarks(path: str | Path, landmarks: Mapping[str, np.ndarray]) -> None:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["landmark", "x", "y", "z"])
        for landmark_id, point in landmarks.items():
            writer.writerow([landmark_id, *[format(float(value), ".17g") for value in point]])


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    loaded = trimesh.load(Path(path), process=False)
    if isinstance(loaded, trimesh.Scene):
        geometries = tuple(
            geometry for geometry in loaded.geometry.values() if isinstance(geometry, trimesh.Trimesh)
        )
        if not geometries:
            raise ValueError(f"mesh scene contains no geometry: {path}")
        loaded = trimesh.util.concatenate(geometries)
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError(f"unsupported mesh content in {path}")
    if len(loaded.vertices) == 0 or len(loaded.faces) == 0:
        raise ValueError(f"mesh must contain vertices and triangular faces: {path}")
    return loaded


def write_json(path: str | Path, data: Mapping[str, Any]) -> None:
    json_path = Path(path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
