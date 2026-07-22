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
    (attempt.artifacts_dir / "pipeline_timing_summary.csv").write_text(
        "stage,sample_tag,elapsed_seconds,status\nREMESH,T049_L,1.25,PASS\n",
        encoding="utf-8",
    )
    outside = attempt.root / "outside.csv"
    outside.write_text("not,evidence\n", encoding="utf-8")

    index = ArtifactIndexer().index(attempt)

    assert index.batch_summary.loc[0, "sample_tag"] == "T049_L"
    assert index.output_dirs["weld_dir"] == attempt.artifacts_dir / "whole_ear_r24" / "weld_repaired"
    assert any(ref.path.name == "pipeline_timing_summary.csv" for ref in index.evidence)
    assert all(ref.path != outside for ref in index.evidence)


def test_index_uses_fixed_reference_pca_artifacts_when_that_mode_was_selected(tmp_path: Path):
    attempt = completed_attempt(tmp_path)
    (attempt.artifacts_dir / "manifest.json").write_text(
        json.dumps(
            {
                "status": "COMPLETED",
                "output_scope": "isolated",
                "parameters": {"alignment_mode": "fixed-reference"},
                "outputs": {
                    "aligned_dir": "whole_ear_r24/aligned_gpa",
                    "pca_dir": "pca_gpa_r24",
                    "reference_aligned_dir": "whole_ear_r24/aligned_reference_T001_L",
                    "reference_pca_dir": "pca_reference_T001_L_r24",
                },
            }
        ),
        encoding="utf-8",
    )
    pca_dir = attempt.artifacts_dir / "pca_reference_T001_L_r24"
    pca_dir.mkdir()
    (pca_dir / "pca_input_manifest.csv").write_text(
        "sample_tag,included\nT001_L,True\n", encoding="utf-8"
    )

    index = ArtifactIndexer().index(attempt)

    assert index.pca_input_manifest.loc[0, "sample_tag"] == "T001_L"
    assert index.output_dirs["selected_pca_dir"] == pca_dir
