#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate visual QC figures for patch-based remesh regions."""

from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd

from ear_param.io_utils import load_landmarks, load_mesh, read_csv_robust
from ear_param.qc_visualization import (
    classify_region_qc,
    classify_repaired_region_qc,
    save_region_qc_figure,
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
  python scripts/visualize_remesh_qc.py --samples T076_L T077_L
  python scripts/visualize_remesh_qc.py --samples T076_L T077_L --region_ids T001 T008
        """,
    )
    parser.add_argument("--samples", nargs="+", help="Sample tags, e.g. T076_L T077_L.")
    parser.add_argument("--region_ids", nargs="+", help="Optional subset of region IDs.")
    parser.add_argument("--data_dir", default="data", help="Input data directory.")
    parser.add_argument("--regions", default="config/region_table.csv", help="Region table CSV path.")
    parser.add_argument("--out_dir", default="output/qc_visualizations_r24", help="Output root directory.")
    parser.add_argument("--max_patch_faces", type=int, default=5000, help="Max patch faces drawn per 3D figure.")
    parser.add_argument(
        "--max_salvage_unmapped_ratio",
        type=float,
        default=0.35,
        help="Maximum raw unmapped ratio allowed for raw-FAIL salvage attempts.",
    )
    parser.add_argument(
        "--max_salvage_degenerate_ratio",
        type=float,
        default=0.015,
        help="Maximum raw degenerate-face ratio allowed for salvaged UV repair.",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    raw_out_dir = out_dir / "raw"
    repaired_out_dir = out_dir / "repaired"
    salvaged_out_dir = out_dir / "salvaged"
    raw_out_dir.mkdir(parents=True, exist_ok=True)
    repaired_out_dir.mkdir(parents=True, exist_ok=True)
    salvaged_out_dir.mkdir(parents=True, exist_ok=True)

    sample_tags = args.samples if args.samples else _discover_sample_tags(data_dir)
    if not sample_tags:
        raise SystemExit("No samples found. Use --samples or add meshes to data/clean_mesh.")

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
        mesh_path = data_dir / "clean_mesh" / f"{sample_tag}.ply"
        landmarks_path = data_dir / "landmarks" / f"{sample_tag}_landmarks.csv"
        print(f"[QC] Loading {sample_tag}")
        mesh = load_mesh(mesh_path)
        landmarks = load_landmarks(landmarks_path)

        for _, row in regions.iterrows():
            region = row.to_dict()
            region_id = str(region["region_id"])
            print(f"[QC] {sample_tag} {region_id}")
            raw_figure_path = raw_out_dir / sample_tag / f"{region_id}_qc.png"
            repaired_figure_path = repaired_out_dir / sample_tag / f"{region_id}_qc.png"
            salvaged_figure_path = salvaged_out_dir / sample_tag / f"{region_id}_qc.png"
            try:
                result = build_region_remesh(mesh, landmarks, region)
                raw_record = classify_region_qc(sample_tag, result)
                raw_record.update({
                    "sample_id": sample_id,
                    "side": side,
                    "figure_path": str(raw_figure_path),
                    "error": "",
                })
                save_region_qc_figure(
                    mesh,
                    result,
                    raw_figure_path,
                    max_patch_faces=args.max_patch_faces,
                )

                repaired = repair_unmapped_samples(result)
                repaired_record = classify_repaired_region_qc(sample_tag, result, repaired)
                repaired_record.update({
                    "sample_id": sample_id,
                    "side": side,
                    "figure_path": str(repaired_figure_path),
                    "error": "",
                })
                save_region_repaired_qc_figure(
                    mesh,
                    result,
                    repaired,
                    repaired_figure_path,
                    max_patch_faces=args.max_patch_faces,
                )

                salvaged = repair_unmapped_samples(
                    result,
                    allow_raw_fail_repair=True,
                    max_raw_fail_repair_unmapped_ratio=args.max_salvage_unmapped_ratio,
                    max_raw_fail_repair_degenerate_ratio=args.max_salvage_degenerate_ratio,
                )
                salvaged_record = classify_repaired_region_qc(sample_tag, result, salvaged)
                salvaged_record.update({
                    "sample_id": sample_id,
                    "side": side,
                    "figure_path": str(salvaged_figure_path),
                    "error": "",
                })
                save_region_repaired_qc_figure(
                    mesh,
                    result,
                    salvaged,
                    salvaged_figure_path,
                    max_patch_faces=args.max_patch_faces,
                )
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
                })
                salvaged_record = dict(repaired_record)
                print(f"  [ERROR] {exc}")
            raw_summary_records.append(raw_record)
            repaired_summary_records.append(repaired_record)
            salvaged_summary_records.append(salvaged_record)

    raw_summary = pd.DataFrame(raw_summary_records)
    repaired_summary = pd.DataFrame(repaired_summary_records)
    salvaged_summary = pd.DataFrame(salvaged_summary_records)
    raw_summary_path = raw_out_dir / "qc_visualization_summary.csv"
    repaired_summary_path = repaired_out_dir / "qc_visualization_summary.csv"
    salvaged_summary_path = salvaged_out_dir / "qc_visualization_summary.csv"
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


def _split_sample_tag(sample_tag: str) -> tuple[str, str]:
    if "_" not in sample_tag:
        raise ValueError(f"sample tag must look like <sample_id>_<side>: {sample_tag}")
    sample_id, side = sample_tag.rsplit("_", 1)
    return sample_id, side


if __name__ == "__main__":
    main()
