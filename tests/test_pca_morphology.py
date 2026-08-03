"""Tests for post-PCA morphology extremes, clustering, and outlier analysis."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
import sys

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
PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


def test_write_outputs_creates_auditable_tables_cluster_means_and_figures(tmp_path: Path):
    from ear_param.pca_morphology import (
        analyze_pca_morphology,
        write_pca_morphology_outputs,
    )

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
    out_dir = tmp_path / "pca"
    analysis = analyze_pca_morphology(
        inputs,
        result,
        variance_threshold=0.75,
        aligned_dir=tmp_path / "aligned",
    )

    morphology_dir = write_pca_morphology_outputs(inputs, result, analysis, out_dir=out_dir)

    for name in (
        "pca_morphology_summary.csv",
        "pc_extreme_shapes.csv",
        "observed_pc_extremes.csv",
        "multivariate_extreme_individuals.csv",
        "cluster_k_selection.csv",
        "cluster_assignments.csv",
        "cluster_summary.csv",
    ):
        assert (morphology_dir / name).is_file()
    assert (morphology_dir / "cluster_means" / "Cluster_01_mean.ply").is_file()
    assert (morphology_dir / "figures" / "pc1_pc2_clusters.png").is_file()
    assert (morphology_dir / "figures" / "pc_variance_scree.png").is_file()


def test_write_pca_outputs_writes_pc02_modes_even_when_threshold_retains_only_pc01(tmp_path: Path):
    from ear_param.pca_average import write_pca_outputs

    inputs, result = _inputs_and_result(np.array([
        [-2.0, -1.0],
        [0.0, 0.0],
        [2.0, 1.0],
    ]))
    result = replace(result, n_components_75=1)

    write_pca_outputs(inputs, result, tmp_path / "pca", variance_threshold=0.75)

    assert (tmp_path / "pca" / "pc_modes" / "PC01_plus_2sd.ply").is_file()
    assert (tmp_path / "pca" / "pc_modes" / "PC02_plus_2sd.ply").is_file()
    assert (tmp_path / "pca" / "pc_modes" / "PC02_minus_2sd.ply").is_file()


def test_analysis_keeps_pc02_real_extremes_when_cluster_threshold_retains_only_pc01(tmp_path: Path):
    from ear_param.pca_morphology import analyze_pca_morphology

    inputs, result = _inputs_and_result(np.array([
        [-3.0, -1.0],
        [0.0, 0.0],
        [3.0, 1.0],
    ]))
    result = replace(result, n_components_75=1)

    analysis = analyze_pca_morphology(
        inputs,
        result,
        variance_threshold=0.75,
        aligned_dir=tmp_path / "aligned",
    )

    pc02 = analysis.observed_pc_extremes.loc[
        analysis.observed_pc_extremes["component"] == "PC02"
    ]
    assert set(pc02["status"]) == {"available"}
    assert set(pc02["sample_tag"]) == {"S001_L", "S003_L"}
    assert analysis.summary.loc[0, "feature_components"] == "PC01"


def test_build_average_ear_cli_writes_pca_morphology_outputs(tmp_path: Path):
    aligned_dir = tmp_path / "aligned"
    weld_dir = tmp_path / "weld"
    output_dir = tmp_path / "pca"
    aligned_dir.mkdir()
    weld_dir.mkdir()
    alignment_rows = []
    for index, sample_tag in enumerate(("S001_L", "S002_L", "S003_L", "S004_L")):
        points = BASE_POINTS.copy()
        points[:, 0] += (-2.0, -1.0, 1.0, 2.0)[index]
        points[:, 1] += (-1.0, 1.0, -1.0, 1.0)[index]
        pd.DataFrame({
            "global_vertex_id": np.arange(len(points)),
            "x": points[:, 0],
            "y": points[:, 1],
            "z": points[:, 2],
        }).to_csv(aligned_dir / f"{sample_tag}_aligned_whole_ear_points.csv", index=False)
        pd.DataFrame({
            "global_face_id": np.arange(len(FACES)),
            "global_v0": FACES[:, 0],
            "global_v1": FACES[:, 1],
            "global_v2": FACES[:, 2],
        }).to_csv(aligned_dir / f"{sample_tag}_aligned_whole_ear_faces.csv", index=False)
        pd.DataFrame([{
            "sample_tag": sample_tag,
            "status": "PASS",
            "pca_ready": True,
            "input_layer": "weld_repaired",
        }]).to_csv(weld_dir / f"{sample_tag}_weld_qc_summary.csv", index=False)
        alignment_rows.append({
            "sample_tag": sample_tag,
            "status": "PASS",
            "input_layer": "weld_repaired",
        })
    pd.DataFrame(alignment_rows).to_csv(aligned_dir / "alignment_qc_summary.csv", index=False)

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_average_ear.py",
            "--aligned_dir", str(aligned_dir),
            "--weld_dir", str(weld_dir),
            "--out_dir", str(output_dir),
            "--variance_threshold", "0.75",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "[W3 PCA] Morphology analysis: PASS" in completed.stdout
    assert (output_dir / "pca_morphology" / "pca_morphology_summary.csv").is_file()
