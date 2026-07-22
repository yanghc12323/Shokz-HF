#!/usr/bin/env python3
"""Build fixed-topology whole ears from W2 salvaged region outputs."""

from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np
import pandas as pd
import trimesh

from ear_param.whole_ear import (
    WholeEarResult,
    assemble_whole_ear,
    build_global_template,
    repair_shared_edge_conflicts,
)


_BASELINE_OUTPUT_DIR = Path("output/whole_ear_r24/salvaged")
_REPAIRED_OUTPUT_DIR = Path("output/whole_ear_r24/weld_repaired")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build whole-ear welded meshes and boundary QC from salvaged W2 outputs."
    )
    parser.add_argument(
        "--input_dir",
        default="output/parameterized_points_r24/salvaged",
        help="Directory containing salvaged points/faces/QC CSV files.",
    )
    parser.add_argument("--regions", default="config/region_table.csv")
    parser.add_argument(
        "--out_dir",
        help=(
            "Output directory. Defaults to the immutable salvaged baseline, or to "
            "weld_repaired when --enable_edge_repair is set."
        ),
    )
    parser.add_argument("--samples", nargs="+", help="Optional sample tags, e.g. MQ_S013L.")
    parser.add_argument("--weld_warning_mm", type=float, default=0.25)
    parser.add_argument("--weld_fail_mm", type=float, default=1.0)
    parser.add_argument("--mesh_dir", default="data/clean_mesh")
    parser.add_argument(
        "--enable_edge_repair",
        action="store_true",
        help="Create a conservative post-salvage shared-edge repair layer.",
    )
    parser.add_argument("--edge_repair_max_run_length", type=int, default=2)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    out_dir = _resolve_output_dir(args.out_dir, args.enable_edge_repair)
    out_dir.mkdir(parents=True, exist_ok=True)

    regions = pd.read_csv(args.regions)
    template = build_global_template(regions)
    template.manifest.to_csv(out_dir / "global_template_manifest.csv", index=False)
    template.edges.to_csv(out_dir / "global_template_edges.csv", index=False)
    template.edge_members.to_csv(out_dir / "global_template_edge_members.csv", index=False)

    sample_tags = args.samples or _discover_sample_tags(input_dir)
    if not sample_tags:
        raise SystemExit(f"No *_remesh_points.csv files found in {input_dir}")

    summaries: list[pd.DataFrame] = []
    for sample_tag in sample_tags:
        print(f"[WholeEar] {sample_tag}")
        points = pd.read_csv(input_dir / f"{sample_tag}_remesh_points.csv")
        faces = pd.read_csv(input_dir / f"{sample_tag}_remesh_faces.csv")
        qc = pd.read_csv(input_dir / f"{sample_tag}_remesh_qc.csv")
        baseline = assemble_whole_ear(
            template,
            points,
            faces,
            qc,
            warning_mm=args.weld_warning_mm,
            fail_mm=args.weld_fail_mm,
        )
        result = baseline
        repair_qc: pd.DataFrame | None = None
        if args.enable_edge_repair:
            mesh_path = Path(args.mesh_dir) / f"{sample_tag}.ply"
            if not mesh_path.exists():
                raise SystemExit(f"Original mesh not found for edge repair: {mesh_path}")
            mesh = trimesh.load(mesh_path, force="mesh", process=False)
            repair = repair_shared_edge_conflicts(
                template,
                points,
                qc,
                mesh,
                baseline,
                warning_mm=args.weld_warning_mm,
                fail_mm=args.weld_fail_mm,
                max_run_length=args.edge_repair_max_run_length,
            )
            result = assemble_whole_ear(
                template,
                repair.points,
                faces,
                qc,
                warning_mm=args.weld_warning_mm,
                fail_mm=args.weld_fail_mm,
            )
            result = _with_edge_repair_summary(result, baseline, repair.qc)
            repair_qc = repair.qc
        _export_sample(sample_tag, result, template, out_dir, repair_qc)
        summaries.append(result.summary)

    summary = pd.concat(summaries, ignore_index=True)
    summary.to_csv(out_dir / "whole_ear_weld_summary.csv", index=False)
    print("\n[WholeEar] Batch summary:")
    display_columns = [
        "sample_id",
        "side",
        "status",
        "pca_ready",
        "pass_edge_count",
        "warning_edge_count",
        "fail_edge_count",
        "max_conflict_distance_mm",
        "max_replacement_distance_mm",
        "replacement_point_count",
    ]
    if args.enable_edge_repair:
        display_columns[2:2] = [
            "raw_weld_status",
            "edge_repair_applied",
            "edge_repair_count",
        ]
    print(summary[display_columns].to_string(index=False))


