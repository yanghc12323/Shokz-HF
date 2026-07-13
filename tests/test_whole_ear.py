"""Tests for whole-ear topology assembly and boundary welding."""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import trimesh


def test_edge_repair_uses_a_separate_output_layer_and_rejects_the_baseline_dir():
    from scripts.build_whole_ear import _resolve_output_dir

    assert _resolve_output_dir(None, edge_repair_enabled=False) == Path(
        "output/whole_ear_r24/salvaged"
    )
    assert _resolve_output_dir(None, edge_repair_enabled=True) == Path(
        "output/whole_ear_r24/weld_repaired"
    )
    with pytest.raises(SystemExit, match="weld_repaired"):
        _resolve_output_dir(
            "output/whole_ear_r24/salvaged", edge_repair_enabled=True
        )

def _regions(*rows: tuple[str, str, str, str, int]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["region_id", "lm_a", "lm_b", "lm_c", "resolution"],
    )


def test_global_template_merges_reversed_shared_edge_and_landmark_corner():
    from ear_param.whole_ear import build_global_template

    regions = _regions(
        ("R1", "A", "B", "C", 2),
        ("R2", "B", "A", "D", 2),
        ("R3", "E", "A", "F", 2),
    )

    template = build_global_template(regions)

    assert template.local_to_global[("R1", 0)] == template.local_to_global[("R2", 5)]
    assert template.local_to_global[("R1", 3)] == template.local_to_global[("R2", 3)]
    assert template.local_to_global[("R1", 5)] == template.local_to_global[("R2", 0)]
    assert template.local_to_global[("R1", 0)] == template.local_to_global[("R3", 5)]
    assert template.n_global_vertices == 14


def test_global_template_rejects_resolution_mismatch_on_shared_edge():
    from ear_param.whole_ear import build_global_template

    regions = _regions(
        ("R1", "A", "B", "C", 2),
        ("R2", "B", "A", "D", 3),
    )

    with pytest.raises(ValueError, match="resolution"):
        build_global_template(regions)


def test_global_template_rejects_edge_used_by_more_than_two_regions():
    from ear_param.whole_ear import build_global_template

    regions = _regions(
        ("R1", "A", "B", "C", 2),
        ("R2", "B", "A", "D", 2),
        ("R3", "A", "B", "E", 2),
    )

    with pytest.raises(ValueError, match="non-manifold"):
        build_global_template(regions)


def _sample_tables():
    from ear_param.remesh import make_subdivision_template

    regions = _regions(
        ("R1", "A", "B", "C", 2),
        ("R2", "B", "A", "D", 2),
    )
    coordinates = {
        "R1": np.array([
            [0.20, 0.00, 0.00],
            [0.00, 0.50, 0.00],
            [0.00, 1.00, 0.00],
            [0.50, 0.00, 0.00],
            [0.50, 0.50, 0.00],
            [1.00, 0.00, 0.00],
        ]),
        "R2": np.array([
            [1.00, 0.00, 0.00],
            [1.00, -0.50, 0.00],
            [1.00, -1.00, 0.00],
            [0.50, 0.00, 0.00],
            [0.50, -0.50, 0.00],
            [0.00, 0.00, 0.00],
        ]),
    }
    point_rows = []
    for region_id, xyz in coordinates.items():
        for point_id, point in enumerate(xyz):
            repaired = region_id == "R1" and point_id == 0
            point_rows.append({
                "sample_id": "S1",
                "side": "L",
                "region_id": region_id,
                "region_point_id": point_id,
                "x": point[0],
                "y": point[1],
                "z": point[2],
                "raw_is_unmapped": repaired,
                "repair_method": "smooth_internal" if repaired else "mapped",
            })

    template_faces = make_subdivision_template(2).faces
    face_rows = []
    for region_id in ("R1", "R2"):
        for face_id, face in enumerate(template_faces):
            face_rows.append({
                "sample_id": "S1",
                "side": "L",
                "region_id": region_id,
                "face_id": face_id,
                "local_v0": face[0],
                "local_v1": face[1],
                "local_v2": face[2],
            })
    qc = pd.DataFrame([
        {"sample_id": "S1", "side": "L", "region_id": "R1", "status": "PASS"},
        {"sample_id": "S1", "side": "L", "region_id": "R2", "status": "PASS"},
    ])
    return regions, pd.DataFrame(point_rows), pd.DataFrame(face_rows), qc


