import json
from pathlib import Path

from desktop_app.artifact_indexer import ArtifactIndexer
from desktop_app.models import AttemptRecord
from desktop_app.ui.result_workbench import ResultWorkbench


def artifact_index(tmp_path: Path):
    attempt = AttemptRecord.create(tmp_path / "project", "run-001", "attempt-001")
    attempt.artifacts_dir.mkdir(parents=True)
    (attempt.artifacts_dir / "manifest.json").write_text(
        json.dumps(
            {
                "status": "COMPLETED",
                "output_scope": "isolated",
                "outputs": {"weld_dir": "whole_ear_r24/weld_repaired"},
            }
        ),
        encoding="utf-8",
    )
    (attempt.artifacts_dir / "pipeline_batch_summary.csv").write_text(
        "sample_tag,discovery,remesh,salvage,weld,alignment,pca_included,reason\n"
        "T049_L,READY,PASS,PASS,PASS,PASS,YES,\n",
        encoding="utf-8",
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