def _resolve_output_dir(
    value: str | None,
    edge_repair_enabled: bool,
) -> Path:
    """Select a layer-specific output path without allowing baseline overwrite."""
    if value is None:
        return _REPAIRED_OUTPUT_DIR if edge_repair_enabled else _BASELINE_OUTPUT_DIR

    output_dir = Path(value)
    if edge_repair_enabled and output_dir.resolve() == _BASELINE_OUTPUT_DIR.resolve():
        raise SystemExit(
            "--enable_edge_repair must write to a separate layer such as "
            "output/whole_ear_r24/weld_repaired, not the salvaged baseline."
        )
    return output_dir


def _discover_sample_tags(input_dir: Path) -> list[str]:
    suffix = "_remesh_points.csv"
    return sorted(path.name.removesuffix(suffix) for path in input_dir.glob(f"*{suffix}"))


def _export_sample(
    sample_tag: str,
    result: WholeEarResult,
    template,
    out_dir: Path,
    repair_qc: pd.DataFrame | None = None,
) -> None:
    result.points.to_csv(out_dir / f"{sample_tag}_whole_ear_points.csv", index=False)
    result.faces.to_csv(out_dir / f"{sample_tag}_whole_ear_faces.csv", index=False)
    result.edge_qc.to_csv(out_dir / f"{sample_tag}_weld_qc_edges.csv", index=False)
    result.vertex_qc.to_csv(out_dir / f"{sample_tag}_weld_qc_vertices.csv", index=False)
    result.summary.to_csv(out_dir / f"{sample_tag}_weld_qc_summary.csv", index=False)
    if repair_qc is not None:
        audit = repair_qc.copy()
        audit.insert(0, "side", str(result.summary.loc[0, "side"]))
        audit.insert(0, "sample_id", str(result.summary.loc[0, "sample_id"]))
        audit.to_csv(out_dir / f"{sample_tag}_edge_repair_qc.csv", index=False)

    vertices = result.points[["x", "y", "z"]].to_numpy(dtype=float)
    faces = result.faces[["global_v0", "global_v1", "global_v2"]].to_numpy(dtype=int)
    if np.isfinite(vertices).all() and len(faces):
        trimesh.Trimesh(vertices=vertices, faces=faces, process=False).export(
            out_dir / f"{sample_tag}_whole_ear_welded.ply"
        )
    _save_weld_qc_figure(
        sample_tag,
        result,
        template,
        out_dir / f"{sample_tag}_weld_qc.png",
        repair_qc,
    )


