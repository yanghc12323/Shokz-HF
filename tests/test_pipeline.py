"""Tests for the formal end-to-end batch pipeline."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from threading import Event, Lock
import time
from types import SimpleNamespace

import pandas as pd
import pytest
import trimesh


def test_remesh_backend_summary_aggregates_gpu_timing(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, _summarize_remesh_backends

    salvaged_dir = tmp_path / "salvaged"
    salvaged_dir.mkdir()
    for sample_tag, region_count, h2d, solve in (
        ("MQ_S001L", 52, 0.25, 0.75),
        ("MQ_S001R", 52, 0.50, 1.25),
    ):
        (salvaged_dir / f"{sample_tag}_remesh_backend.json").write_text(
            json.dumps(
                {
                    "requested": "auto",
                    "effective": "cuda",
                    "fallback_reason": "",
                    "gpu_peak_bytes": 1024,
                    "gpu_timing": {
                        "region_count": region_count,
                        "lock_wait_seconds": 0.1,
                        "host_to_device_seconds": h2d,
                        "harmonic_solve_seconds": solve,
                        "uv_lookup_seconds": 2.0,
                        "map_to_3d_seconds": 0.5,
                        "device_to_host_seconds": 0.25,
                        "region_wall_seconds": 4.0,
                    },
                }
            ),
            encoding="utf-8",
        )

    summary = _summarize_remesh_backends(
        PipelineConfig(mesh_dir=tmp_path / "mesh", landmarks_dir=tmp_path / "landmarks", salvaged_dir=salvaged_dir)
    )

    assert summary["gpu_timing"] == {
        "region_count": 104,
        "lock_wait_seconds": 0.2,
        "host_to_device_seconds": 0.75,
        "harmonic_solve_seconds": 2.0,
        "uv_lookup_seconds": 4.0,
        "map_to_3d_seconds": 1.0,
        "device_to_host_seconds": 0.5,
        "region_wall_seconds": 8.0,
    }


def test_full_pipeline_output_root_scopes_every_stage(tmp_path: Path):
    from scripts.run_full_pipeline import build_parser, build_pipeline_config

    root = tmp_path / "scoped_run"
    args = build_parser().parse_args([
        "--mesh_dir", str(tmp_path / "clean_mesh"),
        "--landmarks_dir", str(tmp_path / "landmarks"),
        "--output-root", str(root),
        "--reference-sample", "T076_L",
    ])

    config, run_dir, layout = build_pipeline_config(args)

    assert layout is not None
    assert run_dir == root
    assert config.raw_dir == root / "parameterized_points_r24" / "raw"
    assert config.raw_mesh_dir == root / "remesh_r24" / "raw"
    assert config.weld_dir == root / "whole_ear_r24" / "weld_repaired"
    assert config.reference_pca_dir == root / "pca_reference_T076_L_r24"


def test_full_pipeline_output_root_rejects_distinct_run_dir(tmp_path: Path):
    from scripts.run_full_pipeline import build_parser, build_pipeline_config

    args = build_parser().parse_args([
        "--output-root", str(tmp_path / "scoped_run"),
        "--run_dir", str(tmp_path / "summary_elsewhere"),
    ])

    with pytest.raises(ValueError, match="--run_dir must resolve to --output-root"):
        build_pipeline_config(args)


def test_full_pipeline_output_root_accepts_same_resolved_run_dir(tmp_path: Path):
    from scripts.run_full_pipeline import build_parser, build_pipeline_config

    root = tmp_path / "scoped_run"
    equivalent = root.parent / "other" / ".." / root.name
    args = build_parser().parse_args([
        "--output-root", str(root),
        "--run_dir", str(equivalent),
    ])

    _, run_dir, _ = build_pipeline_config(args)

    assert run_dir == root


def test_full_pipeline_without_output_root_keeps_legacy_stage_paths(tmp_path: Path):
    from scripts.run_full_pipeline import build_parser, build_pipeline_config

    args = build_parser().parse_args([
        "--mesh_dir", str(tmp_path / "clean_mesh"),
        "--landmarks_dir", str(tmp_path / "landmarks"),
        "--run_dir", str(tmp_path / "summary_only"),
    ])

    config, run_dir, layout = build_pipeline_config(args)

    assert layout is None
    assert run_dir == tmp_path / "summary_only"
    assert config.raw_dir == Path("output/parameterized_points_r24/raw")
    assert config.weld_dir == Path("output/whole_ear_r24/weld_repaired")


def test_full_pipeline_only_prepares_an_explicit_output_root(
    tmp_path: Path,
    monkeypatch,
):
    import scripts.run_full_pipeline as full_pipeline

    prepared_roots: list[Path] = []
    configs = []
    written_run_dirs: list[Path] = []
    result = SimpleNamespace(
        records=pd.DataFrame({"weld": ["PASS"]}),
        pca_status="SKIPPED",
        pca_result={},
        reference_pca_status="SKIPPED",
        reference_pca_result={},
        stage_timings=[],
    )

    monkeypatch.setattr(
        full_pipeline,
        "prepare_empty_output_root",
        lambda root: prepared_roots.append(root),
    )
    monkeypatch.setattr(full_pipeline, "build_subprocess_stages", lambda config: object())
    monkeypatch.setattr(
        full_pipeline,
        "run_pipeline",
        lambda config, stage_functions: configs.append(config) or result,
    )
    monkeypatch.setattr(
        full_pipeline,
        "write_pipeline_outputs",
        lambda result, run_dir: written_run_dirs.append(run_dir),
    )

    summary_only = tmp_path / "summary_only"
    monkeypatch.setattr(sys, "argv", ["run_full_pipeline.py", "--run_dir", str(summary_only)])
    full_pipeline.main()

    root = tmp_path / "scoped_run"
    monkeypatch.setattr(sys, "argv", ["run_full_pipeline.py", "--output-root", str(root)])
    full_pipeline.main()

    assert prepared_roots == [root]
    assert configs[0].raw_dir == Path("output/parameterized_points_r24/raw")
    assert configs[1].raw_dir == root / "parameterized_points_r24" / "raw"
    assert written_run_dirs == [summary_only, root]


def test_full_pipeline_execute_finalizes_manifest_on_error(tmp_path: Path, monkeypatch):
    import scripts.run_full_pipeline as cli

    root = tmp_path / "failed_run"
    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    args = cli.build_parser().parse_args([
        "--mesh_dir", str(mesh_dir),
        "--landmarks_dir", str(landmarks_dir),
        "--output-root", str(root),
    ])
    monkeypatch.setattr(cli, "build_subprocess_stages", lambda config: object())
    monkeypatch.setattr(
        cli,
        "run_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        cli.execute(args)

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "ERROR"
    assert "boom" in manifest["error"]


def test_full_pipeline_execute_marks_manifest_cancelled(tmp_path: Path, monkeypatch):
    import scripts.run_full_pipeline as cli
    from ear_param.run_control import RunCancelled

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    config_dir = tmp_path / "config"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    config_dir.mkdir()
    regions = config_dir / "region_table.csv"
    regions.write_text(
        "region_id,lm_a,lm_b,lm_c,resolution\nT001,L1,L2,L3,24\n",
        encoding="utf-8",
    )
    root = tmp_path / "cancelled_run"
    args = cli.build_parser().parse_args([
        "--mesh_dir", str(mesh_dir),
        "--landmarks_dir", str(landmarks_dir),
        "--regions", str(regions),
        "--output-root", str(root),
    ])
    monkeypatch.setattr(cli, "build_subprocess_stages", lambda config: object())
    monkeypatch.setattr(
        cli,
        "run_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(RunCancelled("cancelled")),
    )

    assert cli.execute(args) is None

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "CANCELLED"
    assert manifest["error"] == "cancelled"


def test_full_pipeline_execute_finalizes_completed_manifest_and_prints_summary(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    import scripts.run_full_pipeline as cli

    root = tmp_path / "completed_run"
    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    args = cli.build_parser().parse_args([
        "--mesh_dir", str(mesh_dir),
        "--landmarks_dir", str(landmarks_dir),
        "--output-root", str(root),
    ])
    result = cli.PipelineResult(
        records=pd.DataFrame({
            "discovery": ["READY"],
            "salvage": ["PASS"],
            "weld": ["PASS"],
            "alignment": ["PASS"],
            "pca_included": ["YES"],
            "reference_alignment": ["SKIPPED"],
            "reference_pca_included": ["NO"],
        }),
        pca_status="PASS",
        pca_result={"retained_component_count": 1},
    )
    written_run_dirs: list[Path] = []
    monkeypatch.setattr(cli, "build_subprocess_stages", lambda config: object())
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: result)
    monkeypatch.setattr(
        cli,
        "write_pipeline_outputs",
        lambda result, run_dir: written_run_dirs.append(run_dir),
    )

    assert cli.execute(args) is result

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "COMPLETED"
    assert manifest["result"]["sample_count"] == 1
    assert written_run_dirs == [root]
    captured = capsys.readouterr().out
    assert "[Pipeline] Final summary:" in captured
    assert "[Pipeline] PCA status: PASS" in captured
    assert f"[Pipeline] Run artifacts: {root}" in captured


def test_discover_samples_records_ready_and_missing_pairs(tmp_path: Path):
    from ear_param.pipeline import discover_samples

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    (mesh_dir / "T001_L.ply").write_text("mesh placeholder")
    (mesh_dir / "T002_L.ply").write_text("mesh placeholder")
    (landmarks_dir / "T001_L_landmarks.csv").write_text("landmark_id,x,y,z\n")
    (landmarks_dir / "T003_L_landmarks.csv").write_text("landmark_id,x,y,z\n")

    discovered = discover_samples(mesh_dir, landmarks_dir).set_index("sample_tag")

    assert discovered.loc["T001_L", "discovery"] == "READY"
    assert discovered.loc["T002_L", "discovery"] == "MISSING_LANDMARKS"
    assert discovered.loc["T003_L", "discovery"] == "MISSING_MESH"
    assert discovered.loc["T002_L", "reason"] == "missing_landmarks"
    assert discovered.loc["T003_L", "reason"] == "missing_mesh"


def test_discover_samples_pairs_mq_mesh_with_t_landmarks(tmp_path: Path):
    from ear_param.pipeline import discover_samples

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    (mesh_dir / "MQ_S001L.ply").write_text("mesh placeholder")
    (landmarks_dir / "T001_L_landmarks.csv").write_text("landmark_id,x,y,z\n")

    discovered = discover_samples(mesh_dir, landmarks_dir)

    assert discovered.to_dict("records") == [
        {"sample_tag": "MQ_S001L", "discovery": "READY", "reason": ""}
    ]


def test_discover_samples_keeps_unrecognized_mesh_for_validation(tmp_path: Path):
    from ear_param.pipeline import discover_samples

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    (mesh_dir / "unrecognized.ply").write_text("mesh placeholder")

    discovered = discover_samples(mesh_dir, landmarks_dir)

    assert discovered.to_dict("records") == [{
        "sample_tag": "unrecognized",
        "discovery": "MISSING_LANDMARKS",
        "reason": "missing_landmarks",
    }]


def test_pipeline_uses_t_landmark_path_for_mq_canonicalization(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    mesh_path = mesh_dir / "MQ_S001L.ply"
    trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]], process=False,
    ).export(mesh_path)
    pd.DataFrame({"landmark_id": ["L7"], "x": [0.0], "y": [0.0], "z": [0.0]}).to_csv(
        landmarks_dir / "T001_L_landmarks.csv", index=False
    )
    canonical_dir = tmp_path / "canonical"
    called: list[str] = []
    stages = StageFunctions(
        remesh_sample=lambda tag: called.append(tag) or {"remesh": "PASS", "salvage": "PASS"},
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": ["PASS"], "pca_ready": [True]}),
        alignment_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": ["PASS"]}),
        pca_batch=lambda: {"status": "PASS", "included_tags": ["MQ_S001L"]},
    )

    run_pipeline(
        PipelineConfig(
            mesh_dir=mesh_dir,
            landmarks_dir=landmarks_dir,
            canonical_dir=canonical_dir,
            disable_side_normalization=False,
        ),
        stage_functions=stages,
    )

    assert called == ["MQ_S001L"]
    assert (canonical_dir / "MQ_S001L_landmarks.csv").is_file()


def test_pipeline_continues_after_one_sample_remesh_error(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    for sample_tag in ("T001_L", "T002_L"):
        (mesh_dir / f"{sample_tag}.ply").write_text("mesh placeholder")
        (landmarks_dir / f"{sample_tag}_landmarks.csv").write_text("landmark_id,x,y,z\n")

    processed: list[str] = []

    def remesh_sample(sample_tag: str) -> dict[str, str]:
        processed.append(sample_tag)
        if sample_tag == "T001_L":
            raise RuntimeError("bad landmarks")
        return {"remesh": "PASS", "salvage": "PASS"}

    def remesh_qc(sample_tag: str) -> str:
        return "PASS"

    stages = StageFunctions(
        remesh_sample=remesh_sample,
        remesh_qc=remesh_qc,
        weld_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status", "pca_ready"]),
        alignment_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status"]),
        pca_batch=lambda: {"status": "PASS", "included_tags": []},
    )
    result = run_pipeline(
        PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir),
        stage_functions=stages,
    )

    records = result.records.set_index("sample_tag")
    assert processed == ["T001_L", "T002_L"]
    assert records.loc["T001_L", "remesh"] == "ERROR"
    assert records.loc["T001_L", "salvage"] == "SKIPPED"
    assert records.loc["T002_L", "remesh"] == "PASS"
    assert records.loc["T002_L", "remesh_qc"] == "PASS"


def test_pipeline_emits_machine_readable_sample_and_stage_events(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    (mesh_dir / "T076_L.ply").write_text("mesh placeholder")
    (landmarks_dir / "T076_L_landmarks.csv").write_text("landmark_id,x,y,z\n")
    events: list[tuple[str, dict[str, object]]] = []
    stages = StageFunctions(
        remesh_sample=lambda tag: {"remesh": "PASS", "salvage": "PASS"},
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame({
            "sample_tag": tags, "status": ["PASS"], "pca_ready": [True],
        }),
        alignment_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": ["PASS"]}),
        pca_batch=lambda: {"status": "PASS", "included_tags": ["T076_L"]},
    )

    result = run_pipeline(
        PipelineConfig(
            mesh_dir=mesh_dir,
            landmarks_dir=landmarks_dir,
            event_reporter=lambda event, fields: events.append((event, fields)),
        ),
        stage_functions=stages,
    )

    assert result.records.loc[0, "salvage"] == "PASS"
    assert ("sample_started", {"sample_tag": "T076_L", "stage": "REMESH"}) in events
    assert any(
        event == "sample_finished"
        and fields["sample_tag"] == "T076_L"
        and fields["stage"] == "REMESH"
        and fields["status"] == "PASS"
        for event, fields in events
    )
    assert ("stage_started", {"stage": "WELD", "sample_count": 1}) in events
    assert any(
        event == "stage_finished" and fields["stage"] == "WELD" and fields["status"] == "PASS"
        for event, fields in events
    )


def test_pipeline_config_defaults_to_three_percent_degenerate_salvage_ratio(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig

    config = PipelineConfig(
        mesh_dir=tmp_path / "clean_mesh",
        landmarks_dir=tmp_path / "landmarks",
    )

    assert config.max_salvage_degenerate_ratio == 0.03


def test_pipeline_config_defaults_match_child_salvage_and_pca_defaults(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig
    from scripts.run_full_pipeline import build_parser, build_pipeline_config

    config = PipelineConfig(
        mesh_dir=tmp_path / "clean_mesh",
        landmarks_dir=tmp_path / "landmarks",
    )
    args = build_parser().parse_args([])
    cli_config, _, _ = build_pipeline_config(args)

    assert config.max_salvage_unmapped_ratio == 0.45
    assert config.max_salvage_degenerate_ratio == 0.03
    assert config.weld_warning_mm == 0.5
    assert config.weld_fail_mm == 1.5
    assert config.pca_variance_threshold == 0.75
    assert cli_config.max_salvage_unmapped_ratio == 0.45
    assert cli_config.max_salvage_degenerate_ratio == 0.03
    assert cli_config.weld_warning_mm == 0.5
    assert cli_config.weld_fail_mm == 1.5
    assert cli_config.pca_variance_threshold == 0.75
    assert cli_config.parallel_workers == 1


def test_pipeline_resolves_automatic_workers_to_a_bounded_count(monkeypatch):
    import ear_param.pipeline as pipeline

    monkeypatch.setattr(pipeline.os, "cpu_count", lambda: 12)

    assert pipeline._effective_parallel_workers(0) == 4
    assert pipeline._effective_parallel_workers(2) == 2


def test_pipeline_config_appends_new_fields_after_legacy_field_order():
    from dataclasses import fields

    from ear_param.pipeline import PipelineConfig

    legacy_field_names = (
        "mesh_dir", "landmarks_dir", "regions", "raw_dir", "repaired_dir",
        "salvaged_dir", "raw_mesh_dir", "repaired_mesh_dir", "salvaged_mesh_dir",
        "qc_dir", "weld_dir", "aligned_dir", "pca_dir", "reference_aligned_dir",
        "reference_pca_dir", "canonical_dir", "canonical_side", "mirror_axis",
        "disable_side_normalization", "max_salvage_degenerate_ratio", "sample_tags",
        "skip_remesh_qc", "skip_pca", "reference_sample", "reporter",
    )

    assert tuple(field.name for field in fields(PipelineConfig)) == (
        *legacy_field_names,
        "max_salvage_unmapped_ratio",
        "pca_variance_threshold",
            "event_reporter",
            "checkpoint",
            "event_log",
            "qc_figure_mode",
            "alignment_mode",
                "parallel_workers",
                "weld_warning_mm",
                "weld_fail_mm",
                "remesh_backend",
            )


def test_pipeline_config_preserves_legacy_positional_constructor_mapping():
    from ear_param.pipeline import PipelineConfig

    reporter = lambda message: None
    legacy_values = (
        Path("mesh"), Path("landmarks"), Path("regions"), Path("raw"),
        Path("repaired"), Path("salvaged"), Path("raw_mesh"),
        Path("repaired_mesh"), Path("salvaged_mesh"), Path("qc"), Path("weld"),
        Path("aligned"), Path("pca"), Path("reference_aligned"),
        Path("reference_pca"), Path("canonical"), "L", "z", False, 0.012,
        ("T001_L",), True, True, "T001_L", reporter,
    )
    legacy_field_names = (
        "mesh_dir", "landmarks_dir", "regions", "raw_dir", "repaired_dir",
        "salvaged_dir", "raw_mesh_dir", "repaired_mesh_dir", "salvaged_mesh_dir",
        "qc_dir", "weld_dir", "aligned_dir", "pca_dir", "reference_aligned_dir",
        "reference_pca_dir", "canonical_dir", "canonical_side", "mirror_axis",
        "disable_side_normalization", "max_salvage_degenerate_ratio", "sample_tags",
        "skip_remesh_qc", "skip_pca", "reference_sample", "reporter",
    )

    config = PipelineConfig(*legacy_values)

    for field_name, expected in zip(legacy_field_names, legacy_values, strict=True):
        assert getattr(config, field_name) == expected
    assert config.max_salvage_unmapped_ratio == 0.45
    assert config.pca_variance_threshold == 0.75


def test_full_pipeline_cli_applies_salvage_and_pca_thresholds(tmp_path: Path):
    from scripts.run_full_pipeline import build_parser, build_pipeline_config

    args = build_parser().parse_args([
        "--max-salvage-unmapped-ratio", "0.28",
        "--pca-variance-threshold", "0.82",
    ])

    config, _, _ = build_pipeline_config(args)

    assert config.max_salvage_unmapped_ratio == 0.28
    assert config.pca_variance_threshold == 0.82


def test_full_pipeline_cli_writes_jsonl_events_when_requested(tmp_path: Path):
    from scripts.run_full_pipeline import build_parser, build_pipeline_config

    event_path = tmp_path / "events.jsonl"
    args = build_parser().parse_args(["--event-log", str(event_path)])

    config, _, _ = build_pipeline_config(args)

    assert config.event_reporter is not None
    config.event_reporter("stage_started", {"stage": "REMESH"})
    payload = json.loads(event_path.read_text(encoding="utf-8"))
    assert payload["event"] == "stage_started"
    assert payload["stage"] == "REMESH"


def test_pipeline_config_keeps_legacy_remesh_mesh_defaults(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig

    config = PipelineConfig(
        mesh_dir=tmp_path / "clean_mesh",
        landmarks_dir=tmp_path / "landmarks",
    )

    assert config.raw_mesh_dir == Path("output/remesh_r24/raw")
    assert config.repaired_mesh_dir == Path("output/remesh_r24/repaired")
    assert config.salvaged_mesh_dir == Path("output/remesh_r24/salvaged")


def test_subprocess_remesh_receives_all_scoped_output_directories(
    tmp_path: Path,
    monkeypatch,
):
    import ear_param.pipeline as pipeline

    root = tmp_path / "run"
    config = pipeline.PipelineConfig(
        mesh_dir=tmp_path / "data" / "clean_mesh",
        landmarks_dir=tmp_path / "data" / "landmarks",
        canonical_dir=root / "canonical",
        raw_dir=root / "points" / "raw",
        repaired_dir=root / "points" / "repaired",
        salvaged_dir=root / "points" / "salvaged",
        raw_mesh_dir=root / "meshes" / "raw",
        repaired_mesh_dir=root / "meshes" / "repaired",
        salvaged_mesh_dir=root / "meshes" / "salvaged",
        max_salvage_unmapped_ratio=0.28,
    )
    commands: list[list[str]] = []

    def fake_run(command: list[str], cwd: Path) -> None:
        commands.append(command)
        config.raw_dir.mkdir(parents=True, exist_ok=True)
        config.salvaged_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"status": ["PASS"]}).to_csv(
            config.raw_dir / "T001_L_remesh_qc.csv", index=False
        )
        pd.DataFrame({"status": ["PASS"]}).to_csv(
            config.salvaged_dir / "T001_L_remesh_qc.csv", index=False
        )

    monkeypatch.setattr(pipeline, "_run_command", fake_run)
    pipeline.build_subprocess_stages(config).remesh_sample("T001_L")

    command = commands[0]
    assert command[command.index("--salvaged_mesh_out_dir") + 1] == str(config.salvaged_mesh_dir)
    assert "--out_dir" not in command
    assert "--mesh_out_dir" not in command
    assert "--repaired_out_dir" not in command
    assert "--repaired_mesh_out_dir" not in command
    assert command[command.index("--max_salvage_unmapped_ratio") + 1] == "0.28"


def test_subprocess_remesh_passes_original_mq_sample_tag(tmp_path: Path, monkeypatch):
    import ear_param.pipeline as pipeline

    config = pipeline.PipelineConfig(
        mesh_dir=tmp_path / "data" / "clean_mesh",
        landmarks_dir=tmp_path / "data" / "landmarks",
        raw_dir=tmp_path / "raw",
        salvaged_dir=tmp_path / "salvaged",
    )
    commands: list[list[str]] = []

    def fake_run(command: list[str], cwd: Path) -> None:
        commands.append(command)
        config.raw_dir.mkdir(parents=True, exist_ok=True)
        config.salvaged_dir.mkdir(parents=True, exist_ok=True)
        for output_dir in (config.raw_dir, config.salvaged_dir):
            pd.DataFrame({"status": ["PASS"]}).to_csv(
                output_dir / "MQ_S001L_remesh_qc.csv", index=False
            )

    monkeypatch.setattr(pipeline, "_run_command", fake_run)

    pipeline.build_subprocess_stages(config).remesh_sample("MQ_S001L")

    command = commands[0]
    assert command[command.index("--sample-tag") + 1] == "MQ_S001L"


def test_subprocess_weld_preserves_mq_sample_tag(tmp_path: Path, monkeypatch):
    import ear_param.pipeline as pipeline

    config = pipeline.PipelineConfig(
        mesh_dir=tmp_path / "data" / "clean_mesh",
        landmarks_dir=tmp_path / "data" / "landmarks",
        weld_dir=tmp_path / "weld",
    )

    captured_commands: list[list[str]] = []

    def fake_run(command: list[str], cwd: Path) -> None:
        captured_commands.append(command)
        config.weld_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({
            "sample_id": ["MQ_S001"],
            "side": ["L"],
            "status": ["PASS"],
            "pca_ready": [True],
        }).to_csv(config.weld_dir / "whole_ear_weld_summary.csv", index=False)

    monkeypatch.setattr(pipeline, "_run_command", fake_run)

    summary = pipeline.build_subprocess_stages(config).weld_batch(["MQ_S001L"])

    assert summary["sample_tag"].tolist() == ["MQ_S001L"]
    command = captured_commands[0]
    assert command[command.index("--weld_warning_mm") + 1] == "0.5"
    assert command[command.index("--weld_fail_mm") + 1] == "1.5"


def test_full_pipeline_marks_no_weld_pass_as_failed_no_valid_result():
    from scripts.run_full_pipeline import pipeline_terminal_error, pipeline_terminal_status

    result = SimpleNamespace(records=pd.DataFrame({"weld": ["ERROR", "SKIPPED"]}))

    assert pipeline_terminal_status(result) == "FAILED_NO_VALID_RESULT"
    assert "整耳拼接" in pipeline_terminal_error(result)


def test_subprocess_remesh_qc_receives_effective_salvage_limits(monkeypatch):
    import ear_param.pipeline as pipeline

    config = pipeline.PipelineConfig(
        mesh_dir=Path("data/clean_mesh"),
        landmarks_dir=Path("data/landmarks"),
        max_salvage_unmapped_ratio=0.28,
        max_salvage_degenerate_ratio=0.012,
        qc_figure_mode="repaired-fail",
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        pipeline,
        "_run_command",
        lambda command, cwd: commands.append(command),
    )
    monkeypatch.setattr(
        pipeline.pd,
        "read_csv",
        lambda path: pd.DataFrame({"sample_tag": ["T001_L"], "status": ["PASS"]}),
    )

    status = pipeline.build_subprocess_stages(config).remesh_qc("T001_L")

    assert status == "PASS"
    assert len(commands) == 1
    command = commands[0]
    assert "--max_salvage_unmapped_ratio" in command
    assert command[command.index("--max_salvage_unmapped_ratio") + 1] == "0.28"
    assert command[command.index("--max_salvage_degenerate_ratio") + 1] == "0.012"
    assert command[command.index("--figure-mode") + 1] == "repaired-fail"


def test_parallel_subprocess_qc_uses_a_private_summary_dir(monkeypatch, tmp_path: Path):
    import ear_param.pipeline as pipeline

    config = pipeline.PipelineConfig(
        mesh_dir=tmp_path / "inputs" / "clean_mesh",
        landmarks_dir=tmp_path / "inputs" / "landmarks",
        qc_dir=tmp_path / "qc",
        parallel_workers=2,
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(pipeline, "_run_command", lambda command, cwd: commands.append(command))
    monkeypatch.setattr(
        pipeline.pd,
        "read_csv",
        lambda path: pd.DataFrame({"sample_tag": ["T001_L"], "status": ["PASS"]}),
    )

    pipeline.build_subprocess_stages(config).remesh_qc("T001_L")

    command = commands[0]
    assert command[command.index("--summary-dir") + 1] == str(
        config.qc_dir / "_sample_summaries" / "T001_L"
    )


def test_merge_private_qc_summaries_restores_sorted_standard_summaries(tmp_path: Path):
    from ear_param.pipeline import _merge_private_qc_summaries

    qc_dir = tmp_path / "qc"
    for sample_tag in ("T002_L", "T001_L"):
        for layer in ("raw", "repaired", "salvaged"):
            path = qc_dir / "_sample_summaries" / sample_tag / layer
            path.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"sample_tag": [sample_tag], "region_id": ["R02"], "status": ["PASS"]}).to_csv(
                path / "qc_visualization_summary.csv", index=False
            )

    _merge_private_qc_summaries(qc_dir, ["T002_L", "T001_L"])

    merged = pd.read_csv(qc_dir / "salvaged" / "qc_visualization_summary.csv")
    assert merged["sample_tag"].tolist() == ["T001_L", "T002_L"]


def test_subprocess_pca_branches_receive_effective_variance_threshold(
    tmp_path: Path,
    monkeypatch,
):
    import ear_param.pipeline as pipeline

    root = tmp_path / "run"
    config = pipeline.PipelineConfig(
        mesh_dir=tmp_path / "data" / "clean_mesh",
        landmarks_dir=tmp_path / "data" / "landmarks",
        weld_dir=root / "weld",
        aligned_dir=root / "aligned",
        pca_dir=root / "pca",
        reference_aligned_dir=root / "reference_aligned",
        reference_pca_dir=root / "reference_pca",
        pca_variance_threshold=0.82,
    )
    commands: list[list[str]] = []

    def fake_run(command: list[str], cwd: Path) -> None:
        commands.append(command)
        out_dir = Path(command[command.index("--out_dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"sample_tag": ["T001_L"], "included": [True]}).to_csv(
            out_dir / "pca_input_manifest.csv",
            index=False,
        )
        pd.DataFrame({
            "retained_component_count": [1],
            "retained_cumulative_explained_variance_ratio": [0.9],
        }).to_csv(out_dir / "pca_summary.csv", index=False)

    monkeypatch.setattr(pipeline, "_run_command", fake_run)
    stages = pipeline.build_subprocess_stages(config)
    stages.pca_batch()
    assert stages.fixed_reference_pca_batch is not None
    stages.fixed_reference_pca_batch()

    assert len(commands) == 2
    assert all(
        command[command.index("--variance_threshold") + 1] == "0.82"
        for command in commands
    )


def test_pipeline_allows_raw_remesh_warning_when_salvage_passes(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    for sample_tag in ("T001_L", "T002_L"):
        (mesh_dir / f"{sample_tag}.ply").write_text("mesh placeholder")
        (landmarks_dir / f"{sample_tag}_landmarks.csv").write_text("landmark_id,x,y,z\n")

    stages = StageFunctions(
        remesh_sample=lambda tag: {"remesh": "WARNING", "salvage": "PASS"},
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame({
            "sample_tag": tags,
            "status": ["PASS", "PASS"],
            "pca_ready": [True, True],
        }),
        alignment_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": ["PASS", "PASS"]}),
        pca_batch=lambda: {"status": "PASS", "included_tags": ["T001_L", "T002_L"]},
    )

    result = run_pipeline(
        PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir),
        stage_functions=stages,
    )

    records = result.records.set_index("sample_tag")
    assert records.loc["T001_L", "remesh"] == "WARNING"
    assert records.loc["T001_L", "remesh_qc"] == "PASS"
    assert records.loc["T001_L", "weld"] == "PASS"
    assert records.loc["T001_L", "alignment"] == "PASS"
    assert records.loc["T001_L", "pca_included"] == "YES"


def test_pipeline_visualizes_remesh_qc_when_salvage_fails(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    (mesh_dir / "T001_L.ply").write_text("mesh placeholder")
    (landmarks_dir / "T001_L_landmarks.csv").write_text("landmark_id,x,y,z\n")

    visualized: list[str] = []
    stages = StageFunctions(
        remesh_sample=lambda tag: {"remesh": "FAIL", "salvage": "FAIL"},
        remesh_qc=lambda tag: visualized.append(tag) or "FAIL",
        weld_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status", "pca_ready"]),
        alignment_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status"]),
        pca_batch=lambda: {"status": "PASS", "included_tags": []},
    )

    result = run_pipeline(
        PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir),
        stage_functions=stages,
    )

    record = result.records.iloc[0]
    assert visualized == ["T001_L"]
    assert record["salvage"] == "FAIL"
    assert record["remesh_qc"] == "FAIL"
    assert record["weld"] == "SKIPPED"


def test_pipeline_writes_summary_and_skips_pca_under_two_aligned_samples(tmp_path: Path):
    from ear_param.pipeline import (
        PipelineConfig,
        StageFunctions,
        run_pipeline,
        write_pipeline_outputs,
    )

    mesh_dir = tmp_path / "clean_mesh"
    landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    (mesh_dir / "T001_L.ply").write_text("mesh placeholder")
    (landmarks_dir / "T001_L_landmarks.csv").write_text("landmark_id,x,y,z\n")

    stages = StageFunctions(
        remesh_sample=lambda tag: {"remesh": "PASS", "salvage": "PASS"},
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame({
            "sample_tag": tags,
            "status": ["PASS"],
            "pca_ready": [True],
        }),
        alignment_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": ["PASS"]}),
        pca_batch=lambda: {"status": "PASS", "included_tags": ["T001_L"]},
    )
    result = run_pipeline(
        PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir),
        stage_functions=stages,
    )
    run_dir = tmp_path / "pipeline_run"

    write_pipeline_outputs(result, run_dir)

    assert result.pca_status == "SKIPPED_INSUFFICIENT_SAMPLES"
    assert (run_dir / "pipeline_batch_summary.csv").is_file()
    assert (run_dir / "pipeline_run_summary.csv").is_file()
    assert (run_dir / "pipeline_run.log").is_file()


def test_pipeline_records_right_sample_canonicalization(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir, landmarks_dir = tmp_path / "clean_mesh", tmp_path / "landmarks"
    mesh_dir.mkdir(); landmarks_dir.mkdir()
    trimesh.Trimesh(vertices=[[1, 0, 0], [0, 1, 0], [0, 0, 1]], faces=[[0, 1, 2]], process=False).export(mesh_dir / "T001_R.ply")
    pd.DataFrame({"landmark_id": ["L7"], "x": [1.], "y": [0.], "z": [0.]}).to_csv(landmarks_dir / "T001_R_landmarks.csv", index=False)
    stages = StageFunctions(lambda tag: {"remesh": "PASS", "salvage": "FAIL"}, lambda tag: "PASS", lambda tags: pd.DataFrame(), lambda tags: pd.DataFrame(), lambda: {})

    result = run_pipeline(PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir, canonical_dir=tmp_path / "canonical", disable_side_normalization=False), stage_functions=stages)

    record = result.records.iloc[0]
    assert record["source_side"] == "R"
    assert record["canonical_side"] == "L"
    assert bool(record["mirrored"])


def test_pipeline_runs_isolated_fixed_reference_pca_branch(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir, landmarks_dir = tmp_path / "clean_mesh", tmp_path / "landmarks"
    mesh_dir.mkdir(); landmarks_dir.mkdir()
    for sample_tag in ("T001_L", "T002_L"):
        (mesh_dir / f"{sample_tag}.ply").write_text("mesh placeholder")
        (landmarks_dir / f"{sample_tag}_landmarks.csv").write_text("landmark_id,x,y,z\n")

    calls: list[tuple[str, object]] = []
    stages = StageFunctions(
        remesh_sample=lambda tag: {"remesh": "PASS", "salvage": "PASS"},
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": "PASS", "pca_ready": True}),
        alignment_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": "PASS"}),
        pca_batch=lambda: {"status": "PASS", "included_tags": ["T001_L", "T002_L"]},
        fixed_reference_alignment_batch=lambda tags, reference: (
            calls.append(("alignment", (tags, reference)))
            or pd.DataFrame({"sample_tag": tags, "status": "PASS"})
        ),
        fixed_reference_pca_batch=lambda: (
            calls.append(("pca", None))
            or {"status": "PASS", "included_tags": ["T001_L", "T002_L"]}
        ),
    )

    result = run_pipeline(
        PipelineConfig(
            mesh_dir=mesh_dir,
            landmarks_dir=landmarks_dir,
            reference_sample="T001_L",
        ),
        stage_functions=stages,
    )

    records = result.records.set_index("sample_tag")
    assert calls == [
        ("alignment", (["T001_L", "T002_L"], "T001_L")),
        ("pca", None),
    ]
    assert records.loc["T001_L", "alignment"] == "PASS"
    assert records.loc["T001_L", "reference_alignment"] == "PASS"
    assert records.loc["T001_L", "pca_included"] == "YES"
    assert records.loc["T001_L", "reference_pca_included"] == "YES"
    assert result.pca_status == "PASS"
    assert result.reference_pca_status == "PASS"


def test_fixed_reference_mode_uses_reference_branch_as_primary_result(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir, landmarks_dir = tmp_path / "clean_mesh", tmp_path / "landmarks"
    mesh_dir.mkdir(); landmarks_dir.mkdir()
    for sample_tag in ("T001_L", "T002_L"):
        (mesh_dir / f"{sample_tag}.ply").write_text("mesh placeholder")
        (landmarks_dir / f"{sample_tag}_landmarks.csv").write_text("landmark_id,x,y,z\n")

    calls: list[str] = []
    stages = StageFunctions(
        remesh_sample=lambda tag: {"remesh": "PASS", "salvage": "PASS"},
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": "PASS", "pca_ready": True}),
        alignment_batch=lambda tags: calls.append("gpa-alignment") or pd.DataFrame(),
        pca_batch=lambda: calls.append("gpa-pca") or {"status": "PASS", "included_tags": []},
        fixed_reference_alignment_batch=lambda tags, reference: (
            calls.append("reference-alignment")
            or pd.DataFrame({"sample_tag": tags, "status": "PASS"})
        ),
        fixed_reference_pca_batch=lambda: (
            calls.append("reference-pca")
            or {"status": "PASS", "included_tags": ["T001_L", "T002_L"]}
        ),
    )

    result = run_pipeline(
        PipelineConfig(
            mesh_dir=mesh_dir,
            landmarks_dir=landmarks_dir,
            reference_sample="T001_L",
            alignment_mode="fixed-reference",
        ),
        stage_functions=stages,
    )

    assert calls == ["reference-alignment", "reference-pca"]
    assert result.pca_status == "PASS"
    assert result.pca_result == result.reference_pca_result
    assert set(result.records["alignment"]) == {"PASS"}
    assert set(result.records["pca_included"]) == {"YES"}


def test_fixed_reference_mode_requires_reference_sample():
    from scripts.run_full_pipeline import build_parser, build_pipeline_config

    args = build_parser().parse_args(["--alignment-mode", "fixed-reference"])

    with pytest.raises(ValueError, match="reference-sample"):
        build_pipeline_config(args)


def test_pipeline_subprocesses_are_hidden_on_windows(monkeypatch, tmp_path: Path):
    import ear_param.pipeline as pipeline

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda command, **kwargs: captured.update(command=command, **kwargs),
    )
    monkeypatch.setattr(pipeline.sys, "platform", "win32")

    pipeline._run_command(["python", "stage.py"], tmp_path)

    assert captured["creationflags"] == pipeline.subprocess.CREATE_NO_WINDOW


def test_pipeline_runs_independent_remesh_samples_in_parallel_and_keeps_row_order(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir, landmarks_dir = tmp_path / "clean_mesh", tmp_path / "landmarks"
    mesh_dir.mkdir(); landmarks_dir.mkdir()
    for sample_tag in ("T001_L", "T002_L"):
        (mesh_dir / f"{sample_tag}.ply").write_text("mesh placeholder")
        (landmarks_dir / f"{sample_tag}_landmarks.csv").write_text("landmark_id,x,y,z\n")
    second_started = Event()

    def remesh_sample(sample_tag: str) -> dict[str, str]:
        if sample_tag == "T001_L":
            assert second_started.wait(0.5), "second sample was not started in parallel"
        else:
            second_started.set()
        return {"remesh": "PASS", "salvage": "PASS"}

    stages = StageFunctions(
        remesh_sample=remesh_sample,
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status", "pca_ready"]),
        alignment_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status"]),
        pca_batch=lambda: {"status": "PASS", "included_tags": []},
    )

    result = run_pipeline(
        PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir, parallel_workers=2),
        stage_functions=stages,
    )

    assert result.records["sample_tag"].tolist() == ["T001_L", "T002_L"]
    assert result.records["remesh"].tolist() == ["PASS", "PASS"]


def test_parallel_remesh_relays_sample_region_events_from_private_logs(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir, landmarks_dir = tmp_path / "clean_mesh", tmp_path / "landmarks"
    mesh_dir.mkdir(); landmarks_dir.mkdir()
    (mesh_dir / "T001_L.ply").write_text("mesh placeholder")
    (landmarks_dir / "T001_L_landmarks.csv").write_text("landmark_id,x,y,z\n")
    events: list[tuple[str, dict[str, object]]] = []
    stages = StageFunctions(
        remesh_sample=lambda tag: {"remesh": "PASS", "salvage": "PASS"},
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status", "pca_ready"]),
        alignment_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status"]),
        pca_batch=lambda: {"status": "PASS", "included_tags": []},
        remesh_events=lambda tag: [{"event": "region_finished", "sample_tag": tag, "region_id": "R01"}],
    )

    run_pipeline(
        PipelineConfig(
            mesh_dir=mesh_dir,
            landmarks_dir=landmarks_dir,
            parallel_workers=2,
            event_reporter=lambda event, fields: events.append((event, fields)),
        ),
        stage_functions=stages,
    )

    assert ("region_finished", {"sample_tag": "T001_L", "region_id": "R01"}) in events


def test_incremental_private_event_reader_keeps_partial_line_for_next_poll(tmp_path: Path):
    from ear_param.pipeline import _read_jsonl_events_incrementally

    path = tmp_path / "T001_L.jsonl"
    first = b'{"event":"region_started","region_id":"R01"}\n'
    second = b'{"event":"region_finished","region_id":"R01"}'
    path.write_bytes(first + second[:20])

    events, offset = _read_jsonl_events_incrementally(path, 0)

    assert events == [{"event": "region_started", "region_id": "R01"}]
    assert offset == len(first)
    with path.open("ab") as stream:
        stream.write(second[20:] + b"\n")
    events, offset = _read_jsonl_events_incrementally(path, offset)
    assert events == [{"event": "region_finished", "region_id": "R01"}]
    assert offset == len(first) + len(second) + 1


def test_parallel_remesh_relays_region_event_before_sample_finishes(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir, landmarks_dir = tmp_path / "clean_mesh", tmp_path / "landmarks"
    mesh_dir.mkdir(); landmarks_dir.mkdir()
    (mesh_dir / "T001_L.ply").write_text("mesh placeholder")
    (landmarks_dir / "T001_L_landmarks.csv").write_text("landmark_id,x,y,z\n")
    event_ready = Event()
    event_forwarded = Event()
    sent = False
    received: list[tuple[str, dict[str, object]]] = []

    def remesh_sample(tag: str) -> dict[str, str]:
        event_ready.set()
        assert event_forwarded.wait(0.5), "region event was not forwarded during processing"
        return {"remesh": "PASS", "salvage": "PASS"}

    def poll_events(tag: str) -> list[dict[str, object]]:
        nonlocal sent
        if event_ready.is_set() and not sent:
            sent = True
            return [{"event": "region_finished", "sample_tag": tag, "region_id": "R01"}]
        return []

    def report(event: str, fields: dict[str, object]) -> None:
        received.append((event, fields))
        if event == "region_finished":
            event_forwarded.set()

    stages = StageFunctions(
        remesh_sample=remesh_sample,
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status", "pca_ready"]),
        alignment_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status"]),
        pca_batch=lambda: {"status": "PASS", "included_tags": []},
        poll_remesh_events=poll_events,
    )

    run_pipeline(
        PipelineConfig(
            mesh_dir=mesh_dir,
            landmarks_dir=landmarks_dir,
            parallel_workers=2,
            event_reporter=report,
        ),
        stage_functions=stages,
    )

    assert ("region_finished", {"sample_tag": "T001_L", "region_id": "R01"}) in received


def test_parallel_remesh_runs_qc_calls_concurrently_when_outputs_are_isolated(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline

    mesh_dir, landmarks_dir = tmp_path / "clean_mesh", tmp_path / "landmarks"
    mesh_dir.mkdir(); landmarks_dir.mkdir()
    for sample_tag in ("T001_L", "T002_L"):
        (mesh_dir / f"{sample_tag}.ply").write_text("mesh placeholder")
        (landmarks_dir / f"{sample_tag}_landmarks.csv").write_text("landmark_id,x,y,z\n")
    lock = Lock()
    active_qc = 0
    max_active_qc = 0

    def remesh_sample(tag: str) -> dict[str, str]:
        return {"remesh": "PASS", "salvage": "PASS"}

    def remesh_qc(tag: str) -> str:
        nonlocal active_qc, max_active_qc
        with lock:
            active_qc += 1
            max_active_qc = max(max_active_qc, active_qc)
        time.sleep(0.05)
        with lock:
            active_qc -= 1
        return "PASS"

    stages = StageFunctions(
        remesh_sample=remesh_sample, remesh_qc=remesh_qc,
        weld_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status", "pca_ready"]),
        alignment_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status"]),
        pca_batch=lambda: {"status": "PASS", "included_tags": []},
    )

    run_pipeline(
        PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir, parallel_workers=2),
        stage_functions=stages,
    )

    assert max_active_qc == 2


def test_pipeline_writes_sample_timing_summary(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline, write_pipeline_outputs

    mesh_dir, landmarks_dir = tmp_path / "clean_mesh", tmp_path / "landmarks"
    mesh_dir.mkdir(); landmarks_dir.mkdir()
    (mesh_dir / "T001_L.ply").write_text("mesh placeholder")
    (landmarks_dir / "T001_L_landmarks.csv").write_text("landmark_id,x,y,z\n")
    stages = StageFunctions(
        remesh_sample=lambda tag: {"remesh": "PASS", "salvage": "PASS"},
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status", "pca_ready"]),
        alignment_batch=lambda tags: pd.DataFrame(columns=["sample_tag", "status"]),
        pca_batch=lambda: {"status": "PASS", "included_tags": []},
    )

    result = run_pipeline(
        PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir, parallel_workers=1),
        stage_functions=stages,
    )
    write_pipeline_outputs(result, tmp_path / "run")

    timings = pd.read_csv(tmp_path / "run" / "pipeline_timing_summary.csv")
    assert timings[["stage", "sample_tag"]].values.tolist()[:2] == [
        ["REMESH", "T001_L"],
        ["REMESH_QC", "T001_L"],
    ]
    timing_text = (tmp_path / "run" / "sample_processing_time.txt").read_text(encoding="utf-8")
    assert "T001_L" in timing_text
    assert "总耗时" in timing_text


def test_pipeline_timing_summary_includes_global_stage_elapsed_time(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig, StageFunctions, run_pipeline, write_pipeline_outputs

    mesh_dir, landmarks_dir = tmp_path / "clean_mesh", tmp_path / "landmarks"
    mesh_dir.mkdir(); landmarks_dir.mkdir()
    for sample_tag in ("T001_L", "T002_L"):
        (mesh_dir / f"{sample_tag}.ply").write_text("mesh placeholder")
        (landmarks_dir / f"{sample_tag}_landmarks.csv").write_text("landmark_id,x,y,z\n")
    stages = StageFunctions(
        remesh_sample=lambda tag: {"remesh": "PASS", "salvage": "PASS"},
        remesh_qc=lambda tag: "PASS",
        weld_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": ["PASS", "PASS"], "pca_ready": [True, True]}),
        alignment_batch=lambda tags: pd.DataFrame({"sample_tag": tags, "status": ["PASS", "PASS"]}),
        pca_batch=lambda: {"status": "PASS", "included_tags": ["T001_L", "T002_L"]},
    )

    result = run_pipeline(PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir), stage_functions=stages)
    write_pipeline_outputs(result, tmp_path / "run")

    timings = pd.read_csv(tmp_path / "run" / "pipeline_timing_summary.csv")
    assert {"WELD", "ALIGNMENT", "GPA_PCA"}.issubset(set(timings["stage"]))
    assert pd.isna(timings.loc[timings["stage"] == "WELD", "sample_tag"].item())
