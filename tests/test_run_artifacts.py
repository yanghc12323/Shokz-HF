from pathlib import Path

import pytest


def test_prepare_empty_output_root_creates_missing_directory(tmp_path: Path):
    from ear_param.run_artifacts import RESERVATION_MARKER, prepare_empty_output_root

    root = tmp_path / "new_run"
    assert prepare_empty_output_root(root) == root
    assert root.is_dir()
    assert (root / RESERVATION_MARKER).is_file()


def test_prepare_empty_output_root_accepts_existing_empty_directory(tmp_path: Path):
    from ear_param.run_artifacts import RESERVATION_MARKER, prepare_empty_output_root

    root = tmp_path / "empty_run"
    root.mkdir()
    assert prepare_empty_output_root(root) == root
    assert (root / RESERVATION_MARKER).is_file()


def test_prepare_empty_output_root_rejects_second_claim(tmp_path: Path):
    from ear_param.run_artifacts import prepare_empty_output_root

    root = tmp_path / "claimed_run"
    prepare_empty_output_root(root)

    with pytest.raises(FileExistsError, match="output root is not empty"):
        prepare_empty_output_root(root)


def test_prepare_empty_output_root_rejects_non_empty_directory(tmp_path: Path):
    from ear_param.run_artifacts import prepare_empty_output_root

    root = tmp_path / "existing_run"
    root.mkdir()
    (root / "old_result.csv").write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(FileExistsError, match="output root is not empty"):
        prepare_empty_output_root(root)


def test_pipeline_output_layout_maps_every_stage_under_one_root(tmp_path: Path):
    from ear_param.run_artifacts import PipelineOutputLayout

    root = tmp_path / "run_001"
    layout = PipelineOutputLayout.from_output_root(root)

    assert layout.output_root == root
    assert layout.canonical_dir == root / "canonical_inputs_r24"
    assert layout.raw_dir == root / "parameterized_points_r24" / "raw"
    assert layout.repaired_dir == root / "parameterized_points_r24" / "repaired"
    assert layout.salvaged_dir == root / "parameterized_points_r24" / "salvaged"
    assert layout.raw_mesh_dir == root / "remesh_r24" / "raw"
    assert layout.repaired_mesh_dir == root / "remesh_r24" / "repaired"
    assert layout.salvaged_mesh_dir == root / "remesh_r24" / "salvaged"
    assert layout.qc_dir == root / "remesh_qc_r24"
    assert layout.weld_dir == root / "whole_ear_r24" / "weld_repaired"
    assert layout.aligned_dir == root / "whole_ear_r24" / "aligned_gpa"
    assert layout.pca_dir == root / "pca_gpa_r24"
    assert layout.reference_aligned_dir == root / "whole_ear_r24" / "aligned_reference_MQ_S068L"
    assert layout.reference_pca_dir == root / "pca_reference_MQ_S068L_r24"

    config_paths = layout.pipeline_config_kwargs()
    assert set(config_paths) == {
        "canonical_dir", "raw_dir", "repaired_dir", "salvaged_dir",
        "raw_mesh_dir", "repaired_mesh_dir", "salvaged_mesh_dir",
        "qc_dir", "weld_dir", "aligned_dir", "pca_dir",
        "reference_aligned_dir", "reference_pca_dir",
    }
    assert all(root in path.parents for path in config_paths.values())


def test_pipeline_output_layout_uses_selected_reference_sample(tmp_path: Path):
    from ear_param.run_artifacts import PipelineOutputLayout

    root = tmp_path / "run_002"
    layout = PipelineOutputLayout.from_output_root(root, reference_sample="T123_R")

    assert layout.reference_aligned_dir == root / "whole_ear_r24" / "aligned_reference_T123_R"
    assert layout.reference_pca_dir == root / "pca_reference_T123_R_r24"


@pytest.mark.parametrize("reference_sample", ("../escape", "T123/R", "T123 R", ""))
def test_pipeline_output_layout_rejects_unsafe_reference_token(
    tmp_path: Path,
    reference_sample: str,
):
    from ear_param.run_artifacts import PipelineOutputLayout

    with pytest.raises(ValueError, match="reference sample"):
        PipelineOutputLayout.from_output_root(
            tmp_path / "run_003",
            reference_sample=reference_sample,
        )
