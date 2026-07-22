#!/usr/bin/env python3
"""Run the official W2-to-W3 batch pipeline over all paired ear samples."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ear_param.pipeline import (
    PipelineConfig,
    PipelineResult,
    build_subprocess_stages,
    run_pipeline,
    write_pipeline_outputs,
)
from ear_param.events import JsonlEventWriter
from ear_param.run_artifacts import PipelineOutputLayout, prepare_empty_output_root
from ear_param.run_manifest import create_run_manifest, finish_manifest, write_manifest
from ear_param.run_control import FileRunControl, RunCancelled


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run remesh, QC, weld repair, GPA-PCA, and optional fixed-reference PCA."
    )
    parser.add_argument("--mesh_dir", default="data/clean_mesh")
    parser.add_argument("--landmarks_dir", default="data/landmarks")
    parser.add_argument("--regions", default="config/region_table.csv")
    parser.add_argument("--samples", nargs="+", help="Optional sample tags, e.g. MQ_S076L MQ_S077L.")
    parser.add_argument("--skip-remesh-qc", action="store_true")
    parser.add_argument(
        "--qc-figure-mode",
        choices=("all", "repaired-fail", "none"),
        default="all",
        help="Region QC PNG generation: all, repaired-fail, or none.",
    )
    parser.add_argument("--canonical-side", default="L", choices=("L",))
    parser.add_argument("--mirror-axis", default="x", choices=("x", "y", "z"))
    parser.add_argument(
        "--max-salvage-unmapped-ratio",
        type=float,
        default=0.35,
        help="Maximum raw unmapped ratio eligible for salvage attempts.",
    )
    parser.add_argument(
        "--max-salvage-degenerate-ratio",
        type=float,
        default=0.015,
        help="Maximum raw degenerate-face ratio eligible for salvaged UV repair.",
    )
    parser.add_argument(
        "--pca-variance-threshold",
        type=float,
        default=0.75,
        help="Cumulative explained-variance threshold for both PCA branches.",
    )
    parser.add_argument("--skip-pca", action="store_true")
    parser.add_argument(
        "--parallel-workers",
        type=int,
        default=1,
        help="Concurrent Remesh/QC samples; 0 selects the bounded automatic desktop setting.",
    )
    parser.add_argument(
        "--alignment-mode",
        choices=("gpa", "fixed-reference"),
        default="gpa",
        help="Alignment and PCA route: GPA (default) or a selected fixed-reference ear.",
    )
    parser.add_argument(
        "--reference-sample",
        help="Optional fixed-reference ear tag, e.g. MQ_S076L; enables the second PCA branch.",
    )
    parser.add_argument("--run_dir", help="Directory for this run's summary artifacts.")
    parser.add_argument(
        "--output-root",
        help="Optional isolated root for every stage output; must be empty.",
    )
    parser.add_argument("--event-log", help="Optional JSONL event log for a desktop run.")
    parser.add_argument("--control-path", help="Optional desktop pause/cancel control file.")
    return parser


def build_pipeline_config(
    args: argparse.Namespace,
) -> tuple[PipelineConfig, Path, PipelineOutputLayout | None]:
    if args.parallel_workers < 0:
        raise ValueError("--parallel-workers must be zero or a positive integer")
    if args.alignment_mode == "fixed-reference" and not args.reference_sample:
        raise ValueError("--reference-sample is required when --alignment-mode fixed-reference")
    output_root = Path(args.output_root) if args.output_root else None
    if output_root is not None and args.run_dir:
        requested_run_dir = Path(args.run_dir)
        if requested_run_dir.resolve() != output_root.resolve():
            raise ValueError("--run_dir must resolve to --output-root in isolated mode")
        run_dir = output_root
    else:
        run_dir = (
            Path(args.run_dir)
            if args.run_dir
            else output_root
            if output_root is not None
            else Path("output/pipeline_runs") / datetime.now().strftime("%Y%m%d_%H%M%S")
        )
    layout = (
        PipelineOutputLayout.from_output_root(
            output_root,
            reference_sample=args.reference_sample,
        )
        if output_root is not None
        else None
    )
    config_kwargs: dict[str, object] = {
        "mesh_dir": Path(args.mesh_dir),
        "landmarks_dir": Path(args.landmarks_dir),
        "regions": Path(args.regions),
        "sample_tags": tuple(args.samples or ()),
        "skip_remesh_qc": args.skip_remesh_qc,
        "qc_figure_mode": args.qc_figure_mode,
        "canonical_side": args.canonical_side,
        "mirror_axis": args.mirror_axis,
        "max_salvage_unmapped_ratio": args.max_salvage_unmapped_ratio,
        "max_salvage_degenerate_ratio": args.max_salvage_degenerate_ratio,
        "pca_variance_threshold": args.pca_variance_threshold,
        "disable_side_normalization": False,
        "skip_pca": args.skip_pca,
        "reference_sample": args.reference_sample,
        "alignment_mode": args.alignment_mode,
        "parallel_workers": args.parallel_workers,
        "reporter": print,
    }
    if args.event_log:
        config_kwargs["event_log"] = Path(args.event_log)
        writer = JsonlEventWriter(Path(args.event_log))
        config_kwargs["event_reporter"] = (
            lambda event, fields: writer.emit(event, **fields)
        )
    if args.control_path:
        config_kwargs["checkpoint"] = FileRunControl(Path(args.control_path)).checkpoint
    if layout is not None:
        config_kwargs.update(layout.pipeline_config_kwargs())
    return PipelineConfig(**config_kwargs), run_dir, layout


def _print_final_summary(result: PipelineResult, run_dir: Path) -> None:
    print("\n[Pipeline] Final summary:")
    print(result.records.to_string(index=False))
    print(f"[Pipeline] PCA status: {result.pca_status}")
    print(f"[Pipeline] Fixed-reference PCA status: {result.reference_pca_status}")
    print(f"[Pipeline] Run artifacts: {run_dir}")


def execute(args: argparse.Namespace) -> PipelineResult | None:
    config, run_dir, layout = build_pipeline_config(args)
    if layout is not None:
        prepare_empty_output_root(layout.output_root)
    manifest_path = run_dir / "manifest.json"
    manifest = create_run_manifest(
        config=config,
        run_dir=run_dir,
        output_root=layout.output_root if layout else None,
        project_root=_PROJECT_ROOT,
        argv=sys.argv[1:],
    )
    write_manifest(manifest_path, manifest)
    try:
        result = run_pipeline(config, stage_functions=build_subprocess_stages(config))
        write_pipeline_outputs(result, run_dir)
    except RunCancelled as exc:
        finish_manifest(manifest_path, status="CANCELLED", error=str(exc))
        print("[Pipeline] Cancelled by desktop controller.")
        return None
    except BaseException as exc:
        finish_manifest(manifest_path, status="ERROR", error=str(exc))
        raise
    finish_manifest(manifest_path, status="COMPLETED", result=result)
    _print_final_summary(result, run_dir)
    return result


def main() -> None:
    result = execute(build_parser().parse_args())
    if result is None:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
