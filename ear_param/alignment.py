"""Rigid landmark alignment for whole-ear PCA inputs."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RigidTransform:
    """Rotation and translation mapping source coordinates to a target."""

    rotation: np.ndarray
    translation: np.ndarray
    rms_residual: float
    max_residual: float


@dataclass(frozen=True)
class ProcrustesResult:
    """Final rigid transforms and mean landmarks from iterative alignment."""

    mean_landmarks: np.ndarray
    transforms: dict[str, RigidTransform]
    aligned_landmarks: dict[str, np.ndarray]
    iterations: int
    converged: bool
    final_delta: float


@dataclass(frozen=True)
class FixedReferenceResult:
    """Rigid transforms mapping every sample to one named reference ear."""

    reference_sample: str
    reference_landmarks: np.ndarray
    transforms: dict[str, RigidTransform]
    aligned_landmarks: dict[str, np.ndarray]


def rigid_kabsch(source: np.ndarray, target: np.ndarray) -> RigidTransform:
    """Find the proper rigid transform minimizing landmark squared error."""
    source = _validate_landmarks(source, "source")
    target = _validate_landmarks(target, "target")
    if source.shape != target.shape:
        raise ValueError("source and target landmarks must have the same shape")

    source_centroid = source.mean(axis=0)
    target_centroid = target.mean(axis=0)
    source_centered = source - source_centroid
    target_centered = target - target_centroid
    if np.linalg.matrix_rank(source_centered) < 2 or np.linalg.matrix_rank(target_centered) < 2:
        raise ValueError("alignment landmarks must not be collinear")

    covariance = source_centered.T @ target_centered
    left, _, right_t = np.linalg.svd(covariance)
    correction = np.eye(3)
    if np.linalg.det(right_t.T @ left.T) < 0:
        correction[-1, -1] = -1.0
    rotation = right_t.T @ correction @ left.T
    translation = target_centroid - rotation @ source_centroid

    aligned = (rotation @ source.T).T + translation
    residuals = np.linalg.norm(aligned - target, axis=1)
    return RigidTransform(
        rotation=rotation,
        translation=translation,
        rms_residual=float(np.sqrt(np.mean(np.square(residuals)))),
        max_residual=float(residuals.max()),
    )


def apply_rigid_transform(points: np.ndarray, transform: RigidTransform) -> np.ndarray:
    """Apply one rigid transform to any ordered set of 3D points."""
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points must have shape (N, 3)")
    if not np.isfinite(points).all():
        raise ValueError("points must contain only finite coordinates")
    return (transform.rotation @ points.T).T + transform.translation


def generalized_procrustes(
    landmark_sets: dict[str, np.ndarray],
    *,
    reference_sample: str | None = None,
    tolerance: float = 1e-8,
    max_iterations: int = 20,
) -> ProcrustesResult:
    """Iteratively align samples to their rigid-only mean landmark set."""
    if len(landmark_sets) < 2:
        raise ValueError("Generalized Procrustes requires at least two samples")
    if tolerance <= 0 or max_iterations < 1:
        raise ValueError("tolerance must be positive and max_iterations must be >= 1")

    ordered_ids = sorted(landmark_sets)
    validated = {
        sample_id: _validate_landmarks(landmark_sets[sample_id], sample_id)
        for sample_id in ordered_ids
    }
    shapes = {landmarks.shape for landmarks in validated.values()}
    if len(shapes) != 1:
        raise ValueError("all landmark sets must have the same shape")
    reference_id = reference_sample or ordered_ids[0]
    if reference_id not in validated:
        raise ValueError(f"reference sample not found: {reference_id}")

    target = validated[reference_id].copy()
    transforms: dict[str, RigidTransform] = {}
    aligned: dict[str, np.ndarray] = {}
    final_delta = np.inf
    converged = False
    iterations = 0
    for iteration in range(1, max_iterations + 1):
        transforms = {
            sample_id: rigid_kabsch(landmarks, target)
            for sample_id, landmarks in validated.items()
        }
        aligned = {
            sample_id: apply_rigid_transform(validated[sample_id], transform)
            for sample_id, transform in transforms.items()
        }
        new_target = np.mean(np.stack(list(aligned.values()), axis=0), axis=0)
        final_delta = float(np.sqrt(np.mean(np.square(new_target - target))))
        target = new_target
        iterations = iteration
        if final_delta <= tolerance:
            converged = True
            break

    transforms = {
        sample_id: rigid_kabsch(landmarks, target)
        for sample_id, landmarks in validated.items()
    }
    aligned = {
        sample_id: apply_rigid_transform(validated[sample_id], transform)
        for sample_id, transform in transforms.items()
    }
    mean_landmarks = np.mean(np.stack(list(aligned.values()), axis=0), axis=0)
    return ProcrustesResult(
        mean_landmarks=mean_landmarks,
        transforms=transforms,
        aligned_landmarks=aligned,
        iterations=iterations,
        converged=converged,
        final_delta=final_delta,
    )


def fixed_reference_alignment(
    landmark_sets: dict[str, np.ndarray],
    *,
    reference_sample: str,
) -> FixedReferenceResult:
    """Rigidly align each landmark set to one named reference landmark set."""
    if not landmark_sets:
        raise ValueError("at least one landmark set is required")
    if reference_sample not in landmark_sets:
        raise ValueError(f"reference sample not found: {reference_sample}")

    validated = {
        sample_id: _validate_landmarks(landmarks, sample_id)
        for sample_id, landmarks in landmark_sets.items()
    }
    shapes = {landmarks.shape for landmarks in validated.values()}
    if len(shapes) != 1:
        raise ValueError("all landmark sets must have the same shape")

    reference = validated[reference_sample].copy()
    transforms = {
        sample_id: rigid_kabsch(landmarks, reference)
        for sample_id, landmarks in validated.items()
    }
    aligned = {
        sample_id: apply_rigid_transform(validated[sample_id], transform)
        for sample_id, transform in transforms.items()
    }
    return FixedReferenceResult(
        reference_sample=reference_sample,
        reference_landmarks=reference,
        transforms=transforms,
        aligned_landmarks=aligned,
    )


def _validate_landmarks(points: np.ndarray, label: str) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 3:
        raise ValueError(f"{label} landmarks must have shape (K, 3) with K >= 3")
    if not np.isfinite(points).all():
        raise ValueError(f"{label} landmarks must contain only finite coordinates")
    return points