def _warning_edge_fixture(
    *,
    raw_statuses: tuple[str, str] = ("WARNING", "WARNING"),
    resolution: int = 2,
    conflict_indices: tuple[int, ...] = (1,),
):
    """Create two regions with a repaired-only conflict on shared edge A-B."""
    from ear_param.remesh import make_subdivision_template
    from ear_param.whole_ear import build_global_template

    regions = _regions(
        ("R1", "A", "B", "C", resolution),
        ("R2", "B", "A", "D", resolution),
    )
    template = build_global_template(regions)
    subdivision = make_subdivision_template(resolution)
    landmark_positions = {
        "R1": np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.25, 1.0, 0.0]]),
        "R2": np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.75, -1.0, 0.0]]),
    }
    point_rows = []
    for region_id, landmarks in landmark_positions.items():
        xyz = subdivision.barycentric @ landmarks
        for point_id, point in enumerate(xyz):
            point_rows.append({
                "sample_id": "S1",
                "side": "L",
                "region_id": region_id,
                "region_point_id": point_id,
                "x": point[0],
                "y": point[1],
                "z": point[2],
                "raw_is_unmapped": False,
                "repair_method": "mapped",
            })
    points = pd.DataFrame(point_rows)
    shared = template.edge_members[template.edge_members["edge_id"] == "A__B"]
    for edge_index in (0, resolution):
        members = shared[shared["edge_index"] == edge_index]
        for member in members.itertuples(index=False):
            mask = (
                (points["region_id"] == member.region_id)
                & (points["region_point_id"] == member.region_point_id)
            )
            points.loc[mask, "raw_is_unmapped"] = True
            points.loc[mask, "repair_method"] = "landmark_vertex"
    for edge_index in conflict_indices:
        members = shared[shared["edge_index"] == edge_index].sort_values("region_id")
        for offset, member in enumerate(members.itertuples(index=False)):
            mask = (
                (points["region_id"] == member.region_id)
                & (points["region_point_id"] == member.region_point_id)
            )
            points.loc[mask, "z"] = 0.2 if offset == 0 else -0.2
            points.loc[mask, "raw_is_unmapped"] = True
            points.loc[mask, "repair_method"] = "smooth_near_vertex"

    face_rows = []
    for region_id in ("R1", "R2"):
        for face_id, face in enumerate(subdivision.faces):
            face_rows.append({
                "sample_id": "S1",
                "side": "L",
                "region_id": region_id,
                "face_id": face_id,
                "local_v0": face[0],
                "local_v1": face[1],
                "local_v2": face[2],
            })
    qc = pd.DataFrame([
        {
            "sample_id": "S1",
            "side": "L",
            "region_id": "R1",
            "status": "PASS",
            "raw_status": raw_statuses[0],
            "degenerate_faces": 0,
        },
        {
            "sample_id": "S1",
            "side": "L",
            "region_id": "R2",
            "status": "PASS",
            "raw_status": raw_statuses[1],
            "degenerate_faces": 0,
        },
    ])
    mesh = trimesh.Trimesh(
        vertices=np.array([[-1.0, -2.0, 0.0], [2.0, -2.0, 0.0], [0.5, 2.0, 0.0]]),
        faces=np.array([[0, 1, 2]]),
        process=False,
    )
    return template, points, pd.DataFrame(face_rows), qc, mesh


