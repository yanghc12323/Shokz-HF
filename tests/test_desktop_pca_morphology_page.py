"""Tests for the dedicated desktop PCA morphology analysis page."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6.QtWidgets import QWidget

from desktop_app.artifact_indexer import ArtifactIndex
from desktop_app.models import ArtifactRef, AttemptRecord, LayerName


class FakeViewer(QWidget):
    """Captures model loads without requiring a VTK render window in tests."""

    def __init__(self) -> None:
        super().__init__()
        self.loaded: list[tuple[LayerName, ArtifactRef]] = []

    def load_layer(self, layer: LayerName, artifact: ArtifactRef) -> None:
        self.loaded.append((layer, artifact))


def _index(tmp_path: Path, *, with_morphology: bool) -> ArtifactIndex:
    attempt = AttemptRecord.create(tmp_path / "project", "run-001", "attempt-001")
    aligned_dir = tmp_path / "aligned"
    pca_dir = tmp_path / "pca"
    aligned_dir.mkdir()
    pca_dir.mkdir()
    (aligned_dir / "T049_L_aligned_whole_ear.ply").write_text("ply\n", encoding="utf-8")
    empty = pd.DataFrame()
    morphology_dir = pca_dir / "pca_morphology" if with_morphology else None
    if morphology_dir is not None:
        (morphology_dir / "cluster_means").mkdir(parents=True)
        (morphology_dir / "pc_modes").mkdir()
        (morphology_dir / "cluster_means" / "Cluster_01_mean.ply").write_text("ply\n", encoding="utf-8")
        (pca_dir / "pc_modes").mkdir()
        (pca_dir / "pc_modes" / "PC01_plus_2sd.ply").write_text("ply\n", encoding="utf-8")
        figure_path = morphology_dir / "figures" / "pc1_pc2_clusters.png"
        figure_path.parent.mkdir()
        figure_path.write_bytes(b"png")
    else:
        figure_path = None
    return ArtifactIndex(
        attempt=attempt,
        manifest={},
        output_dirs={"selected_alignment_dir": aligned_dir, "selected_pca_dir": pca_dir},
        batch_summary=empty,
        run_summary=empty,
        weld_summary=empty,
        alignment_summary=empty,
        pca_input_manifest=empty,
        pca_scores=pd.DataFrame({"sample_tag": ["T049_L"], "PC01": [1.25], "PC02": [-0.5]}),
        pca_morphology_dir=morphology_dir,
        pca_morphology_summary=(
            pd.DataFrame([{"status": "PASS", "selected_cluster_count": 2}])
            if with_morphology else empty
        ),
        pc_extreme_shapes=(
            pd.DataFrame([{
                "component": "PC01", "direction": "plus", "status": "available",
                "relative_ply_path": "pc_modes/PC01_plus_2sd.ply",
            }]) if with_morphology else empty
        ),
        observed_pc_extremes=(
            pd.DataFrame([{
                "component": "PC01", "direction": "plus", "sample_tag": "T049_L",
                "score": 1.25, "cluster_id": "Cluster 01", "status": "available",
            }]) if with_morphology else empty
        ),
        multivariate_extremes=(
            pd.DataFrame([{
                "sample_tag": "T049_L", "distance_rank": 1, "distance_to_center": 2.1,
                "is_extreme_candidate": True, "cluster_id": "Cluster 01",
            }]) if with_morphology else empty
        ),
        cluster_k_selection=(
            pd.DataFrame([{"cluster_count": 2, "silhouette_score": 0.81, "selected": True}])
            if with_morphology else empty
        ),
        cluster_assignments=(
            pd.DataFrame([{"sample_tag": "T049_L", "PC01": 1.25, "PC02": -0.5, "cluster_id": "Cluster 01"}])
            if with_morphology else empty
        ),
        cluster_summary=(
            pd.DataFrame([{"cluster_id": "Cluster 01", "sample_count": 1}])
            if with_morphology else empty
        ),
        pc1_pc2_clusters_figure=figure_path,
        pc_variance_scree_figure=None,
        evidence=(),
    )


def test_page_displays_cluster_and_extreme_tables_for_new_run(qtbot, tmp_path: Path):
    from desktop_app.ui.pca_morphology_page import PcaMorphologyPage

    viewer = FakeViewer()
    page = PcaMorphologyPage(viewer=viewer)
    qtbot.addWidget(page)

    page.set_attempt(_index(tmp_path, with_morphology=True))

    assert page.status_label.text() == "PCA 形态分析已生成"
    assert page.cluster_table.item(0, 0).text() == "Cluster 01"
    assert page.observed_extremes_table.item(0, 2).text() == "T049_L"
    assert page.model_selector.isEnabled()


def test_page_loads_theory_and_real_subject_meshes_from_trusted_directories(qtbot, tmp_path: Path):
    from desktop_app.ui.pca_morphology_page import PcaMorphologyPage

    viewer = FakeViewer()
    page = PcaMorphologyPage(viewer=viewer)
    qtbot.addWidget(page)
    index = _index(tmp_path, with_morphology=True)
    page.set_attempt(index)

    page.model_selector.setCurrentText("理论形态｜PC01 +2SD")
    assert viewer.loaded[-1] == (
        LayerName.PCA_MORPHOLOGY,
        ArtifactRef("理论形态｜PC01 +2SD", index.output_dirs["selected_pca_dir"] / "pc_modes" / "PC01_plus_2sd.ply"),
    )
    page.model_selector.setCurrentText("真实被试｜PC01+｜T049_L")
    assert viewer.loaded[-1] == (
        LayerName.PCA_MORPHOLOGY,
        ArtifactRef("真实被试｜PC01+｜T049_L", index.output_dirs["selected_alignment_dir"] / "T049_L_aligned_whole_ear.ply"),
    )


def test_page_explains_when_an_old_run_has_no_morphology_artifacts(qtbot, tmp_path: Path):
    from desktop_app.ui.pca_morphology_page import PcaMorphologyPage

    page = PcaMorphologyPage(viewer=FakeViewer())
    qtbot.addWidget(page)

    page.set_attempt(_index(tmp_path, with_morphology=False))

    assert "未生成" in page.status_label.text()
    assert not page.model_selector.isEnabled()
