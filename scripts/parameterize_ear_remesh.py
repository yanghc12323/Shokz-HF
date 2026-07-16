#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Command-line entry for patch-based ear remesh.

Example for the current T001 test data:
  python scripts/parameterize_ear_remesh.py \
    --sample_id T001 --side L \
    --mesh data/clean_mesh/T001_L.ply \
    --landmarks data/landmarks/T001_L_landmarks.csv \
    --regions config/region_table.csv \
    --out_dir output/parameterized_points

The current T001 source file names still contain "R", but the data is a left
ear, so the recommended side tag for this sample is L.
"""

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
from ear_param.events import JsonlEventWriter

from ear_param.io_utils import load_landmarks, load_mesh, read_csv_robust
from ear_param.remesh import (
    build_region_remesh,
    build_region_remesh_mesh,
    classify_remesh_qc_status,
    compute_region_feature_values,
    repair_unmapped_samples,
)


def _expected_point_count(resolution: int) -> int:
    return (resolution + 1) * (resolution + 2) // 2


def build_sample_status_summary(qc_dir: Path) -> pd.DataFrame:
    """Build PASS/WARNING/FAIL counts for every sample QC file in a directory."""
    records: list[dict[str, object]] = []
    for qc_path in sorted(Path(qc_dir).glob("*_remesh_qc.csv")):
        qc_df = pd.read_csv(qc_path)
        if qc_df.empty or "status" not in qc_df.columns:
            continue
        sample_tag = _sample_tag_from_qc(qc_path, qc_df)
        counts = qc_df["status"].value_counts()
        records.append({
            "sample_tag": sample_tag,
            "PASS": int(counts.get("PASS", 0)),
            "WARNING": int(counts.get("WARNING", 0)),
            "FAIL": int(counts.get("FAIL", 0)),
            "TOTAL": int(len(qc_df)),
        })
    return pd.DataFrame(records, columns=["sample_tag", "PASS", "WARNING", "FAIL", "TOTAL"])


def _sample_tag_from_qc(qc_path: Path, qc_df: pd.DataFrame) -> str:
    if {"sample_id", "side"}.issubset(qc_df.columns) and not qc_df.empty:
        sample_id = str(qc_df["sample_id"].iloc[0])
        side = str(qc_df["side"].iloc[0])
        return f"{sample_id}_{side}"
    return qc_path.name.replace("_remesh_qc.csv", "")


def _print_sample_status_summary(label: str, qc_dir: Path) -> None:
    summary = build_sample_status_summary(qc_dir)
    print(f"\n[Remesh] {label} sample summary:")
    if summary.empty:
        print("  (no QC files found)")
        return
    print(summary.to_string(index=False))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Patch-based 3D ear remesh pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python scripts/parameterize_ear_remesh.py \\
      --sample_id T001 --side L \\
      --mesh data/clean_mesh/T001_L.ply \\
      --landmarks data/landmarks/T001_L_landmarks.csv \\
      --regions config/region_table.csv \\
      --out_dir output/parameterized_points
        """,
    )

    parser.add_argument("--sample_id", required=True, help="Sample ID, e.g. T001.")
    parser.add_argument("--side", default="R", help="Ear side tag: R or L. Default: R.")
    parser.add_argument("--mesh", required=True, help="Input mesh path (.ply).")
    parser.add_argument("--landmarks", required=True, help="Input landmark CSV path.")
    parser.add_argument(
        "--regions",
        default="config/region_table.csv",
        help="Region table CSV path. Default: config/region_table.csv.",
    )
    parser.add_argument(
        "--out_dir",
        default="output/parameterized_points_r24/raw",
        help="Output directory for raw points/faces/features/QC CSV files.",
    )
    parser.add_argument(
        "--mesh_out_dir",
        default="output/remesh_r24/raw",
        help="Output directory for raw PASS remesh PLY files.",
    )
    parser.add_argument(
        "--repaired_out_dir",
        default="output/parameterized_points_r24/repaired",
        help="Output directory for repaired points/faces/QC CSV files.",
    )
    parser.add_argument(
        "--repaired_mesh_out_dir",
        default="output/remesh_r24/repaired",
        help="Output directory for repaired/exportable remesh PLY files.",
    )
    parser.add_argument(
        "--salvaged_out_dir",
        default="output/parameterized_points_r24/salvaged",
        help="Output directory for conservative raw-FAIL salvage CSV files.",
    )
    parser.add_argument(
        "--salvaged_mesh_out_dir",
        default="output/remesh_r24/salvaged",
        help="Output directory for conservative raw-FAIL salvage PLY files.",
    )
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
    parser.add_argument("--event-log", help="Optional desktop JSONL event log.")

    args = parser.parse_args()

    print(f"[Remesh] Loading mesh: {args.mesh}")
    mesh = load_mesh(Path(args.mesh))
    print(f"  -> vertices={len(mesh.vertices)}, faces={len(mesh.faces)}")

    print(f"[Remesh] Loading landmarks: {args.landmarks}")
    landmarks = load_landmarks(Path(args.landmarks))
    print(f"  -> landmarks={len(landmarks)}, ids={list(landmarks.index)}")

    regions_path = Path(args.regions)
    if not regions_path.exists():
        print(f"[ERROR] Region table does not exist: {regions_path}")
        sys.exit(1)
    regions = read_csv_robust(regions_path)
    print(f"[Remesh] Loaded region table: {len(regions)} regions")
    for _, r in regions.iterrows():
        n_expected = _expected_point_count(int(r["resolution"]))
        print(
            f"  {r['region_id']}: {r['region_name']}, "
            f"lm=({r['lm_a']},{r['lm_b']},{r['lm_c']}), "
            f"resolution={r['resolution']}, expected_points={n_expected}"
        )

    required_landmarks: set[str] = set()
    for _, row in regions.iterrows():
        required_landmarks.update([str(row["lm_a"]), str(row["lm_b"]), str(row["lm_c"])])
    missing = required_landmarks - set(landmarks.index)
    if missing:
        print(f"[ERROR] Missing landmarks: {sorted(missing)}")
        print(f"  required: {sorted(required_landmarks)}")
        print(f"  actual: {sorted(landmarks.index)}")
        sys.exit(1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    repaired_out_dir = Path(args.repaired_out_dir)
    repaired_out_dir.mkdir(parents=True, exist_ok=True)
    salvaged_out_dir = Path(args.salvaged_out_dir)
    salvaged_out_dir.mkdir(parents=True, exist_ok=True)

    sample_tag = f"{args.sample_id}_{args.side}"
    event_writer = JsonlEventWriter(Path(args.event_log)) if args.event_log else None
    all_points: list[pd.DataFrame] = []
    all_repaired_points: list[pd.DataFrame] = []
    all_salvaged_points: list[pd.DataFrame] = []
    all_faces: list[pd.DataFrame] = []
    feature_records: list[dict] = []
    qc_records: list[dict] = []
    repaired_qc_records: list[dict] = []
    salvaged_qc_records: list[dict] = []
    global_point_id = 0
    mesh_out_dir = Path(args.mesh_out_dir) / sample_tag
    mesh_out_dir.mkdir(parents=True, exist_ok=True)
    repaired_mesh_out_dir = Path(args.repaired_mesh_out_dir) / sample_tag
    repaired_mesh_out_dir.mkdir(parents=True, exist_ok=True)
    salvaged_mesh_out_dir = Path(args.salvaged_mesh_out_dir) / sample_tag
    salvaged_mesh_out_dir.mkdir(parents=True, exist_ok=True)

    for _, row in regions.iterrows():
        region = row.to_dict()
        rid = str(region["region_id"])
        rname = str(region["region_name"])
        if event_writer:
            event_writer.emit("region_started", sample_tag=sample_tag, region_id=rid, region_name=rname, total_regions=len(regions))

        print(f"\n[Remesh] Processing region {rid} ({rname})...")

        try:
            result = build_region_remesh(mesh, landmarks, region)

            region_start_id = global_point_id
            n_samples = len(result.sample_points_3d)
            n_expected = _expected_point_count(int(region["resolution"]))
            n_unmapped = result.located_samples.unmapped_count
            n_flipped = result.parameterization.flipped_face_count
            n_degenerate = result.parameterization.degenerate_face_count
            patch_face_count = len(result.patch.face_ids)
            remesh_faces = result.template.faces
            n_remesh_faces = len(remesh_faces)

            labels = [f"{sample_tag}_P{global_point_id + i:05d}" for i in range(n_samples)]
            df_region = pd.DataFrame({
                "point_id": labels,
                "sample_id": args.sample_id,
                "side": args.side,
                "region_id": rid,
                "region_name": rname,
                "region_point_id": list(range(n_samples)),
                "lambda_a": result.template.barycentric[:, 0],
                "lambda_b": result.template.barycentric[:, 1],
                "lambda_c": result.template.barycentric[:, 2],
                "u": result.template.uv[:, 0],
                "v": result.template.uv[:, 1],
                "source_face_index": result.located_samples.face_indices,
                "is_unmapped": result.located_samples.unmapped_mask,
                "x": result.sample_points_3d[:, 0],
                "y": result.sample_points_3d[:, 1],
                "z": result.sample_points_3d[:, 2],
            })
            all_points.append(df_region)
            global_point_id += n_samples

            repaired = repair_unmapped_samples(result)
            salvaged = repair_unmapped_samples(
                result,
                allow_raw_fail_repair=True,
                max_raw_fail_repair_unmapped_ratio=args.max_salvage_unmapped_ratio,
                max_raw_fail_repair_degenerate_ratio=args.max_salvage_degenerate_ratio,
            )
            repaired_is_unmapped = ~pd.notna(repaired.points_3d).all(axis=1)
            df_repaired_region = df_region.copy()
            df_repaired_region["raw_x"] = df_region["x"]
            df_repaired_region["raw_y"] = df_region["y"]
            df_repaired_region["raw_z"] = df_region["z"]
            df_repaired_region["raw_is_unmapped"] = df_region["is_unmapped"]
            df_repaired_region["x"] = repaired.points_3d[:, 0]
            df_repaired_region["y"] = repaired.points_3d[:, 1]
            df_repaired_region["z"] = repaired.points_3d[:, 2]
            df_repaired_region["is_unmapped"] = repaired_is_unmapped
            df_repaired_region["is_repaired"] = repaired.repaired_mask
            df_repaired_region["repair_method"] = repaired.repair_methods
            all_repaired_points.append(df_repaired_region)

            salvaged_is_unmapped = ~pd.notna(salvaged.points_3d).all(axis=1)
            df_salvaged_region = df_region.copy()
            df_salvaged_region["raw_x"] = df_region["x"]
            df_salvaged_region["raw_y"] = df_region["y"]
            df_salvaged_region["raw_z"] = df_region["z"]
            df_salvaged_region["raw_is_unmapped"] = df_region["is_unmapped"]
            df_salvaged_region["x"] = salvaged.points_3d[:, 0]
            df_salvaged_region["y"] = salvaged.points_3d[:, 1]
            df_salvaged_region["z"] = salvaged.points_3d[:, 2]
            df_salvaged_region["is_unmapped"] = salvaged_is_unmapped
            df_salvaged_region["is_repaired"] = salvaged.repaired_mask
            df_salvaged_region["repair_method"] = salvaged.repair_methods
            df_salvaged_region["salvage_attempted"] = salvaged.salvage_attempted
            df_salvaged_region["salvage_accepted"] = salvaged.salvage_accepted
            df_salvaged_region["salvage_rejection_reason"] = salvaged.salvage_rejection_reason
            df_salvaged_region["degenerate_ratio"] = salvaged.degenerate_ratio
            df_salvaged_region["degenerate_before"] = salvaged.degenerate_before
            df_salvaged_region["degenerate_after"] = salvaged.degenerate_after
            df_salvaged_region["degenerate_salvage_attempted"] = salvaged.degenerate_salvage_attempted
            df_salvaged_region["degenerate_salvage_accepted"] = salvaged.degenerate_salvage_accepted
            df_salvaged_region["degenerate_salvage_method"] = salvaged.degenerate_salvage_method
            df_salvaged_region["degenerate_salvage_rejection_reason"] = salvaged.degenerate_salvage_rejection_reason
            all_salvaged_points.append(df_salvaged_region)

            all_faces.append(pd.DataFrame({
                "sample_id": args.sample_id,
                "side": args.side,
                "region_id": rid,
                "region_name": rname,
                "face_id": list(range(n_remesh_faces)),
                "local_v0": remesh_faces[:, 0],
                "local_v1": remesh_faces[:, 1],
                "local_v2": remesh_faces[:, 2],
                "global_v0": remesh_faces[:, 0] + region_start_id,
                "global_v1": remesh_faces[:, 1] + region_start_id,
                "global_v2": remesh_faces[:, 2] + region_start_id,
            }))

            feature_record = {
                "sample_id": args.sample_id,
                "side": args.side,
                "region_id": rid,
                "region_name": rname,
            }
            feature_record.update(compute_region_feature_values(
                landmarks,
                result.snapped_landmarks,
                str(region["lm_a"]),
                str(region["lm_b"]),
                str(region["lm_c"]),
            ))
            feature_records.append(feature_record)

            status = classify_remesh_qc_status(n_samples, n_unmapped, n_degenerate)

            mesh_path = mesh_out_dir / f"{rid}_remesh.ply"
            mesh_exported = False
            if status == "PASS":
                build_region_remesh_mesh(result).export(mesh_path)
                mesh_exported = True

            repaired_mesh_path = repaired_mesh_out_dir / f"{rid}_remesh_repaired.ply"
            repaired_mesh_exported = False
            if repaired.exportable:
                build_region_remesh_mesh(
                    result,
                    vertices_override=repaired.points_3d,
                ).export(repaired_mesh_path)
                repaired_mesh_exported = True

            salvaged_mesh_path = salvaged_mesh_out_dir / f"{rid}_remesh_salvaged.ply"
            salvaged_mesh_exported = False
            if salvaged.exportable:
                build_region_remesh_mesh(
                    result,
                    vertices_override=salvaged.points_3d,
                ).export(salvaged_mesh_path)
                salvaged_mesh_exported = True

            qc_records.append({
                "sample_id": args.sample_id,
                "side": args.side,
                "region_id": rid,
                "region_name": rname,
                "sample_point_count": n_samples,
                "expected_point_count": n_expected,
                "remesh_face_count": n_remesh_faces,
                "unmapped_count": n_unmapped,
                "flipped_faces": n_flipped,
                "degenerate_faces": n_degenerate,
                "patch_face_count": patch_face_count,
                "mesh_exported": mesh_exported,
                "mesh_path": str(mesh_path) if mesh_exported else "",
                "status": status,
            })
            repaired_qc_records.append({
                "sample_id": args.sample_id,
                "side": args.side,
                "region_id": rid,
                "region_name": rname,
                "sample_point_count": n_samples,
                "expected_point_count": n_expected,
                "remesh_face_count": n_remesh_faces,
                "raw_unmapped_count": n_unmapped,
                "raw_status": status,
                "repaired_unmapped_count": repaired.repaired_unmapped_count,
                "repair_count": repaired.repaired_count,
                "repair_applied": repaired.repaired_count > 0,
                "flipped_faces": n_flipped,
                "degenerate_faces": n_degenerate,
                "patch_face_count": patch_face_count,
                "mesh_exported": repaired_mesh_exported,
                "mesh_path": str(repaired_mesh_path) if repaired_mesh_exported else "",
                "status": repaired.status,
            })
            salvaged_qc_records.append({
                "sample_id": args.sample_id,
                "side": args.side,
                "region_id": rid,
                "region_name": rname,
                "sample_point_count": n_samples,
                "expected_point_count": n_expected,
                "remesh_face_count": n_remesh_faces,
                "raw_unmapped_count": n_unmapped,
                "raw_status": status,
                "salvaged_unmapped_count": salvaged.repaired_unmapped_count,
                "repair_count": salvaged.repaired_count,
                "repair_applied": salvaged.repaired_count > 0,
                "salvage_attempted": salvaged.salvage_attempted,
                "salvage_accepted": salvaged.salvage_accepted,
                "salvage_rejection_reason": salvaged.salvage_rejection_reason,
                "degenerate_ratio": salvaged.degenerate_ratio,
                "degenerate_before": salvaged.degenerate_before,
                "degenerate_after": salvaged.degenerate_after,
                "degenerate_salvage_attempted": salvaged.degenerate_salvage_attempted,
                "degenerate_salvage_accepted": salvaged.degenerate_salvage_accepted,
                "degenerate_salvage_method": salvaged.degenerate_salvage_method,
                "degenerate_salvage_rejection_reason": salvaged.degenerate_salvage_rejection_reason,
                "flipped_faces": n_flipped,
                "degenerate_faces": n_degenerate,
                "patch_face_count": patch_face_count,
                "mesh_exported": salvaged_mesh_exported,
                "mesh_path": str(salvaged_mesh_path) if salvaged_mesh_exported else "",
                "status": salvaged.status,
            })
            if event_writer:
                event_writer.emit("region_finished", sample_tag=sample_tag, region_id=rid, region_name=rname, raw_status=status, repaired_status=repaired.status, salvaged_status=salvaged.status, final_status=salvaged.status, reason=str(salvaged.salvage_rejection_reason or ""), completed_regions=len(qc_records), total_regions=len(regions))

            print(
                f"  -> points={n_samples} (expected {n_expected}), "
                f"unmapped={n_unmapped}, flipped={n_flipped}, "
                f"degenerate={n_degenerate}, patch_faces={patch_face_count}, "
                f"remesh_faces={n_remesh_faces}, raw_status={status}, "
                f"repaired_status={repaired.status}, repairs={repaired.repaired_count}, "
                f"salvaged_status={salvaged.status}, salvage_accepted={salvaged.salvage_accepted}, "
                f"degenerate={salvaged.degenerate_before}->{salvaged.degenerate_after}"
            )

        except Exception as exc:
            print(f"  [ERROR] Region {rid} failed: {exc}")
            qc_records.append({
                "sample_id": args.sample_id,
                "side": args.side,
                "region_id": rid,
                "region_name": rname,
                "sample_point_count": 0,
                "expected_point_count": 0,
                "remesh_face_count": 0,
                "unmapped_count": 0,
                "flipped_faces": 0,
                "degenerate_faces": 0,
                "patch_face_count": 0,
                "mesh_exported": False,
                "mesh_path": "",
                "status": "FAIL",
            })
            repaired_qc_records.append({
                "sample_id": args.sample_id,
                "side": args.side,
                "region_id": rid,
                "region_name": rname,
                "sample_point_count": 0,
                "expected_point_count": 0,
                "remesh_face_count": 0,
                "raw_unmapped_count": 0,
                "raw_status": "FAIL",
                "repaired_unmapped_count": 0,
                "repair_count": 0,
                "repair_applied": False,
                "flipped_faces": 0,
                "degenerate_faces": 0,
                "patch_face_count": 0,
                "mesh_exported": False,
                "mesh_path": "",
                "status": "FAIL",
            })
            salvaged_qc_records.append({
                "sample_id": args.sample_id,
                "side": args.side,
                "region_id": rid,
                "region_name": rname,
                "sample_point_count": 0,
                "expected_point_count": 0,
                "remesh_face_count": 0,
                "raw_unmapped_count": 0,
                "raw_status": "FAIL",
                "salvaged_unmapped_count": 0,
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
                "flipped_faces": 0,
                "degenerate_faces": 0,
                "patch_face_count": 0,
                "mesh_exported": False,
                "mesh_path": "",
                "status": "FAIL",
            })
            if event_writer:
                event_writer.emit("region_finished", sample_tag=sample_tag, region_id=rid, region_name=rname, raw_status="FAIL", repaired_status="FAIL", salvaged_status="FAIL", final_status="FAIL", reason=str(exc), completed_regions=len(qc_records), total_regions=len(regions))

    if all_points:
        df_all = pd.concat(all_points, ignore_index=True)
        points_path = out_dir / f"{sample_tag}_remesh_points.csv"
        df_all.to_csv(points_path, index=False)
        print(f"\n[Remesh] Points saved: {points_path}")
        print(f"  -> total_points={len(df_all)}")
    else:
        print("\n[WARNING] No sample points were produced")

    if all_faces:
        faces_path = out_dir / f"{sample_tag}_remesh_faces.csv"
        faces_df = pd.concat(all_faces, ignore_index=True)
        faces_df.to_csv(faces_path, index=False)
        print(f"[Remesh] Faces saved: {faces_path}")
        repaired_faces_path = repaired_out_dir / f"{sample_tag}_remesh_faces.csv"
        faces_df.to_csv(repaired_faces_path, index=False)
        print(f"[Remesh] Repaired faces saved: {repaired_faces_path}")
        salvaged_faces_path = salvaged_out_dir / f"{sample_tag}_remesh_faces.csv"
        faces_df.to_csv(salvaged_faces_path, index=False)
        print(f"[Remesh] Salvaged faces saved: {salvaged_faces_path}")

    if all_repaired_points:
        repaired_points_path = repaired_out_dir / f"{sample_tag}_remesh_points.csv"
        pd.concat(all_repaired_points, ignore_index=True).to_csv(repaired_points_path, index=False)
        print(f"[Remesh] Repaired points saved: {repaired_points_path}")

    if all_salvaged_points:
        salvaged_points_path = salvaged_out_dir / f"{sample_tag}_remesh_points.csv"
        pd.concat(all_salvaged_points, ignore_index=True).to_csv(salvaged_points_path, index=False)
        print(f"[Remesh] Salvaged points saved: {salvaged_points_path}")

    if feature_records:
        features_path = out_dir / f"{sample_tag}_region_features.csv"
        pd.DataFrame(feature_records).to_csv(features_path, index=False)
        print(f"[Remesh] Region features saved: {features_path}")

    qc_path = out_dir / f"{sample_tag}_remesh_qc.csv"
    pd.DataFrame(qc_records).to_csv(qc_path, index=False)
    print(f"[Remesh] QC saved: {qc_path}")
    repaired_qc_path = repaired_out_dir / f"{sample_tag}_remesh_qc.csv"
    pd.DataFrame(repaired_qc_records).to_csv(repaired_qc_path, index=False)
    print(f"[Remesh] Repaired QC saved: {repaired_qc_path}")
    salvaged_qc_path = salvaged_out_dir / f"{sample_tag}_remesh_qc.csv"
    pd.DataFrame(salvaged_qc_records).to_csv(salvaged_qc_path, index=False)
    print(f"[Remesh] Salvaged QC saved: {salvaged_qc_path}")

    qc_df = pd.DataFrame(qc_records)
    pass_c = int((qc_df["status"] == "PASS").sum())
    warn_c = int((qc_df["status"] == "WARNING").sum())
    fail_c = int((qc_df["status"] == "FAIL").sum())
    print(f"\n[Remesh] Done: PASS={pass_c} WARNING={warn_c} FAIL={fail_c}")
    repaired_qc_df = pd.DataFrame(repaired_qc_records)
    repaired_pass_c = int((repaired_qc_df["status"] == "PASS").sum())
    repaired_warn_c = int((repaired_qc_df["status"] == "WARNING").sum())
    repaired_fail_c = int((repaired_qc_df["status"] == "FAIL").sum())
    print(
        "[Remesh] Repaired Done: "
        f"PASS={repaired_pass_c} WARNING={repaired_warn_c} FAIL={repaired_fail_c}"
    )
    salvaged_qc_df = pd.DataFrame(salvaged_qc_records)
    salvaged_pass_c = int((salvaged_qc_df["status"] == "PASS").sum())
    salvaged_warn_c = int((salvaged_qc_df["status"] == "WARNING").sum())
    salvaged_fail_c = int((salvaged_qc_df["status"] == "FAIL").sum())
    print(
        "[Remesh] Salvaged Done: "
        f"PASS={salvaged_pass_c} WARNING={salvaged_warn_c} FAIL={salvaged_fail_c}"
    )
    _print_sample_status_summary("Raw", out_dir)
    _print_sample_status_summary("Repaired", repaired_out_dir)
    _print_sample_status_summary("Salvaged", salvaged_out_dir)


if __name__ == "__main__":
    main()

