"""Tests for post-PCA morphology extremes, clustering, and outlier analysis."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ear_param.pca_average import PcaInput, PcaResult


FACES = np.array([[0, 1, 2], [0, 2, 3]], dtype=int)
BASE_POINTS = np.array([
    [0.0, 0.0, 0.0],
    [1.0, 0.0, 0.0],
    [1.0, 1.0, 0.0],
    [0.0, 1.0, 0.0],
])


def _inputs_and_result(
    scores: np.ndarray,
    sample_tags: tuple[str, ...] | None = None,
) -> tuple[PcaInput, PcaResult]:
    sample_count = len(scores)
    tags = sample_tags or tuple(f"S{index:03d}_L" for index in range(1, sample_count + 1))
    point_blocks = np.stack([
        BASE_POINTS + [float(index), float(index % 2) * 0.1, 0.0]
        for index in range(sample_count)
    ])
    components = np.zeros((2, BASE_POINTS.size), dtype=float)
    components[0, 0] = 1.0
    components[1, 1] = 1.0
    inputs = PcaInput(
        sample_tags=tags,
        points=point_blocks,
        vertex_ids=np.arange(len(BASE_POINTS), dtype=int),
        faces=FACES,
        face_ids=np.arange(len(FACES), dtype=int),
        manifest=pd.DataFrame({"sample_tag": tags, "included": True}),
    )
    result = PcaResult(
        mean_points=point_blocks.mean(axis=0),
        components=components,
        scores=np.asarray(scores, dtype=float),
        explained_variance=np.array([9.0, 4.0]),
        explained_variance_ratio=np.array([0.69, 0.31]),
        cumulative_explained_variance_ratio=np.array([0.69, 1.0]),
        n_components_75=2,
    )
    return inputs, result


def test_analysis_selects_directional_extremes_and_auto_cluster_count(tmp_path: Path):
    from ear_param.pca_morphology import analyze_pca_morphology

    inputs, result = _inputs_and_result(np.array([
        [-5.0, -6.0],
        [-4.0, -4.0],
        [-3.0, -3.0],
        [-2.0, -2.0],
        [2.0, 2.0],
        [3.0, 3.0],
        [4.0, 4.0],
        [5.0, 6.0],
    ]))

    analysis = analyze_pca_morphology(
        inputs,
        result,
        variance_threshold=0.75,
        aligned_dir=tmp_path / "aligned",
    )

    available = analysis.observed_pc_extremes.loc[
        analysis.observed_pc_extremes["status"] == "available"
    ]
    assert set(available["direction"]) == {"plus", "minus"}
    assert set(available["component"]) == {"PC01", "PC02"}
    assert set(available.loc[available["direction"] == "plus", "sample_tag"]) == {"S008_L"}
    assert set(available.loc[available["direction"] == "minus", "sample_tag"]) == {"S001_L"}
    assert analysis.summary.loc[0, "cluster_status"] == "PASS"
    assert analysis.summary.loc[0, "selected_cluster_count"] == 2
    assert analysis.cluster_assignments["cluster_id"].nunique() == 2
    assert set(analysis.cluster_mean_points) == {"Cluster 01", "Cluster 02"}
    assert analysis.multivariate_extremes["is_extreme_candidate"].any()


def test_analysis_skips_clustering_when_fewer_than_four_samples(tmp_path: Path):
    from ear_param.pca_morphology import analyze_pca_morphology

    inputs, result = _inputs_and_result(np.array([
        [-2.0, -1.0],
        [0.0, 0.0],
        [2.0, 1.0],
    ]))

    analysis = analyze_pca_morphology(
        inputs,
        result,
        variance_threshold=0.75,
        aligned_dir=tmp_path / "aligned",
    )

    assert analysis.summary.loc[0, "cluster_status"] == "insufficient_sample_count"
    assert analysis.summary.loc[0, "selected_cluster_count"] == 0
    assert analysis.cluster_assignments.empty
    assert analysis.cluster_mean_points == {}


def test_analysis_uses_sample_tag_order_to_break_directional_extreme_ties(tmp_path: Path):
    from ear_param.pca_morphology import analyze_pca_morphology

    inputs, result = _inputs_and_result(
        np.array([
            [-2.0, -1.0],
            [2.0, 0.0],
            [2.0, 1.0],
        ]),
        sample_tags=("S003_L", "S002_L", "S001_L"),
    )

    analysis = analyze_pca_morphology(
        inputs,
        result,
        variance_threshold=0.75,
        aligned_dir=tmp_path / "aligned",
    )

    pc01_plus = analysis.observed_pc_extremes.loc[
        (analysis.observed_pc_extremes["component"] == "PC01")
        & (analysis.observed_pc_extremes["direction"] == "plus")
    ].iloc[0]
    assert pc01_plus["sample_tag"] == "S001_L"
    assert pc01_plus["tie_count"] == 2
    assert pc01_plus["tied_sample_tags"] == "S001_L;S002_L"
