import json
from pathlib import Path
from types import SimpleNamespace

from desktop_app.artifact_indexer import ArtifactIndexer
from desktop_app.models import AttemptRecord
import desktop_app.ui.result_workbench as result_workbench_module
from desktop_app.ui.result_workbench import ResultWorkbench


def artifact_index(tmp_path: Path):
    attempt = AttemptRecord.create(tmp_path / "project", "run-001", "attempt-001")
    attempt.artifacts_dir.mkdir(parents=True)
    (attempt.artifacts_dir / "manifest.json").write_text(
        json.dumps(
            {
                "status": "COMPLETED",
                "output_scope": "isolated",
                "parameters": {"alignment_mode": "gpa"},
                "result": {
                    "pca_status": "PASS",
                    "pca_included_count": 1,
                    "pca_result": {
                        "retained_component_count": 2,
                        "retained_cumulative_explained_variance_ratio": 0.83,
                    },
                },
                "outputs": {
                    "weld_dir": "whole_ear_r24/weld_repaired",
                    "pca_dir": "pca_gpa_r24",
                },
            }
        ),
        encoding="utf-8",
    )
    (attempt.artifacts_dir / "pipeline_batch_summary.csv").write_text(
        "sample_tag,discovery,remesh,salvage,weld,alignment,pca_included,reason\n"
        "T049_L,READY,PASS,PASS,PASS,PASS,YES,\n",
        encoding="utf-8",
    )
    pca_dir = attempt.artifacts_dir / "pca_gpa_r24"
    pca_dir.mkdir()
    (pca_dir / "scores.csv").write_text(
        "sample_tag,PC01,PC02\nT049_L,1.25,-0.50\n", encoding="utf-8"
    )
    return ArtifactIndexer().index(attempt)


def test_unavailable_layer_is_disabled_with_reason(qtbot, tmp_path: Path):
    workbench = ResultWorkbench()
    qtbot.addWidget(workbench)

    workbench.set_attempt(artifact_index(tmp_path))

    assert not workbench.layer_button("平均耳").isEnabled()
    assert "PCA" in workbench.layer_button("平均耳").toolTip()


def test_select_sample_shows_gate_reason(qtbot, tmp_path: Path):
    workbench = ResultWorkbench()
    qtbot.addWidget(workbench)
    workbench.set_attempt(artifact_index(tmp_path))

    detail = workbench.select_sample("T049_L")

    assert detail.sample_tag == "T049_L"
    assert "PCA" in workbench.status_label.text()


def test_result_workbench_displays_primary_pca_summary(qtbot, tmp_path: Path):
    workbench = ResultWorkbench()
    qtbot.addWidget(workbench)

    workbench.set_attempt(artifact_index(tmp_path))

    assert "GPA" in workbench.pca_summary_label.text()
    assert "PASS" in workbench.pca_summary_label.text()
    assert "2" in workbench.pca_summary_label.text()
    assert workbench.result_title_label.text() == "结果复核"
    assert workbench.pca_title_label.text() == "PCA 结果"
    assert workbench.pca_summary_table.item(0, 0).text() == "配准方式"
    assert workbench.pca_scores_table.item(0, 0).text() == "T049_L"
    assert workbench.pca_scores_table.item(0, 1).text() == "1.25"


def test_result_workbench_places_scores_above_viewer_outside_left_sidebar(qtbot):
    workbench = ResultWorkbench()
    qtbot.addWidget(workbench)

    assert workbench.review_splitter.orientation().name == "Vertical"
    assert workbench.pca_scores_panel.objectName() == "pcaScoresPanel"
    assert workbench.pca_scores_table.parentWidget() is workbench.pca_scores_panel
    assert workbench.viewer_panel.objectName() == "viewerPanel"
    assert workbench.viewer.parentWidget() is workbench.viewer_panel
    assert workbench.pca_scores_table not in workbench.result_sidebar.findChildren(type(workbench.pca_scores_table))


def test_result_workbench_places_pca_morphology_in_a_separate_tab(qtbot):
    workbench = ResultWorkbench()
    qtbot.addWidget(workbench)

    assert workbench.result_tabs.count() == 2
    assert workbench.result_tabs.tabText(0) == "结果复核"
    assert workbench.result_tabs.tabText(1) == "PCA 形态分析"
    assert workbench.result_tabs.widget(1) is workbench.pca_morphology_page


def test_result_workbench_opens_current_attempt_output_folder(qtbot, tmp_path: Path, monkeypatch):
    workbench = ResultWorkbench()
    qtbot.addWidget(workbench)
    index = artifact_index(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(
        result_workbench_module,
        "QDesktopServices",
        SimpleNamespace(openUrl=lambda url: opened.append(url.toLocalFile()) or True),
    )

    workbench.set_attempt(index)
    workbench.open_output_folder_button.click()

    assert workbench.open_output_folder_button.isEnabled()
    assert opened == [index.attempt.artifacts_dir.as_posix()]