def test_whole_ear_uses_mapped_coordinate_without_treating_replacement_as_conflict():
    from ear_param.whole_ear import assemble_whole_ear, build_global_template

    regions, points, faces, qc = _sample_tables()
    template = build_global_template(regions)

    result = assemble_whole_ear(
        template,
        points,
        faces,
        qc,
        warning_mm=0.04,
        fail_mm=0.20,
    )

    global_a = template.local_to_global[("R1", 0)]
    selected_a = result.points.set_index("global_vertex_id").loc[global_a]
    np.testing.assert_allclose(selected_a[["x", "y", "z"]].to_numpy(float), [0.0, 0.0, 0.0])
    assert selected_a["chosen_region_id"] == "R2"
    edge = result.edge_qc.set_index("edge_id").loc["A__B"]
    assert edge["status"] == "PASS"
    assert edge["replacement_point_count"] == 1
    assert edge["max_replacement_distance_mm"] == pytest.approx(0.2)
    assert edge["max_conflict_distance_mm"] == pytest.approx(0.0)
    assert result.summary.loc[0, "status"] == "PASS"
    assert bool(result.summary.loc[0, "pca_ready"])


def test_whole_ear_faces_are_globally_indexed_and_pass_with_larger_tolerance():
    from ear_param.whole_ear import assemble_whole_ear, build_global_template

    regions, points, faces, qc = _sample_tables()
    result = assemble_whole_ear(
        build_global_template(regions),
        points,
        faces,
        qc,
        warning_mm=0.25,
        fail_mm=1.00,
    )

    assert len(result.points) == 9
    assert len(result.faces) == 8
    assert result.faces[["global_v0", "global_v1", "global_v2"]].to_numpy().max() == 8
    assert result.summary.loc[0, "status"] == "PASS"
    assert bool(result.summary.loc[0, "pca_ready"])


def test_whole_ear_fails_when_region_faces_are_incomplete():
    from ear_param.whole_ear import assemble_whole_ear, build_global_template

    regions, points, faces, qc = _sample_tables()
    faces = faces.drop(faces.index[-1]).reset_index(drop=True)

    result = assemble_whole_ear(build_global_template(regions), points, faces, qc)

    assert result.summary.loc[0, "status"] == "FAIL"
    assert not bool(result.summary.loc[0, "pca_ready"])
    assert result.summary.loc[0, "invalid_region_face_count"] == 1
    assert "invalid_region_faces" in result.summary.loc[0, "failure_reasons"]


def test_whole_ear_prefers_landmark_vertex_for_global_landmark_corner():
    from ear_param.whole_ear import assemble_whole_ear, build_global_template

    regions, points, faces, qc = _sample_tables()
    mask = (points["region_id"] == "R1") & (points["region_point_id"] == 0)
    points.loc[mask, "repair_method"] = "landmark_vertex"
    template = build_global_template(regions)

    result = assemble_whole_ear(template, points, faces, qc)

    global_a = template.local_to_global[("R1", 0)]
    selected = result.points.set_index("global_vertex_id").loc[global_a]
    assert selected["chosen_region_id"] == "R1"
    assert selected["chosen_repair_method"] == "landmark_vertex"


def test_whole_ear_rejects_non_pass_salvaged_region():
    from ear_param.whole_ear import assemble_whole_ear, build_global_template

    regions, points, faces, qc = _sample_tables()
    qc.loc[qc["region_id"] == "R2", "status"] = "FAIL"

    result = assemble_whole_ear(build_global_template(regions), points, faces, qc)

    assert result.summary.loc[0, "status"] == "FAIL"
    assert "non_pass_regions" in result.summary.loc[0, "failure_reasons"]


def test_whole_ear_fails_when_both_edge_copies_are_repaired_and_disagree():
    from ear_param.whole_ear import assemble_whole_ear, build_global_template

    regions, points, faces, qc = _sample_tables()
    for region_id in ("R1", "R2"):
        mask = (points["region_id"] == region_id) & (points["region_point_id"] == 3)
        points.loc[mask, "raw_is_unmapped"] = True
        points.loc[mask, "repair_method"] = "smooth_near_vertex"
    points.loc[
        (points["region_id"] == "R1") & (points["region_point_id"] == 3),
        "x",
    ] = 0.8

    result = assemble_whole_ear(
        build_global_template(regions),
        points,
        faces,
        qc,
        warning_mm=0.1,
        fail_mm=0.2,
    )

    edge = result.edge_qc.set_index("edge_id").loc["A__B"]
    assert edge["unresolved_point_count"] == 1
    assert edge["max_conflict_distance_mm"] == pytest.approx(0.3)
    assert edge["status"] == "FAIL"
    assert result.summary.loc[0, "status"] == "FAIL"


