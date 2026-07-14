"""Command-line interface for ear mesh alignment."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .pipeline import DEFAULT_LANDMARK_IDS, align_and_export_mesh


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rigidly align an ear mesh and export OBJ/STL without scaling."
    )
    parser.add_argument("--ref-model", required=True)
    parser.add_argument("--moving-model", required=True)
    parser.add_argument("--ref-landmarks", required=True)
    parser.add_argument("--moving-landmarks", required=True)
    parser.add_argument("--out-obj", required=True)
    parser.add_argument("--out-stl", required=True)
    parser.add_argument(
        "--landmark-ids", nargs="+", default=list(DEFAULT_LANDMARK_IDS), metavar="ID"
    )
    parser.add_argument("--mirror-axis", choices=("x", "y", "z"), default="x")
    parser.add_argument(
        "--no-auto-mirror",
        action="store_true",
        help="Do not detect L/R filename tokens or mirror the moving ear.",
    )
    parser.add_argument("--out-landmarks")
    parser.add_argument("--transform-json")
    parser.add_argument("--metrics-json")
    parser.add_argument(
        "--keep-reference-origin",
        action="store_true",
        help="Keep the reference model's original origin instead of centering the selected landmarks.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = align_and_export_mesh(
        ref_mesh_path=args.ref_model,
        moving_mesh_path=args.moving_model,
        ref_landmark_csv=args.ref_landmarks,
        moving_landmark_csv=args.moving_landmarks,
        output_obj_path=args.out_obj,
        output_stl_path=args.out_stl,
        landmark_ids=tuple(args.landmark_ids),
        auto_mirror=not args.no_auto_mirror,
        mirror_axis=args.mirror_axis,
        output_landmarks_path=args.out_landmarks,
        transform_path=args.transform_json,
        metrics_path=args.metrics_json,
        center_reference=not args.keep_reference_origin,
    )
    print(
        json.dumps(
            {
                "obj": str(result.output_obj_path),
                "stl": str(result.output_stl_path),
                "landmarks": str(result.output_landmarks_path),
                "transform": str(result.transform_path),
                "metrics": str(result.metrics_path),
                "reference_obj": str(result.output_reference_obj_path) if result.output_reference_obj_path else None,
                "reference_stl": str(result.output_reference_stl_path) if result.output_reference_stl_path else None,
                "reference_landmarks": str(result.output_reference_landmarks_path) if result.output_reference_landmarks_path else None,
                "reference_centroid_original": result.reference_centroid.tolist(),
                "mirrored": result.mirrored,
                "rms_error": result.metrics["rms_error"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
