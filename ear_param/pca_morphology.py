"""Post-PCA morphology extremes, descriptive clustering, and outlier ranking."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist, squareform

from ear_param.pca_average import PcaInput, PcaResult


_MAX_CLUSTER_COUNT = 6
_MIN_CLUSTER_SAMPLE_COUNT = 4
_EXTREME_PERCENTILE = 0.95


@dataclass(frozen=True)
class PcaMorphologyAnalysis:
    """Auditable morphology analysis derived from an already fitted PCA."""

    summary: pd.DataFrame
    pc_extreme_shapes: pd.DataFrame
    observed_pc_extremes: pd.DataFrame
    multivariate_extremes: pd.DataFrame
    cluster_k_selection: pd.DataFrame
    cluster_assignments: pd.DataFrame
    cluster_summary: pd.DataFrame
    cluster_mean_points: dict[str, np.ndarray]
    aligned_dir: Path


def analyze_pca_morphology(
    inputs: PcaInput,
    result: PcaResult,
    *,
    variance_threshold: float,
    aligned_dir: Path,
) -> PcaMorphologyAnalysis:
    """Describe PCA extremes without changing the fitted PCA or any QC status."""
    if not 0.0 < variance_threshold <= 1.0:
        raise ValueError("variance_threshold must be in (0, 1]")

    order = np.argsort(np.asarray(inputs.sample_tags, dtype=str), kind="stable")
    sample_tags = tuple(str(inputs.sample_tags[index]) for index in order)
    points = inputs.points[order]
    retained_names, retained_scores = _retained_scores(result, order)
    standardized_scores, active_names = _standardize_scores(retained_scores, retained_names)

    cluster_selection, assignments, cluster_summary, cluster_mean_points, cluster_status, selected_count = (
        _cluster_samples(
            sample_tags,
            retained_scores,
            retained_names,
            standardized_scores,
            active_names,
            points,
        )
    )
    observed_extremes = _directional_extremes(
        sample_tags,
        retained_scores,
        retained_names,
        standardized_scores,
        active_names,
        assignments,
    )
    multivariate_extremes = _multivariate_extremes(
        sample_tags,
        retained_scores,
        retained_names,
        standardized_scores,
        assignments,
    )
    summary = pd.DataFrame([{
        "status": "PASS",
        "reason": "",
        "included_sample_count": len(sample_tags),
        "feature_component_count": len(active_names),
        "feature_components": ";".join(active_names),
        "variance_threshold": float(variance_threshold),
        "cluster_status": cluster_status,
        "selected_cluster_count": int(selected_count),
        "extreme_percentile_threshold": _EXTREME_PERCENTILE,
    }])
    return PcaMorphologyAnalysis(
        summary=summary,
        pc_extreme_shapes=_pc_extreme_shapes(result),
        observed_pc_extremes=observed_extremes,
        multivariate_extremes=multivariate_extremes,
        cluster_k_selection=cluster_selection,
        cluster_assignments=assignments,
        cluster_summary=cluster_summary,
        cluster_mean_points=cluster_mean_points,
        aligned_dir=Path(aligned_dir),
    )


def _retained_scores(result: PcaResult, order: np.ndarray) -> tuple[list[str], np.ndarray]:
    count = min(int(result.n_components_75), len(result.components))
    names = [f"PC{index:02d}" for index in range(1, count + 1)]
    return names, np.asarray(result.scores[order, :count], dtype=float)


def _standardize_scores(scores: np.ndarray, names: list[str]) -> tuple[np.ndarray, list[str]]:
    if not len(names):
        return np.empty((len(scores), 0), dtype=float), []
    means = scores.mean(axis=0)
    deviations = scores.std(axis=0, ddof=0)
    tolerance = np.finfo(float).eps * np.maximum(np.abs(means), 1.0)
    keep = deviations > tolerance
    if not np.any(keep):
        return np.empty((len(scores), 0), dtype=float), []
    return (scores[:, keep] - means[keep]) / deviations[keep], [
        name for name, retained in zip(names, keep) if retained
    ]


def _pc_extreme_shapes(result: PcaResult) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for component_index, component in enumerate(("PC01", "PC02")):
        available = component_index < len(result.components)
        for direction in ("plus", "minus"):
            records.append({
                "component": component,
                "direction": direction,
                "std_multiplier": 2.0,
                "explained_variance_ratio": (
                    float(result.explained_variance_ratio[component_index]) if available else np.nan
                ),
                "relative_ply_path": (
                    f"pc_modes/{component}_{direction}_2sd.ply" if available else ""
                ),
                "status": "available" if available else "unavailable_insufficient_nonzero_components",
            })
    return pd.DataFrame(records)


def _cluster_samples(
    sample_tags: tuple[str, ...],
    raw_scores: np.ndarray,
    score_names: list[str],
    features: np.ndarray,
    feature_names: list[str],
    points: np.ndarray,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, np.ndarray], str, int]:
    if len(sample_tags) < _MIN_CLUSTER_SAMPLE_COUNT:
        return _empty_cluster_outputs(), pd.DataFrame(), pd.DataFrame(), {}, "insufficient_sample_count", 0
    if not feature_names:
        return _empty_cluster_outputs(), pd.DataFrame(), pd.DataFrame(), {}, "no_nonzero_score_variance", 0

    linkage_matrix = linkage(features, method="ward")
    candidates: list[dict[str, object]] = []
    valid_labels: dict[int, np.ndarray] = {}
    for cluster_count in range(2, min(_MAX_CLUSTER_COUNT, len(sample_tags) - 1) + 1):
        labels = fcluster(linkage_matrix, cluster_count, criterion="maxclust")
        unique_labels = np.unique(labels)
        if len(unique_labels) < 2 or len(unique_labels) >= len(sample_tags):
            candidates.append({
                "cluster_count": cluster_count,
                "observed_cluster_count": len(unique_labels),
                "silhouette_score": np.nan,
                "status": "unavailable_invalid_cluster_partition",
                "selected": False,
            })
            continue
        score = _average_silhouette(features, labels)
        candidates.append({
            "cluster_count": cluster_count,
            "observed_cluster_count": len(unique_labels),
            "silhouette_score": score,
            "status": "available" if np.isfinite(score) else "unavailable_nonfinite_silhouette",
            "selected": False,
        })
        if np.isfinite(score):
            valid_labels[cluster_count] = labels

    selection = pd.DataFrame(candidates)
    if not valid_labels:
        return selection, pd.DataFrame(), pd.DataFrame(), {}, "no_valid_cluster_candidate", 0

    selected_count = min(
        valid_labels,
        key=lambda count: (-float(selection.loc[
            selection["cluster_count"] == count, "silhouette_score"
        ].iloc[0]), count),
    )
    selection.loc[selection["cluster_count"] == selected_count, "selected"] = True
    assignments, summary, means = _label_clusters(
        sample_tags,
        raw_scores,
        score_names,
        valid_labels[selected_count],
        points,
    )
    return selection, assignments, summary, means, "PASS", selected_count


def _empty_cluster_outputs() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "cluster_count", "observed_cluster_count", "silhouette_score", "status", "selected",
    ])


def _average_silhouette(features: np.ndarray, labels: np.ndarray) -> float:
    """Compute mean silhouette without adding a scikit-learn dependency."""
    distances = squareform(pdist(features, metric="euclidean"))
    values: list[float] = []
    for index, label in enumerate(labels):
        own_indices = np.flatnonzero(labels == label)
        if len(own_indices) <= 1:
            values.append(0.0)
            continue
        other_own = own_indices[own_indices != index]
        intra_distance = float(distances[index, other_own].mean())
        nearest_other_distance = min(
            float(distances[index, labels == other_label].mean())
            for other_label in np.unique(labels)
            if other_label != label
        )
        denominator = max(intra_distance, nearest_other_distance)
        values.append(
            (nearest_other_distance - intra_distance) / denominator if denominator else 0.0
        )
    return float(np.mean(values))


def _label_clusters(
    sample_tags: tuple[str, ...],
    raw_scores: np.ndarray,
    score_names: list[str],
    labels: np.ndarray,
    points: np.ndarray,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, np.ndarray]]:
    label_order = sorted(
        np.unique(labels),
        key=lambda label: (float(raw_scores[labels == label, 0].mean()), int(label)),
    )
    name_by_label = {
        int(label): f"Cluster {index:02d}"
        for index, label in enumerate(label_order, start=1)
    }
    assignments = pd.DataFrame({"sample_tag": sample_tags})
    for index, name in enumerate(score_names):
        assignments[name] = raw_scores[:, index]
    assignments["cluster_id"] = [name_by_label[int(label)] for label in labels]

    records: list[dict[str, object]] = []
    mean_points: dict[str, np.ndarray] = {}
    for label in label_order:
        cluster_id = name_by_label[int(label)]
        member_indices = np.flatnonzero(labels == label)
        record: dict[str, object] = {
            "cluster_id": cluster_id,
            "sample_count": len(member_indices),
            "member_sample_tags": ";".join(sample_tags[index] for index in member_indices),
            "mean_mesh_relative_path": f"cluster_means/{cluster_id.replace(' ', '_')}_mean.ply",
        }
        for score_index, score_name in enumerate(score_names):
            record[f"mean_{score_name}"] = float(raw_scores[member_indices, score_index].mean())
        records.append(record)
        mean_points[cluster_id] = points[member_indices].mean(axis=0)
    return assignments, pd.DataFrame(records), mean_points


def _directional_extremes(
    sample_tags: tuple[str, ...],
    scores: np.ndarray,
    score_names: list[str],
    standardized_scores: np.ndarray,
    feature_names: list[str],
    assignments: pd.DataFrame,
) -> pd.DataFrame:
    assignment_by_tag = (
        assignments.set_index("sample_tag")["cluster_id"].to_dict()
        if not assignments.empty else {}
    )
    feature_index = {name: index for index, name in enumerate(feature_names)}
    records: list[dict[str, object]] = []
    for component_index, component in enumerate(("PC01", "PC02")):
        if component_index >= len(score_names):
            for direction in ("plus", "minus"):
                records.append({
                    "component": component,
                    "direction": direction,
                    "sample_tag": "",
                    "score": np.nan,
                    "score_z": np.nan,
                    "tie_count": 0,
                    "tied_sample_tags": "",
                    "cluster_id": "",
                    "status": "unavailable_insufficient_nonzero_components",
                })
            continue
        values = scores[:, component_index]
        for direction, target in (("plus", values.max()), ("minus", values.min())):
            tied = sorted(
                sample_tag for sample_tag, value in zip(sample_tags, values) if np.isclose(value, target)
            )
            sample_tag = tied[0]
            sample_index = sample_tags.index(sample_tag)
            records.append({
                "component": component,
                "direction": direction,
                "sample_tag": sample_tag,
                "score": float(target),
                "score_z": (
                    float(standardized_scores[sample_index, feature_index[component]])
                    if component in feature_index else np.nan
                ),
                "tie_count": len(tied),
                "tied_sample_tags": ";".join(tied),
                "cluster_id": assignment_by_tag.get(sample_tag, ""),
                "status": "available",
            })
    return pd.DataFrame(records)


def _multivariate_extremes(
    sample_tags: tuple[str, ...],
    scores: np.ndarray,
    score_names: list[str],
    standardized_scores: np.ndarray,
    assignments: pd.DataFrame,
) -> pd.DataFrame:
    table = pd.DataFrame({"sample_tag": sample_tags})
    for index, name in enumerate(score_names):
        table[name] = scores[:, index]
    table["distance_to_center"] = np.linalg.norm(standardized_scores, axis=1)
    table["distance_percentile"] = table["distance_to_center"].rank(pct=True, method="min")
    table["distance_rank"] = table["distance_to_center"].rank(
        ascending=False, method="min"
    ).astype(int)
    threshold = float(np.quantile(table["distance_to_center"], _EXTREME_PERCENTILE))
    table["is_extreme_candidate"] = table["distance_to_center"] >= threshold
    if assignments.empty:
        table["cluster_id"] = ""
    else:
        table = table.merge(assignments[["sample_tag", "cluster_id"]], on="sample_tag", how="left")
    return table.sort_values(["distance_rank", "sample_tag"], kind="stable").reset_index(drop=True)