def test_edge_repair_promotes_one_warning_point_between_landmark_and_mapped_anchor():
    from ear_param.whole_ear import (
        assemble_whole_ear,
        repair_shared_edge_conflicts,
    )

    template, points, faces, qc, mesh = _warning_edge_fixture()
    baseline = assemble_whole_ear(template, points, faces, qc)

    repair = repair_shared_edge_conflicts(template, points, qc, mesh, baseline)
    final = assemble_whole_ear(template, repair.points, faces, qc)

    assert baseline.summary.loc[0, "status"] == "WARNING"
    assert repair.qc["applied"].sum() == 1
    assert final.summary.loc[0, "status"] == "PASS"
    assert bool(final.summary.loc[0, "pca_ready"])


def test_edge_repair_rejects_raw_fail_adjacent_region():
    from ear_param.whole_ear import (
        assemble_whole_ear,
        repair_shared_edge_conflicts,
    )

    template, points, faces, qc, mesh = _warning_edge_fixture(
        raw_statuses=("FAIL", "WARNING")
    )
    baseline = assemble_whole_ear(template, points, faces, qc)

    repair = repair_shared_edge_conflicts(template, points, qc, mesh, baseline)

    assert not repair.qc["applied"].any()
    assert "adjacent_raw_fail" in set(repair.qc["rejection_reason"])
    pd.testing.assert_frame_equal(repair.points, points)


def test_edge_repair_rejects_degenerate_adjacent_region():
    from ear_param.whole_ear import (
        assemble_whole_ear,
        repair_shared_edge_conflicts,
    )

    template, points, faces, qc, mesh = _warning_edge_fixture()
    qc.loc[qc["region_id"] == "R1", "degenerate_faces"] = 1
    baseline = assemble_whole_ear(template, points, faces, qc)

    repair = repair_shared_edge_conflicts(template, points, qc, mesh, baseline)

    assert not repair.qc["applied"].any()
    assert "adjacent_degenerate_face" in set(repair.qc["rejection_reason"])
    pd.testing.assert_frame_equal(repair.points, points)


def test_edge_repair_audits_non_finite_edge_candidate_without_attempting_repair():
    from ear_param.whole_ear import (
        assemble_whole_ear,
        repair_shared_edge_conflicts,
    )

    template, points, faces, qc, mesh = _warning_edge_fixture()
    mask = (points["region_id"] == "R1") & (points["region_point_id"] == 3)
    points.loc[mask, "x"] = np.nan
    baseline = assemble_whole_ear(template, points, faces, qc)

    repair = repair_shared_edge_conflicts(template, points, qc, mesh, baseline)

    audit = repair.qc.set_index("edge_index")
    assert baseline.summary.loc[0, "status"] == "FAIL"
    assert not audit.loc[1, "applied"]
    assert audit.loc[1, "rejection_reason"] == "non_finite_candidate"
    assert np.isnan(audit.loc[1, "pre_distance_mm"])
    pd.testing.assert_frame_equal(repair.points, points)


def test_edge_repair_rejects_run_longer_than_limit():
    from ear_param.whole_ear import (
        assemble_whole_ear,
        repair_shared_edge_conflicts,
    )

    template, points, faces, qc, mesh = _warning_edge_fixture(
        resolution=4,
        conflict_indices=(1, 2, 3),
    )
    baseline = assemble_whole_ear(template, points, faces, qc)

    repair = repair_shared_edge_conflicts(template, points, qc, mesh, baseline)

    assert not repair.qc["applied"].any()
    assert "conflict_run_too_long" in set(repair.qc["rejection_reason"])


