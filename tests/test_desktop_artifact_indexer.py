import json
from pathlib import Path

import pytest

from desktop_app.artifact_indexer import ArtifactIndexer, ArtifactIntegrityError
from desktop_app.models import AttemptRecord


def completed_attempt(tmp_path: Path) -> AttemptRecord:
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
    return attempt


def test_index_rejects_manifest_that_claims_path_outside_artifacts(tmp_path: Path):
    attempt = completed_attempt(tmp_path)
    (attempt.artifacts_dir / "manifest.json").write_text(
        json.dumps(
            {
                "status": "COMPLETED",
                "output_scope": "isolated",
                "outputs": {"weld_dir": "../outside"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactIntegrityError):
        ArtifactIndexer().index(attempt)


def test_index_loads_declared_batch_evidence_only(tmp_path: Path):
    attempt = completed_attempt(tmp_path)
    (attempt.artifacts_dir / "pipeline_batch_summary.csv").write_text(
        "sample_tag,discovery,salvage,weld,alignment,pca_included,reason\n"
        "T049_L,READY,PASS,FAIL,SKIPPED,SKIPPED,weld_not_pca_ready\n",
        encoding="utf-8",
    )
    outside = attempt.root / "outside.csv"
    outside.write_text("not,evidence\n", encoding="utf-8")

    index = ArtifactIndexer().index(attempt)

    assert index.batch_summary.loc[0, "sample_tag"] == "T049_L"
    assert index.output_dirs["weld_dir"] == attempt.artifacts_dir / "whole_ear_r24" / "weld_repaired"
    assert all(ref.path != outside for ref in index.evidence)
