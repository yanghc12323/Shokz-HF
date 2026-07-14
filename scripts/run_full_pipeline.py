#!/usr/bin/env python3
"""Run the official W2-to-W3 batch pipeline over all paired ear samples."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ear_param.pipeline import (
    PipelineConfig,
    build_subprocess_stages,
    run_pipeline,
    write_pipeline_outputs,
)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run remesh, QC, weld repair, GPA-PCA, and optional fixed-reference PCA."
    )
    parser.add_argument("--mesh_dir", default="data/clean_mesh")
    parser.add_argument("--landmarks_dir", default="data/landmarks")
    parser.add_argument("--regions", default="config/region_table.csv")
    parser.add_argument("--samples", nargs="+", help="Optional sample tags, e.g. T076_L T077_L.")
    parser.add_argument("--skip-remesh-qc", action="store_true")
    parser.add_argument("--canonical-side", default="L", choices=("L",))
    parser.add_argument("--mirror-axis", default="x", choices=("x", "y", "z"))
    parser.add_argument("--skip-pca", action="store_true")
    parser.add_argument(
        "--reference-sample",
        help="Optional fixed-reference ear tag, e.g. T076_L; enables the second PCA branch.",
    )
    parser.add_argument("--run_dir", help="Directory for this run's summary artifacts.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else (
        Path("output/pipeline_runs") / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    config = PipelineConfig(
        mesh_dir=Path(args.mesh_dir),
        landmarks_dir=Path(args.landmarks_dir),
        regions=Path(args.regions),
        sample_tags=tuple(args.samples or ()),
        skip_remesh_qc=args.skip_remesh_qc,
        canonical_side=args.canonical_side,
        mirror_axis=args.mirror_axis,
        disable_side_normalization=False,
        skip_pca=args.skip_pca,
        reference_sample=args.reference_sample,
        reporter=print,
    )
    result = run_pipeline(config, stage_functions=build_subprocess_stages(config))
    write_pipeline_outputs(result, run_dir)
    print("\n[Pipeline] Final summary:")
    print(result.records.to_string(index=False))
    print(f"[Pipeline] PCA status: {result.pca_status}")
    print(f"[Pipeline] Fixed-reference PCA status: {result.reference_pca_status}")
    print(f"[Pipeline] Run artifacts: {run_dir}")


if __name__ == "__main__":
    main()
