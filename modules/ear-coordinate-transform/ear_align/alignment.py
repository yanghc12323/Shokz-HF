"""Rigid coordinate transformations without scale normalization."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray


FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class RigidTransform:
    """A rotation and translation using ``X' = R @ X + t``."""

    rotation: FloatArray
    translation: FloatArray

    def __post_init__(self) -> None:
        rotation = np.asarray(self.rotation, dtype=float)
        translation = np.asarray(self.translation, dtype=float)
        if rotation.shape != (3, 3):
            raise ValueError(f"rotation must have shape (3, 3), got {rotation.shape}")
        if translation.shape != (3,):
            raise ValueError(
                f"translation must have shape (3,), got {translation.shape}"
            )
        if not np.isfinite(rotation).all() or not np.isfinite(translation).all():
            raise ValueError("rotation and translation must contain finite values")
        object.__setattr__(self, "rotation", rotation)
        object.__setattr__(self, "translation", translation)

    @property
    def matrix(self) -> FloatArray:
        matrix = np.eye(4, dtype=float)
        matrix[:3, :3] = self.rotation
        matrix[:3, 3] = self.translation
        return matrix

    @property
    def determinant(self) -> float:
        return float(np.linalg.det(self.rotation))

    def apply(self, points: ArrayLike) -> FloatArray:
        return apply_transform(points, self.rotation, self.translation)


def _as_points(points: ArrayLike, name: str) -> FloatArray:
    array = np.asarray(points, dtype=float)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError(f"{name} must have shape (N, 3), got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} contains non-finite coordinates")
    return array


def apply_transform(points: ArrayLike, rotation: ArrayLike, translation: ArrayLike) -> FloatArray:
    """Apply ``X' = R @ X + t`` to an ``(N, 3)`` point array."""

    point_array = _as_points(points, "points")
    transform = RigidTransform(np.asarray(rotation, dtype=float), np.asarray(translation, dtype=float))
    return (transform.rotation @ point_array.T).T + transform.translation


def kabsch(source: ArrayLike, target: ArrayLike) -> RigidTransform:
    """Find the least-squares proper rigid transform from source to target.

    No scale is estimated. Reflections are explicitly rejected by correcting the
    SVD solution so that ``det(R)`` is positive.
    """

    source_points = _as_points(source, "source")
    target_points = _as_points(target, "target")
    if source_points.shape != target_points.shape:
        raise ValueError(
            "source and target must have identical shapes, got "
            f"{source_points.shape} and {target_points.shape}"
        )
    if len(source_points) < 3:
        raise ValueError("at least three corresponding landmarks are required")

    source_center = source_points.mean(axis=0)
    target_center = target_points.mean(axis=0)
    source_centered = source_points - source_center
    target_centered = target_points - target_center
    if np.linalg.matrix_rank(source_centered) < 2:
        raise ValueError("source landmarks are degenerate; use non-collinear points")
    if np.linalg.matrix_rank(target_centered) < 2:
        raise ValueError("target landmarks are degenerate; use non-collinear points")

    covariance = source_centered.T @ target_centered
    u, _, vt = np.linalg.svd(covariance)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T

    translation = target_center - rotation @ source_center
    return RigidTransform(rotation=rotation, translation=translation)

