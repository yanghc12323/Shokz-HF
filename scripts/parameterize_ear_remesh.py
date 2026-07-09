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

from ear_param.io_utils import load_landmarks, load_mesh, read_csv_robust
from ear_param.remesh import (
    build_region_remesh,
    build_region_remesh_mesh,
    classify_remesh_qc_status,
    compute_region_feature_values,
)


def _expected_point_count(resolution: int) -> int:
    return (resolution + 1) * (resolution + 2) // 2


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
        default="output/parameterized_points",
        help="Output directory for points/faces/features/QC CSV files.",
    )
    parser.add_argument(
        "--mesh_out_dir",
        default="output/remesh",
        help="Output directory for remesh PLY files.",
    )

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

    sample_tag = f"{args.sample_id}_{args.side}"
    all_points: list[pd.DataFrame] = []
    all_faces: list[pd.DataFrame] = []
    feature_records: list[dict] = []
    qc_records: list[dict] = []
    global_point_id = 0
    mesh_out_dir = Path(args.mesh_out_dir) / sample_tag
    mesh_out_dir.mkdir(parents=True, exist_ok=True)

    for _, row in regions.iterrows():
        region = row.to_dict()
        rid = str(region["region_id"])
        rname = str(region["region_name"])

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

            print(
                f"  -> points={n_samples} (expected {n_expected}), "
                f"unmapped={n_unmapped}, flipped={n_flipped}, "
                f"degenerate={n_degenerate}, patch_faces={patch_face_count}, "
                f"remesh_faces={n_remesh_faces}, status={status}"
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
        pd.concat(all_faces, ignore_index=True).to_csv(faces_path, index=False)
        print(f"[Remesh] Faces saved: {faces_path}")

    if feature_records:
        features_path = out_dir / f"{sample_tag}_region_features.csv"
        pd.DataFrame(feature_records).to_csv(features_path, index=False)
        print(f"[Remesh] Region features saved: {features_path}")

    qc_path = out_dir / f"{sample_tag}_remesh_qc.csv"
    pd.DataFrame(qc_records).to_csv(qc_path, index=False)
    print(f"[Remesh] QC saved: {qc_path}")

    qc_df = pd.DataFrame(qc_records)
    pass_c = int((qc_df["status"] == "PASS").sum())
    warn_c = int((qc_df["status"] == "WARNING").sum())
    fail_c = int((qc_df["status"] == "FAIL").sum())
    print(f"\n[Remesh] Done: PASS={pass_c} WARNING={warn_c} FAIL={fail_c}")


if __name__ == "__main__":
    main()

