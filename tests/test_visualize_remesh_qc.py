from scripts.visualize_remesh_qc import figure_layers_for_mode


def test_figure_layers_for_mode_only_renders_repaired_failures_when_requested():
    assert figure_layers_for_mode("all", "PASS") == {"raw", "repaired", "salvaged"}
    assert figure_layers_for_mode("repaired-fail", "FAIL") == {"repaired"}
    assert figure_layers_for_mode("repaired-fail", "PASS") == set()
    assert figure_layers_for_mode("none", "FAIL") == set()


def test_qc_summary_root_defaults_to_out_dir_and_can_be_isolated(tmp_path):
    from scripts.visualize_remesh_qc import summary_output_root

    out_dir = tmp_path / "qc"
    isolated = tmp_path / "qc" / "_sample_summaries" / "T001_L"

    assert summary_output_root(out_dir, None) == out_dir
    assert summary_output_root(out_dir, isolated) == isolated


def test_qc_sample_identity_supports_mq_model_name():
    from scripts.visualize_remesh_qc import _split_sample_tag

    assert _split_sample_tag("MQ_S001L") == ("MQ_S001", "L")