def test_edge_repair_projects_interpolated_point_and_updates_both_region_copies():
    from ear_param.whole_ear import (
        assemble_whole_ear,
        repair_shared_edge_conflicts,
    )

    template, points, faces, qc, mesh = _warning_edge_fixture()
    baseline = assemble_whole_ear(template, points, faces, qc)

    repair = repair_shared_edge_conflicts(template, points, qc, mesh, baseline)
    changed = repair.points.query("repair_method == 'edge_coupled_interpolation'")

    assert len(changed) == 2
    np.testing.assert_allclose(
        changed[["x", "y", "z"]].iloc[0],
        changed[["x", "y", "z"]].iloc[1],
    )
    assert changed["z"].abs().max() == pytest.approx(0.0)
    assert repair.qc.loc[repair.qc["applied"], "projection_distance_mm"].notna().all()


def test_build_whole_ear_cli_exports_edge_repair_qc_in_separate_layer():
    template, points, faces, qc, mesh = _warning_edge_fixture()
    work_dir = Path(".test_artifacts") / "whole_ear_edge_repair_cli" / uuid4().hex
    input_dir = work_dir / "salvaged"
    mesh_dir = work_dir / "mesh"
    output_dir = work_dir / "weld_repaired"
    input_dir.mkdir(parents=True, exist_ok=True)
    mesh_dir.mkdir(parents=True, exist_ok=True)
    regions_path = work_dir / "regions.csv"
    _regions(
        ("R1", "A", "B", "C", 2),
        ("R2", "B", "A", "D", 2),
    ).to_csv(regions_path, index=False)
    points.to_csv(input_dir / "S1_L_remesh_points.csv", index=False)
    faces.to_csv(input_dir / "S1_L_remesh_faces.csv", index=False)
    qc.to_csv(input_dir / "S1_L_remesh_qc.csv", index=False)
    mesh.export(mesh_dir / "S1_L.ply")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_whole_ear.py",
            "--input_dir",
            str(input_dir),
            "--regions",
            str(regions_path),
            "--mesh_dir",
            str(mesh_dir),
            "--enable_edge_repair",
            "--out_dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert (output_dir / "S1_L_edge_repair_qc.csv").exists()
    summary = pd.read_csv(output_dir / "S1_L_weld_qc_summary.csv")
    assert summary.loc[0, "raw_weld_status"] == "WARNING"
    assert bool(summary.loc[0, "edge_repair_applied"])
    assert summary.loc[0, "status"] == "PASS"
    assert summary.loc[0, "input_layer"] == "weld_repaired"


def test_build_whole_ear_cli_exports_csv_ply_and_qc_figure():
    regions, points, faces, qc = _sample_tables()
    work_dir = Path(".test_artifacts") / "whole_ear_cli" / uuid4().hex
    input_dir = work_dir / "salvaged"
    output_dir = work_dir / "whole_ear"
    input_dir.mkdir(parents=True, exist_ok=True)
    regions_path = work_dir / "regions.csv"
    regions.to_csv(regions_path, index=False)
    points.to_csv(input_dir / "S1_L_remesh_points.csv", index=False)
    faces.to_csv(input_dir / "S1_L_remesh_faces.csv", index=False)
    qc.to_csv(input_dir / "S1_L_remesh_qc.csv", index=False)

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_whole_ear.py",
            "--input_dir",
            str(input_dir),
            "--regions",
            str(regions_path),
            "--out_dir",
            str(output_dir),
            "--weld_warning_mm",
            "0.25",
            "--weld_fail_mm",
            "1.0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert (output_dir / "global_template_manifest.csv").exists()
    assert (output_dir / "S1_L_whole_ear_points.csv").exists()
    assert (output_dir / "S1_L_whole_ear_faces.csv").exists()
    assert (output_dir / "S1_L_whole_ear_welded.ply").exists()
    assert (output_dir / "S1_L_weld_qc_edges.csv").exists()
    assert (output_dir / "S1_L_weld_qc_vertices.csv").exists()
    assert (output_dir / "S1_L_weld_qc_summary.csv").exists()
    assert (output_dir / "S1_L_weld_qc.png").exists()
    assert "S1_L" in completed.stdout
