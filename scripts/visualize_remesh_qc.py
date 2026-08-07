#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate visual QC figures for patch-based remesh regions."""

from __future__ import annotations

from pathlib import Path
import sys
from time import perf_counter

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd

from ear_param.io_utils import load_landmarks, load_mesh, read_csv_robust
from ear_param.pipeline import discover_sample_inputs, split_sample_tag
from ear_param.qc_visualization import (
    classify_region_qc,
    classify_repaired_region_qc,
    save_region_repaired_qc_figure,
)
from ear_param.remesh import build_region_remesh, repair_unmapped_samples


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate per-region remesh QC visualizations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python scripts/visualize_remesh_qc.py --samples MQ_S076L MQ_S077L
  python scripts/visualize_remesh_qc.py --samples MQ_S076L MQ_S077L --region_ids T001 T008
        """,
    )
    parser.add_argument("--samples", nargs="+", help="Sample tags, e.g. MQ_S076L MQ_S077L.")
    parser.add_argument("--region_ids", nargs="+", help="Optional subset of region IDs.")
    parser.add_argument("--data_dir", default="data", help="Input data directory.")
    parser.add_argument("--regions", default="config/region_table.csv", help="Region table CSV path.")
    parser.add_argument("--out_dir", default="output/qc_visualizations_r24", help="Output root directory.")
    parser.add_argument(
        "--summary-dir",
        help="Optional QC summary root; figures always remain under --out_dir.",
    )
    parser.add_argument("--max_patch_faces", type=int, default=5000, help="Max patch faces drawn per 3D figure.")
    parser.add_argument(
        "--figure-mode",
        choices=("all", "repaired-fail", "none"),
        default="all",
        help="PNG generation mode; QC summaries are always written.",
    )
    parser.add_argument(
        "--max_salvage_unmapped_ratio",
        type=float,
        default=0.45,
        help="Maximum raw unmapped ratio allowed for raw-FAIL salvage attempts.",
    )
    parser.add_argument(
        "--max_salvage_degenerate_ratio",
        type=float,
        default=0.03,
        help="Maximum raw degenerate-face ratio allowed for salvaged UV repair.",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    summary_dir = summary_output_root(out_dir, Path(args.summary_dir) if args.summary_dir else None)
    salvaged_out_dir = out_dir / "salvaged"
    salvaged_out_dir.mkdir(parents=True, exist_ok=True)
    (summary_dir / "raw").mkdir(parents=True, exist_ok=True)
    (summary_dir / "repaired").mkdir(parents=True, exist_ok=True)
    (summary_dir / "salvaged").mkdir(parents=True, exist_ok=True)

    sample_tags = args.samples if args.samples else _discover_sample_tags(data_dir)
    if not sample_tags:
        raise SystemExit("No samples found. Use --samples or add meshes to data/clean_mesh.")
    source_inputs = {
        str(row.sample_tag): row
        for row in discover_sample_inputs(
            data_dir / "clean_mesh", data_dir / "landmarks"
        ).itertuples(index=False)
    }

    regions = read_csv_robust(Path(args.regions))
    if args.region_ids:
        wanted = set(args.region_ids)
        regions = regions[regions["region_id"].astype(str).isin(wanted)].reset_index(drop=True)
    if regions.empty:
        raise SystemExit("No regions selected.")

    raw_summary_records: list[dict[str, object]] = []
    repaired_summary_records: list[dict[str, object]] = []
    salvaged_summary_records: list[dict[str, object]] = []
    for sample_tag in sample_tags:
        sample_id, side = _split_sample_tag(sample_tag)
        try:
            source = source_inputs[sample_tag]
        except KeyError as exc:
            raise SystemExit(f"Input sample not found: {sample_tag}") from exc
        mesh_path = Path(source.mesh_path)
        landmarks_path = Path(source.landmarks_path)
        print(f"[QC] Loading {sample_tag}")
        mesh = load_mesh(mesh_path)
        landmarks = load_landmarks(landmarks_path)

        for _, row in regions.iterrows():
            region = row.to_dict()
            region_id = str(region["region_id"])
            print(f"[QC] {sample_tag} {region_id}")
            salvaged_figure_path = salvaged_out_dir / sample_tag / f"{region_id}_qc.png"
            try:
                region_started = perf_counter()
                result = build_region_remesh(mesh, landmarks, region)
                region_remesh_seconds = perf_counter() - region_started
                raw_record = classify_region_qc(sample_tag, result)
                repaired = repair_unmapped_samples(result)
                repaired_record = classify_repaired_region_qc(sample_tag, result, repaired)
                salvaged = repair_unmapped_samples(
                    result,
                    allow_raw_fail_repair=True,
                    max_raw_fail_repair_unmapped_ratio=args.max_salvage_unmapped_ratio,
                    max_raw_fail_repair_degenerate_ratio=args.max_salvage_degenerate_ratio,
                )
                salvaged_record = classify_repaired_region_qc(sample_tag, result, salvaged)
                figure_layers = figure_layers_for_mode(
                    args.figure_mode, str(repaired_record["status"])
                )
                raw_record.update({
                    "sample_id": sample_id,
                    "side": side,
                    "figure_path": "",
                    "error": "",
                })
                repaired_record.update({
                    "sample_id": sample_id,
                    "side": side,
                    "figure_path": "",
                    "error": "",
                })
                salvaged_record.update({
                    "sample_id": sample_id,
                    "side": side,
                    "figure_path": str(salvaged_figure_path) if "salvaged" in figure_layers else "",
                    "error": "",
                })
                for record in (raw_record, repaired_record, salvaged_record):
                    record["region_remesh_seconds"] = region_remesh_seconds
                    record["region_total_seconds"] = perf_counter() - region_started
                if "salvaged" in figure_layers:
                    save_region_repaired_qc_figure(mesh, result, salvaged, salvaged_figure_path, max_patch_faces=args.max_patch_faces)
                    salvaged_record["region_total_seconds"] = perf_counter() - region_started
            except Exception as exc:
                raw_record = {
                    "sample_tag": sample_tag,
                    "sample_id": sample_id,
                    "side": side,
                    "region_id": region_id,
                    "region_name": str(region.get("region_name", "")),
                    "sample_point_count": 0,
                    "expected_point_count": 0,
                    "unmapped_count": 0,
                    "unmapped_ratio": 0.0,
                    "flipped_faces": 0,
                    "degenerate_faces": 0,
                    "patch_face_count": 0,
                    "remesh_face_count": 0,
                    "status": "ERROR",
                    "figure_path": "",
                    "error": str(exc),
                }
                repaired_record = dict(raw_record)
                repaired_record.update({
                    "raw_unmapped_count": 0,
                    "raw_unmapped_ratio": 0.0,
                    "raw_status": "ERROR",
                    "repaired_unmapped_count": 0,
                    "repair_count": 0,
                    "repair_applied": False,
                    "salvage_attempted": False,
                    "salvage_accepted": False,
                    "salvage_rejection_reason": "region_error",
                    "degenerate_ratio": 0.0,
                    "degenerate_before": 0,
                    "degenerate_after": 0,
                    "degenerate_salvage_attempted": False,
                    "degenerate_salvage_accepted": False,
                    "degenerate_salvage_method": "",
                    "degenerate_salvage_rejection_reason": "region_error",
                    "dense_validation_resolution": 48,
                    "dense_unmapped_count": 0,
                    "dense_degenerate_face_count": 0,
                    "dense_min_triangle_area_3d": float("nan"),
                    "dense_failure_type": "not_run",
                    "dense_coverage_repair_attempted": False,
                    "dense_coverage_repair_accepted": False,
                    "dense_coverage_repair_before": 0,
                    "dense_coverage_repair_after": 0,
                    "dense_coverage_repair_max_uv_displacement": 0.0,
                    "degenerate_component_count": 0,
                    "largest_degenerate_component_faces": 0,
                    "degenerate_component_touches_boundary": False,
                    "degenerate_component_repair_attempted": False,
                    "degenerate_component_repair_accepted": False,
                })
                salvaged_record = dict(repaired_record)
                for record in (raw_record, repaired_record, salvaged_record):
                    record["region_remesh_seconds"] = 0.0
                    record["region_total_seconds"] = 0.0
                print(f"  [ERROR] {exc}")
            raw_summary_records.append(raw_record)
            repaired_summary_records.append(repaired_record)
            salvaged_summary_records.append(salvaged_record)

    raw_summary = pd.DataFrame(raw_summary_records)
    repaired_summary = pd.DataFrame(repaired_summary_records)
    salvaged_summary = pd.DataFrame(salvaged_summary_records)
    raw_summary_path = summary_dir / "raw" / "qc_visualization_summary.csv"
    repaired_summary_path = summary_dir / "repaired" / "qc_visualization_summary.csv"
    salvaged_summary_path = summary_dir / "salvaged" / "qc_visualization_summary.csv"
    raw_summary.to_csv(raw_summary_path, index=False)
    repaired_summary.to_csv(repaired_summary_path, index=False)
    salvaged_summary.to_csv(salvaged_summary_path, index=False)
    print(f"[QC] Raw summary saved: {raw_summary_path}")
    print(pd.crosstab(raw_summary["sample_tag"], raw_summary["status"]).to_string())
    print(f"[QC] Repaired summary saved: {repaired_summary_path}")
    print(pd.crosstab(repaired_summary["sample_tag"], repaired_summary["status"]).to_string())
    print(f"[QC] Salvaged summary saved: {salvaged_summary_path}")
    print(pd.crosstab(salvaged_summary["sample_tag"], salvaged_summary["status"]).to_string())


def _discover_sample_tags(data_dir: Path) -> list[str]:
    mesh_dir = data_dir / "clean_mesh"
    if not mesh_dir.exists():
        return []
    return sorted(path.stem for path in mesh_dir.glob("*.ply"))


def summary_output_root(out_dir: Path, summary_dir: Path | None) -> Path:
    """Return the QC summary root without changing legacy default output paths."""
    return Path(summary_dir) if summary_dir is not None else Path(out_dir)


def _split_sample_tag(sample_tag: str) -> tuple[str, str]:
    return split_sample_tag(sample_tag)


def figure_layers_for_mode(mode: str, repaired_status: str) -> set[str]:
    """Return the output layers whose Region QC PNGs should be rendered."""
    if mode == "all":
        return {"salvaged"}
    if mode == "repaired-fail" and repaired_status.upper() == "FAIL":
        return {"salvaged"}
    return set()


if __name__ == "__main__":
    main()