def _save_weld_qc_figure(
    sample_tag: str,
    result: WholeEarResult,
    template,
    output_path: Path,
    repair_qc: pd.DataFrame | None = None,
) -> None:
    vertices = result.points[["x", "y", "z"]].to_numpy(dtype=float)
    faces = result.faces[["global_v0", "global_v1", "global_v2"]].to_numpy(dtype=int)
    fig = plt.figure(figsize=(11, 8))
    axis = fig.add_subplot(111, projection="3d")
    if np.isfinite(vertices).all() and len(faces):
        mesh = Poly3DCollection(
            vertices[faces],
            facecolor="#c7d5df",
            edgecolor="#71808a",
            linewidth=0.12,
            alpha=0.72,
        )
        axis.add_collection3d(mesh)

    point_lookup = result.points.set_index("global_vertex_id")
    color_by_status = {"PASS": "#238636", "WARNING": "#d29922", "FAIL": "#cf222e"}
    for edge in result.edge_qc.itertuples(index=False):
        ids = (
            template.edge_members[template.edge_members["edge_id"] == edge.edge_id]
            .sort_values("edge_index")
            .drop_duplicates("edge_index")["global_vertex_id"]
            .to_numpy(dtype=int)
        )
        xyz = point_lookup.loc[ids, ["x", "y", "z"]].to_numpy(dtype=float)
        if np.isfinite(xyz).all():
            axis.plot(
                xyz[:, 0],
                xyz[:, 1],
                xyz[:, 2],
                color=color_by_status[str(edge.status)],
                linewidth=2.3,
            )

    if repair_qc is not None and not repair_qc.empty:
        point_lookup = result.points.set_index("global_vertex_id")
        for row in repair_qc.itertuples(index=False):
            member = template.edge_members[
                (template.edge_members["edge_id"] == row.edge_id)
                & (template.edge_members["edge_index"] == row.edge_index)
            ].iloc[0]
            xyz = point_lookup.loc[int(member.global_vertex_id), ["x", "y", "z"]]
            color = "#00bcd4" if row.applied else "#d946ef"
            axis.scatter(xyz["x"], xyz["y"], xyz["z"], color=color, s=34, depthshade=False)

    status = str(result.summary.loc[0, "status"])
    raw_status = str(result.summary.loc[0, "raw_weld_status"]) if "raw_weld_status" in result.summary else status
    conflict = float(result.summary.loc[0, "max_conflict_distance_mm"])
    replacement = float(result.summary.loc[0, "max_replacement_distance_mm"])
    axis.set_title(
        f"{sample_tag} whole-ear weld QC | raw={raw_status} -> final={status} | "
        f"conflict={conflict:.4f} mm | replacement={replacement:.4f} mm"
    )
    axis.set_xlabel("X")
    axis.set_ylabel("Y")
    axis.set_zlabel("Z")
    _set_axes_equal(axis, vertices)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _with_edge_repair_summary(
    result: WholeEarResult,
    baseline: WholeEarResult,
    repair_qc: pd.DataFrame,
) -> WholeEarResult:
    summary = result.summary.copy()
    summary["input_layer"] = "weld_repaired"
    summary["raw_weld_status"] = str(baseline.summary.loc[0, "status"])
    summary["raw_weld_pca_ready"] = bool(baseline.summary.loc[0, "pca_ready"])
    summary["edge_repair_attempted"] = not repair_qc.empty
    summary["edge_repair_applied"] = bool(repair_qc["applied"].any()) if not repair_qc.empty else False
    summary["edge_repair_count"] = int(repair_qc["applied"].sum()) if not repair_qc.empty else 0
    summary["edge_repair_rejected_count"] = (
        int((~repair_qc["applied"]).sum()) if not repair_qc.empty else 0
    )
    return WholeEarResult(
        result.points,
        result.faces,
        result.edge_qc,
        result.vertex_qc,
        summary,
    )


def _set_axes_equal(axis, vertices: np.ndarray) -> None:
    finite = vertices[np.isfinite(vertices).all(axis=1)]
    if not len(finite):
        return
    center = (finite.min(axis=0) + finite.max(axis=0)) / 2.0
    radius = max(float(np.ptp(finite, axis=0).max()) / 2.0, 1e-6)
    axis.set_xlim(center[0] - radius, center[0] + radius)
    axis.set_ylim(center[1] - radius, center[1] + radius)
    axis.set_zlim(center[2] - radius, center[2] + radius)


if __name__ == "__main__":
    main()
