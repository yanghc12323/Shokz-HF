import json
from pathlib import Path

from desktop_app.artifact_indexer import ArtifactIndexer
from desktop_app.models import AttemptRecord
from desktop_app.result_service import ResultService


def completed_index(tmp_path: Path):
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
        "T049_L,READY,PASS,PASS,FAIL,SKIPPED,SKIPPED,weld_not_pca_ready\n",
        encoding="utf-8",
    )
    return ArtifactIndexer().index(attempt)


def test_weld_failure_explains_pca_interception(tmp_path: Path):
    detail = ResultService().sample_details(completed_index(tmp_path), "T049_L")

    assert detail.pca_status == "拦截"
    assert "Weld" in detail.reason_zh
    assert detail.weld_status == "FAIL"


def test_unknown_machine_reason_is_retained_for_audit(tmp_path: Path):
    index = completed_index(tmp_path)
    index.batch_summary.loc[0, "reason"] = "custom_gate:threshold=9"

    detail = ResultService().sample_details(index, "T049_L")

    assert "custom_gate:threshold=9" in detail.reason_zh
