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
from ear_param.qc_visualization import classify_region_qc, save_region_qc_figure
from ear_param.remesh import build_region_remesh


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
    parser.add_argument("--out_dir", default="output/qc_visualizations", help="Output directory.")
    parser.add_argument("--max_patch_faces", type=int, default=5000, help="Max patch faces drawn per 3D figure.")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sample_tags = args.samples if args.samples else _discover_sample_tags(data_dir)
    if not sample_tags:
        raise SystemExit("No samples found. Use --samples or add meshes to data/clean_mesh.")

    regions = read_csv_robust(Path(args.regions))
    if args.region_ids:
        wanted = set(args.region_ids)
        regions = regions[regions["region_id"].astype(str).isin(wanted)].reset_index(drop=True)
    if regions.empty:
        raise SystemExit("No regions selected.")

    summary_records: list[dict[str, object]] = []
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
            figure_path = out_dir / sample_tag / f"{region_id}_qc.png"
            try:
                result = build_region_remesh(mesh, landmarks, region)
                record = classify_region_qc(sample_tag, result)
                record.update({
                    "sample_id": sample_id,
                    "side": side,
                    "figure_path": str(figure_path),
                    "error": "",
                })
                save_region_qc_figure(
                    mesh,
                    result,
                    figure_path,
                    max_patch_faces=args.max_patch_faces,
                )
            except Exception as exc:
                record = {
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
                print(f"  [ERROR] {exc}")
            summary_records.append(record)

    summary = pd.DataFrame(summary_records)
    summary_path = out_dir / "qc_visualization_summary.csv"
    summary.to_csv(summary_path, index=False)
    print(f"[QC] Summary saved: {summary_path}")
    print(pd.crosstab(summary["sample_tag"], summary["status"]).to_string())


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
