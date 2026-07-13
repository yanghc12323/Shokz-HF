"""Whole-ear topology and boundary-weld utilities.

The global template is coordinate independent: local subdivision points are
identified by region and merged only through shared anatomical landmarks and
landmark-defined edges.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import trimesh

from ear_param.remesh import make_subdivision_template


LocalPoint = tuple[str, int]


@dataclass(frozen=True)
class GlobalTemplate:
    """Fixed whole-ear topology shared by every sample."""

    manifest: pd.DataFrame
    edges: pd.DataFrame
    edge_members: pd.DataFrame
    local_to_global: dict[LocalPoint, int]

    @property
    def n_global_vertices(self) -> int:
        return len(set(self.local_to_global.values()))


class _UnionFind:
    def __init__(self, items: list[LocalPoint]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: LocalPoint) -> LocalPoint:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: LocalPoint, right: LocalPoint) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def build_global_template(regions: pd.DataFrame) -> GlobalTemplate:
    """Build stable global vertex identities from a region definition table."""
    required = {"region_id", "lm_a", "lm_b", "lm_c", "resolution"}
    missing = required.difference(regions.columns)
    if missing:
        raise ValueError(f"region table missing columns: {sorted(missing)}")

    table = regions.loc[:, list(required)].copy()
    table["region_id"] = table["region_id"].astype(str)
    if table["region_id"].duplicated().any():
        raise ValueError("region_id values must be unique")

    records: list[dict[str, object]] = []
    edge_uses: dict[str, list[dict[str, object]]] = {}
    corner_uses: dict[str, list[LocalPoint]] = {}
    all_points: list[LocalPoint] = []

    for region_order, row in table.reset_index(drop=True).iterrows():
        region_id = str(row["region_id"])
        landmarks = (str(row["lm_a"]), str(row["lm_b"]), str(row["lm_c"]))
        if len(set(landmarks)) != 3:
            raise ValueError(f"region {region_id} must use three distinct landmarks")
        resolution = int(row["resolution"])
        if resolution < 1:
            raise ValueError(f"region {region_id} resolution must be >= 1")

        lattice = _lattice_points(resolution)
        for point_id, weights in enumerate(lattice):
            local_point = (region_id, point_id)
            all_points.append(local_point)
            role, landmark_id, edge_id, edge_index = _point_topology(
                landmarks, weights, resolution
            )
            records.append({
                "region_order": region_order,
                "region_id": region_id,
                "region_point_id": point_id,
                "resolution": resolution,
                "topology_role": role,
                "landmark_id": landmark_id,
                "edge_id": edge_id,
                "edge_index": edge_index,
            })
            if landmark_id:
                corner_uses.setdefault(landmark_id, []).append(local_point)

        for first, second in ((0, 1), (1, 2), (2, 0)):
            lm_start, lm_end = sorted((landmarks[first], landmarks[second]))
            edge_id = _edge_id(lm_start, lm_end)
            edge_points = _edge_point_map(
                region_id,
                landmarks,
                lattice,
                first,
                second,
                lm_end,
            )
            edge_uses.setdefault(edge_id, []).append({
                "region_id": region_id,
                "resolution": resolution,
                "lm_start": lm_start,
                "lm_end": lm_end,
                "points": edge_points,
            })

    union_find = _UnionFind(all_points)
    for uses in corner_uses.values():
        for other in uses[1:]:
            union_find.union(uses[0], other)

    edge_records: list[dict[str, object]] = []
    for edge_id, uses in sorted(edge_uses.items()):
        if len(uses) > 2:
            raise ValueError(f"non-manifold edge {edge_id} is used by {len(uses)} regions")
        resolutions = {int(use["resolution"]) for use in uses}
        if len(resolutions) != 1:
            raise ValueError(f"shared edge {edge_id} has inconsistent resolution")
        resolution = resolutions.pop()
        for use in uses:
            if set(use["points"]) != set(range(resolution + 1)):
                raise ValueError(f"edge {edge_id} does not contain resolution + 1 points")
        if len(uses) == 2:
            for edge_index in range(resolution + 1):
                union_find.union(uses[0]["points"][edge_index], uses[1]["points"][edge_index])
        edge_records.append({
            "edge_id": edge_id,
            "lm_start": uses[0]["lm_start"],
            "lm_end": uses[0]["lm_end"],
            "resolution": resolution,
            "is_shared": len(uses) == 2,
            "regions": ";".join(str(use["region_id"]) for use in uses),
        })

    point_order = {point: index for index, point in enumerate(all_points)}
    groups: dict[LocalPoint, list[LocalPoint]] = {}
    for point in all_points:
        groups.setdefault(union_find.find(point), []).append(point)
    ordered_groups = sorted(groups.values(), key=lambda group: min(point_order[p] for p in group))
    local_to_global: dict[LocalPoint, int] = {}
    for global_id, group in enumerate(ordered_groups):
        for point in group:
            local_to_global[point] = global_id

    manifest = pd.DataFrame(records)
    manifest["global_vertex_id"] = [
        local_to_global[(str(row.region_id), int(row.region_point_id))]
        for row in manifest.itertuples()
    ]
    manifest["member_count"] = manifest.groupby("global_vertex_id")["global_vertex_id"].transform("size")
    manifest = manifest.sort_values(["global_vertex_id", "region_order", "region_point_id"])
    manifest = manifest.drop(columns="region_order").reset_index(drop=True)

    return GlobalTemplate(
        manifest=manifest,
        edges=pd.DataFrame(edge_records),
        edge_members=_build_edge_members(edge_uses, local_to_global),
        local_to_global=local_to_global,
    )


@dataclass(frozen=True)
class WholeEarResult:
    """One sample assembled on the fixed whole-ear topology."""

    points: pd.DataFrame
    faces: pd.DataFrame
    edge_qc: pd.DataFrame
    vertex_qc: pd.DataFrame
    summary: pd.DataFrame


@dataclass(frozen=True)
class EdgeRepairResult:
    """Local points after conservative shared-edge repair plus its audit table."""

    points: pd.DataFrame
    qc: pd.DataFrame


def assemble_whole_ear(
    template: GlobalTemplate,
    points: pd.DataFrame,
    faces: pd.DataFrame,
    qc: pd.DataFrame,
    *,
    warning_mm: float = 0.25,
    fail_mm: float = 1.0,
) -> WholeEarResult:
    """Assemble salvaged region outputs and quantify every shared boundary."""
    if warning_mm < 0 or fail_mm < warning_mm:
        raise ValueError("weld thresholds must satisfy 0 <= warning_mm <= fail_mm")
    _require_columns(points, {"region_id", "region_point_id", "x", "y", "z"}, "points")
    _require_columns(
        faces,
        {"region_id", "face_id", "local_v0", "local_v1", "local_v2"},
        "faces",
    )
    _require_columns(qc, {"region_id", "status"}, "qc")

    points = points.copy()
    points["region_id"] = points["region_id"].astype(str)
    points["region_point_id"] = points["region_point_id"].astype(int)
    faces = faces.copy()
    faces["region_id"] = faces["region_id"].astype(str)
    if points.duplicated(["region_id", "region_point_id"]).any():
        raise ValueError("points contain duplicate region_id + region_point_id rows")

    sample_id = _single_value(points, "sample_id", "unknown")
    side = _single_value(points, "side", "")
    expected_regions = set(template.manifest["region_id"].astype(str))
    point_regions = set(points["region_id"])
    qc_by_region = qc.assign(region_id=qc["region_id"].astype(str)).set_index("region_id")

    failure_reasons: list[str] = []
    missing_regions = sorted(expected_regions - point_regions)
    if missing_regions:
        failure_reasons.append("missing_regions")
    missing_qc = sorted(expected_regions - set(qc_by_region.index))
    if missing_qc:
        failure_reasons.append("missing_qc")
    non_pass_regions = sorted(
        region_id
        for region_id in expected_regions.intersection(qc_by_region.index)
        if str(qc_by_region.loc[region_id, "status"]).upper() != "PASS"
    )
    if non_pass_regions:
        failure_reasons.append("non_pass_regions")
    invalid_face_regions = _invalid_region_faces(template, faces)
    if invalid_face_regions:
        failure_reasons.append("invalid_region_faces")

    members = template.manifest.merge(
        points,
        how="left",
        on=["region_id", "region_point_id"],
        validate="one_to_one",
        suffixes=("", "_sample"),
    )
    members["candidate_finite"] = np.isfinite(
        members[["x", "y", "z"]].to_numpy(dtype=float)
    ).all(axis=1)
    members["quality_rank"] = members.apply(_candidate_quality_rank, axis=1)
    members["repair_method"] = members.get(
        "repair_method", pd.Series("unknown", index=members.index)
    ).fillna("unknown")

    ranked = members.sort_values(
        ["global_vertex_id", "quality_rank", "region_id", "region_point_id"]
    )
    finite_chosen = ranked[ranked["candidate_finite"]].drop_duplicates("global_vertex_id")
    fallback = ranked.drop_duplicates("global_vertex_id")
    chosen = pd.concat([
        finite_chosen,
        fallback[~fallback["global_vertex_id"].isin(finite_chosen["global_vertex_id"])],
    ]).sort_values("global_vertex_id")
    invalid_global_vertices = int((~chosen["candidate_finite"]).sum())
    chosen_coordinates = chosen[
        ["global_vertex_id", "region_id", "region_point_id", "quality_rank", "repair_method", "x", "y", "z"]
    ].rename(columns={
        "region_id": "chosen_region_id",
        "region_point_id": "chosen_region_point_id",
        "quality_rank": "chosen_quality_rank",
        "repair_method": "chosen_repair_method",
        "x": "chosen_x",
        "y": "chosen_y",
        "z": "chosen_z",
    })
    members = members.merge(chosen_coordinates, on="global_vertex_id", how="left", validate="many_to_one")
    deltas = (
        members[["x", "y", "z"]].to_numpy(dtype=float)
        - members[["chosen_x", "chosen_y", "chosen_z"]].to_numpy(dtype=float)
    )
    members["distance_to_selected_mm"] = np.linalg.norm(deltas, axis=1)
    members.loc[~members["candidate_finite"], "distance_to_selected_mm"] = np.nan
    members["selected"] = (
        (members["region_id"] == members["chosen_region_id"])
        & (members["region_point_id"] == members["chosen_region_point_id"])
    )

    distance_stats = members.groupby("global_vertex_id").agg(
        member_count=("global_vertex_id", "size"),
        max_candidate_distance_mm=("distance_to_selected_mm", "max"),
        mean_candidate_distance_mm=("distance_to_selected_mm", "mean"),
    )
    whole_points = chosen_coordinates.rename(columns={
        "chosen_x": "x",
        "chosen_y": "y",
        "chosen_z": "z",
    }).merge(distance_stats, on="global_vertex_id", how="left", validate="one_to_one")
    landmark_globals = set(
        template.manifest.loc[
            template.manifest["topology_role"] == "landmark", "global_vertex_id"
        ].astype(int)
    )
    edge_globals = set(
        template.edge_members.loc[
            template.edge_members["global_vertex_id"].map(
                template.edge_members["global_vertex_id"].value_counts()
            ) > 1,
            "global_vertex_id",
        ].astype(int)
    )
    whole_points["topology_role"] = whole_points["global_vertex_id"].map(
        lambda global_id: (
            "landmark" if int(global_id) in landmark_globals
            else "shared_edge" if int(global_id) in edge_globals
            else "interior"
        )
    )
    whole_points.insert(0, "side", side)
    whole_points.insert(0, "sample_id", sample_id)
    whole_points = whole_points.sort_values("global_vertex_id").reset_index(drop=True)

    vertex_qc = members[[
        "global_vertex_id",
        "region_id",
        "region_point_id",
        "x",
        "y",
        "z",
        "candidate_finite",
        "quality_rank",
        "repair_method",
        "selected",
        "distance_to_selected_mm",
    ]].copy()
    vertex_qc.insert(0, "side", side)
    vertex_qc.insert(0, "sample_id", sample_id)
    edge_qc = _build_edge_qc(template, members, sample_id, side, warning_mm, fail_mm)
    whole_faces, degenerate_faces, duplicate_faces = _remap_faces(template, faces, sample_id, side)

    if invalid_global_vertices:
        failure_reasons.append("invalid_global_vertices")
    if degenerate_faces:
        failure_reasons.append("degenerate_global_faces")
    if duplicate_faces:
        failure_reasons.append("duplicate_global_faces")

    edge_status_counts = edge_qc["status"].value_counts() if not edge_qc.empty else pd.Series(dtype=int)
    if failure_reasons or int(edge_status_counts.get("FAIL", 0)):
        status = "FAIL"
    elif int(edge_status_counts.get("WARNING", 0)):
        status = "WARNING"
    else:
        status = "PASS"

    summary = pd.DataFrame([{
        "sample_id": sample_id,
        "side": side,
        "input_layer": "salvaged",
        "expected_region_count": len(expected_regions),
        "pass_region_count": len(expected_regions) - len(missing_qc) - len(non_pass_regions),
        "missing_region_count": len(missing_regions),
        "global_vertex_count": len(whole_points),
        "global_face_count": len(whole_faces),
        "shared_edge_count": len(edge_qc),
        "pass_edge_count": int(edge_status_counts.get("PASS", 0)),
        "warning_edge_count": int(edge_status_counts.get("WARNING", 0)),
        "fail_edge_count": int(edge_status_counts.get("FAIL", 0)),
        "max_boundary_distance_mm": (
            float(edge_qc["max_distance_mm"].max()) if not edge_qc.empty else 0.0
        ),
        "max_conflict_distance_mm": (
            float(edge_qc["max_conflict_distance_mm"].max()) if not edge_qc.empty else 0.0
        ),
        "max_replacement_distance_mm": (
            float(edge_qc["max_replacement_distance_mm"].max()) if not edge_qc.empty else 0.0
        ),
        "replacement_point_count": (
            int(edge_qc["replacement_point_count"].sum()) if not edge_qc.empty else 0
        ),
        "unresolved_point_count": (
            int(edge_qc["unresolved_point_count"].sum()) if not edge_qc.empty else 0
        ),
        "invalid_global_vertex_count": invalid_global_vertices,
        "invalid_region_face_count": len(invalid_face_regions),
        "degenerate_global_face_count": degenerate_faces,
        "duplicate_global_face_count": duplicate_faces,
        "failure_reasons": ";".join(dict.fromkeys(failure_reasons)),
        "status": status,
        "pca_ready": status == "PASS",
    }])
    return WholeEarResult(whole_points, whole_faces, edge_qc, vertex_qc, summary)


def repair_shared_edge_conflicts(
    template: GlobalTemplate,
    points: pd.DataFrame,
    region_qc: pd.DataFrame,
    mesh: trimesh.Trimesh,
    baseline: WholeEarResult,
    *,
    warning_mm: float = 0.25,
    fail_mm: float = 1.0,
    max_run_length: int = 2,
) -> EdgeRepairResult:
    """Repair short WARNING-only shared-edge gaps using anchors on the sample mesh."""
    if warning_mm < 0 or fail_mm < warning_mm:
        raise ValueError("weld thresholds must satisfy 0 <= warning_mm <= fail_mm")
    if max_run_length < 1:
        raise ValueError("max_run_length must be >= 1")
    _require_columns(
        region_qc,
        {"region_id", "raw_status", "degenerate_faces"},
        "region_qc",
    )
    _require_columns(
        points,
        {"region_id", "region_point_id", "x", "y", "z"},
        "points",
    )

    updated = points.copy()
    updated["region_id"] = updated["region_id"].astype(str)
    updated["region_point_id"] = updated["region_point_id"].astype(int)
    if "raw_is_unmapped" not in updated:
        updated["raw_is_unmapped"] = False
    if "repair_method" not in updated:
        updated["repair_method"] = "mapped"
    qc_by_region = region_qc.copy()
    qc_by_region["region_id"] = qc_by_region["region_id"].astype(str)
    if qc_by_region["region_id"].duplicated().any():
        raise ValueError("region_qc contains duplicate region_id rows")
    qc_by_region = qc_by_region.set_index("region_id")

    records: list[dict[str, object]] = []
    non_pass = baseline.edge_qc[baseline.edge_qc["status"] != "PASS"]
    for edge in non_pass.itertuples(index=False):
        edge_rows = _edge_candidate_rows(template, updated, str(edge.edge_id))
        regions = sorted(edge_rows["region_id"].astype(str).unique())
        raw_statuses = {
            region_id: str(qc_by_region.loc[region_id, "raw_status"]).upper()
            for region_id in regions
        }
        degenerate = {
            region_id: int(qc_by_region.loc[region_id, "degenerate_faces"])
            for region_id in regions
        }
        invalid_indices = _non_finite_edge_indices(edge_rows)
        if invalid_indices:
            for edge_index in invalid_indices:
                records.append({
                    "edge_id": str(edge.edge_id),
                    "edge_index": edge_index,
                    "regions": ";".join(regions),
                    "raw_edge_status": str(edge.status),
                    "pre_distance_mm": np.nan,
                    "post_distance_mm": np.nan,
                    "eligible": False,
                    "applied": False,
                    "rejection_reason": "non_finite_candidate",
                    "left_anchor_index": np.nan,
                    "right_anchor_index": np.nan,
                    "projection_distance_mm": np.nan,
                    "repair_method": "",
                })
            continue

        severe = _severe_conflicts(edge_rows, warning_mm)
        if not severe:
            continue
        reason = _edge_repair_rejection_reason(
            str(edge.status),
            raw_statuses,
            degenerate,
            severe,
            max_run_length,
        )
        edge_record_indexes: list[int] = []
        for candidate in severe:
            record = {
                "edge_id": str(edge.edge_id),
                "edge_index": int(candidate["edge_index"]),
                "regions": ";".join(regions),
                "raw_edge_status": str(edge.status),
                "pre_distance_mm": float(candidate["distance_mm"]),
                "post_distance_mm": float(candidate["distance_mm"]),
                "eligible": reason == "",
                "applied": False,
                "rejection_reason": reason,
                "left_anchor_index": np.nan,
                "right_anchor_index": np.nan,
                "projection_distance_mm": np.nan,
                "repair_method": "",
            }
            records.append(record)
            edge_record_indexes.append(len(records) - 1)
        if reason:
            continue

        original = updated.copy()
        projected_by_index: dict[int, tuple[np.ndarray, float, int, int]] = {}
        for run in _contiguous_runs([int(item["edge_index"]) for item in severe]):
            left_anchor = _find_trusted_anchor(edge_rows, run[0], direction=-1)
            right_anchor = _find_trusted_anchor(edge_rows, run[-1], direction=1)
            if left_anchor is None or right_anchor is None:
                reason = "missing_trusted_anchor"
                break
            left_index, left_xyz = left_anchor
            right_index, right_xyz = right_anchor
            for edge_index in run:
                fraction = (edge_index - left_index) / (right_index - left_index)
                interpolated = (1.0 - fraction) * left_xyz + fraction * right_xyz
                try:
                    projected, distance = _project_to_mesh(mesh, interpolated)
                except ValueError:
                    reason = "mesh_projection_failed"
                    break
                projected_by_index[edge_index] = (projected, distance, left_index, right_index)
            if reason:
                break
        if reason:
            for index in edge_record_indexes:
                records[index]["eligible"] = False
                records[index]["rejection_reason"] = reason
            continue

        for edge_index, (projected, _, _, _) in projected_by_index.items():
            members = edge_rows[edge_rows["edge_index"] == edge_index]
            for member in members.itertuples(index=False):
                mask = (
                    (updated["region_id"] == member.region_id)
                    & (updated["region_point_id"] == member.region_point_id)
                )
                updated.loc[mask, ["x", "y", "z"]] = projected
                updated.loc[mask, "raw_is_unmapped"] = True
                updated.loc[mask, "repair_method"] = "edge_coupled_interpolation"

        post_rows = _edge_candidate_rows(template, updated, str(edge.edge_id))
        max_conflict = _max_edge_conflict(post_rows)
        if max_conflict > warning_mm:
            updated = original
            for index in edge_record_indexes:
                records[index]["eligible"] = False
                records[index]["rejection_reason"] = "post_repair_conflict_above_warning"
            continue
        for index in edge_record_indexes:
            edge_index = int(records[index]["edge_index"])
            _, distance, left_index, right_index = projected_by_index[edge_index]
            records[index]["applied"] = True
            records[index]["post_distance_mm"] = 0.0
            records[index]["left_anchor_index"] = left_index
            records[index]["right_anchor_index"] = right_index
            records[index]["projection_distance_mm"] = distance
            records[index]["repair_method"] = "edge_coupled_interpolation"

    columns = [
        "edge_id",
        "edge_index",
        "regions",
        "raw_edge_status",
        "pre_distance_mm",
        "post_distance_mm",
        "eligible",
        "applied",
        "rejection_reason",
        "left_anchor_index",
        "right_anchor_index",
        "projection_distance_mm",
        "repair_method",
    ]
    return EdgeRepairResult(updated, pd.DataFrame(records, columns=columns))


def _lattice_points(resolution: int) -> list[tuple[int, int, int]]:
    return [
        (resolution - i - j, i, j)
        for i in range(resolution + 1)
        for j in range(resolution - i + 1)
    ]


def _point_topology(
    landmarks: tuple[str, str, str],
    weights: tuple[int, int, int],
    resolution: int,
) -> tuple[str, str, str, int | None]:
    positive = [index for index, weight in enumerate(weights) if weight > 0]
    if len(positive) == 1:
        return "landmark", landmarks[positive[0]], "", None
    if len(positive) == 2:
        first, second = positive
        lm_start, lm_end = sorted((landmarks[first], landmarks[second]))
        weight_by_landmark = {
            landmarks[first]: weights[first],
            landmarks[second]: weights[second],
        }
        return "shared_edge_candidate", "", _edge_id(lm_start, lm_end), int(weight_by_landmark[lm_end])
    if sum(weights) != resolution:
        raise ValueError("invalid barycentric lattice point")
    return "interior", "", "", None


def _edge_point_map(
    region_id: str,
    landmarks: tuple[str, str, str],
    lattice: list[tuple[int, int, int]],
    first: int,
    second: int,
    canonical_end: str,
) -> dict[int, LocalPoint]:
    excluded = ({0, 1, 2} - {first, second}).pop()
    end_index = landmarks.index(canonical_end)
    return {
        int(weights[end_index]): (region_id, point_id)
        for point_id, weights in enumerate(lattice)
        if weights[excluded] == 0
    }


def _build_edge_members(
    edge_uses: dict[str, list[dict[str, object]]],
    local_to_global: dict[LocalPoint, int],
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for edge_id, uses in sorted(edge_uses.items()):
        for use in uses:
            for edge_index, local_point in sorted(use["points"].items()):
                records.append({
                    "edge_id": edge_id,
                    "edge_index": int(edge_index),
                    "region_id": str(use["region_id"]),
                    "region_point_id": int(local_point[1]),
                    "global_vertex_id": int(local_to_global[local_point]),
                })
    return pd.DataFrame(records)


def _build_edge_qc(
    template: GlobalTemplate,
    members: pd.DataFrame,
    sample_id: str,
    side: str,
    warning_mm: float,
    fail_mm: float,
) -> pd.DataFrame:
    candidate_coordinates = members[
        [
            "region_id",
            "region_point_id",
            "x",
            "y",
            "z",
            "candidate_finite",
            "quality_rank",
        ]
    ]
    edge_members = template.edge_members.merge(
        candidate_coordinates,
        on=["region_id", "region_point_id"],
        how="left",
        validate="many_to_one",
    )
    records: list[dict[str, object]] = []
    shared_edges = template.edges[template.edges["is_shared"]]
    for edge in shared_edges.itertuples(index=False):
        edge_rows = edge_members[edge_members["edge_id"] == edge.edge_id]
        distances: list[float] = []
        conflict_distances: list[float] = []
        replacement_distances: list[float] = []
        invalid_points = 0
        unresolved_points = 0
        for _, group in edge_rows.groupby("edge_index", sort=True):
            finite = group[group["candidate_finite"]]
            if len(finite) != 2:
                invalid_points += 1
                continue
            xyz = finite[["x", "y", "z"]].to_numpy(dtype=float)
            distance = float(np.linalg.norm(xyz[0] - xyz[1]))
            distances.append(distance)
            mapped_count = int((finite["quality_rank"] == 0).sum())
            if mapped_count == 1:
                replacement_distances.append(distance)
            else:
                conflict_distances.append(distance)
                if mapped_count == 0:
                    unresolved_points += 1
        if invalid_points:
            status = "FAIL"
        else:
            status = _distance_status(
                max(conflict_distances, default=0.0), warning_mm, fail_mm
            )
        records.append({
            "sample_id": sample_id,
            "side": side,
            "edge_id": edge.edge_id,
            "lm_start": edge.lm_start,
            "lm_end": edge.lm_end,
            "regions": edge.regions,
            "expected_point_count": int(edge.resolution) + 1,
            "compared_point_count": len(distances),
            "invalid_point_count": invalid_points,
            "replacement_point_count": len(replacement_distances),
            "unresolved_point_count": unresolved_points,
            "mean_distance_mm": float(np.mean(distances)) if distances else np.nan,
            "rms_distance_mm": (
                float(np.sqrt(np.mean(np.square(distances)))) if distances else np.nan
            ),
            "max_distance_mm": max(distances, default=np.nan),
            "max_conflict_distance_mm": max(conflict_distances, default=0.0),
            "max_replacement_distance_mm": max(replacement_distances, default=0.0),
            "status": status,
        })
    return pd.DataFrame(records)


def _edge_candidate_rows(
    template: GlobalTemplate,
    points: pd.DataFrame,
    edge_id: str,
) -> pd.DataFrame:
    topology = template.manifest[
        ["region_id", "region_point_id", "topology_role"]
    ].copy()
    candidates = topology.merge(
        points,
        on=["region_id", "region_point_id"],
        how="left",
        validate="one_to_one",
    )
    candidates["candidate_finite"] = np.isfinite(
        candidates[["x", "y", "z"]].to_numpy(dtype=float)
    ).all(axis=1)
    candidates["quality_rank"] = candidates.apply(_candidate_quality_rank, axis=1)
    edge_members = template.edge_members[template.edge_members["edge_id"] == edge_id]
    return edge_members.merge(
        candidates[
            [
                "region_id",
                "region_point_id",
                "x",
                "y",
                "z",
                "candidate_finite",
                "quality_rank",
                "repair_method",
            ]
        ],
        on=["region_id", "region_point_id"],
        how="left",
        validate="one_to_one",
    )


def _severe_conflicts(edge_rows: pd.DataFrame, warning_mm: float) -> list[dict[str, object]]:
    conflicts: list[dict[str, object]] = []
    for edge_index, group in edge_rows.groupby("edge_index", sort=True):
        finite = group[group["candidate_finite"]]
        if len(finite) != 2:
            continue
        xyz = finite[["x", "y", "z"]].to_numpy(dtype=float)
        distance = float(np.linalg.norm(xyz[0] - xyz[1]))
        mapped_count = int((finite["quality_rank"] == 0).sum())
        if mapped_count != 1 and distance > warning_mm:
            conflicts.append({
                "edge_index": int(edge_index),
                "distance_mm": distance,
                "all_repaired": bool((finite["quality_rank"] > 0).all()),
            })
    return conflicts


def _non_finite_edge_indices(edge_rows: pd.DataFrame) -> list[int]:
    """Return shared-edge positions with a missing or non-finite candidate."""
    return [
        int(edge_index)
        for edge_index, group in edge_rows.groupby("edge_index", sort=True)
        if not bool(group["candidate_finite"].all())
    ]


def _edge_repair_rejection_reason(
    raw_edge_status: str,
    raw_statuses: dict[str, str],
    degenerate_faces: dict[str, int],
    conflicts: list[dict[str, object]],
    max_run_length: int,
) -> str:
    if any(status == "FAIL" for status in raw_statuses.values()):
        return "adjacent_raw_fail"
    if any(count > 0 for count in degenerate_faces.values()):
        return "adjacent_degenerate_face"
    if raw_edge_status != "WARNING":
        return "raw_weld_not_warning"
    if not all(bool(conflict["all_repaired"]) for conflict in conflicts):
        return "conflict_not_repaired_only"
    if any(len(run) > max_run_length for run in _contiguous_runs([
        int(conflict["edge_index"]) for conflict in conflicts
    ])):
        return "conflict_run_too_long"
    return ""


def _contiguous_runs(indices: list[int]) -> list[list[int]]:
    if not indices:
        return []
    runs: list[list[int]] = [[min(indices)]]
    for index in sorted(set(indices)):
        if index == runs[-1][-1]:
            continue
        if index == runs[-1][-1] + 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    return runs


def _find_trusted_anchor(
    edge_rows: pd.DataFrame,
    start_index: int,
    *,
    direction: int,
) -> tuple[int, np.ndarray] | None:
    available = sorted(edge_rows["edge_index"].astype(int).unique())
    candidate_indices = (
        [index for index in reversed(available) if index < start_index]
        if direction < 0
        else [index for index in available if index > start_index]
    )
    for edge_index in candidate_indices:
        group = edge_rows[edge_rows["edge_index"] == edge_index]
        trusted = group[
            group["candidate_finite"] & (group["quality_rank"] <= 0)
        ].sort_values(["quality_rank", "region_id", "region_point_id"])
        if not trusted.empty:
            row = trusted.iloc[0]
            return int(edge_index), row[["x", "y", "z"]].to_numpy(dtype=float)
    return None


def _project_to_mesh(mesh: trimesh.Trimesh, point: np.ndarray) -> tuple[np.ndarray, float]:
    query = np.asarray(point, dtype=float).reshape(1, 3)
    try:
        projected, distance, _ = trimesh.proximity.closest_point(mesh, query)
    except (ImportError, ModuleNotFoundError):
        projected, distance, _ = trimesh.proximity.closest_point_naive(mesh, query)
    except Exception as error:
        if "rtree" not in str(error).lower():
            raise ValueError("mesh projection failed") from error
        projected, distance, _ = trimesh.proximity.closest_point_naive(mesh, query)
    if not np.isfinite(projected).all() or not np.isfinite(distance).all():
        raise ValueError("mesh projection failed")
    return projected[0], float(distance[0])


def _max_edge_conflict(edge_rows: pd.DataFrame) -> float:
    conflicts = _severe_conflicts(edge_rows, warning_mm=-np.inf)
    return max((float(conflict["distance_mm"]) for conflict in conflicts), default=0.0)


def _remap_faces(
    template: GlobalTemplate,
    faces: pd.DataFrame,
    sample_id: str,
    side: str,
) -> tuple[pd.DataFrame, int, int]:
    records: list[dict[str, object]] = []
    for face in faces.sort_values(["region_id", "face_id"]).itertuples(index=False):
        region_id = str(face.region_id)
        global_vertices = [
            template.local_to_global.get((region_id, int(local_id)), -1)
            for local_id in (face.local_v0, face.local_v1, face.local_v2)
        ]
        records.append({
            "sample_id": sample_id,
            "side": side,
            "region_id": region_id,
            "region_face_id": int(face.face_id),
            "global_face_id": len(records),
            "global_v0": global_vertices[0],
            "global_v1": global_vertices[1],
            "global_v2": global_vertices[2],
        })
    whole_faces = pd.DataFrame(records)
    if whole_faces.empty:
        return whole_faces, 0, 0
    values = whole_faces[["global_v0", "global_v1", "global_v2"]].to_numpy(dtype=int)
    degenerate = int(sum(len(set(face)) < 3 or (face < 0).any() for face in values))
    canonical = np.sort(values, axis=1)
    duplicate = int(pd.DataFrame(canonical).duplicated().sum())
    return whole_faces, degenerate, duplicate


def _invalid_region_faces(template: GlobalTemplate, faces: pd.DataFrame) -> list[str]:
    """Return regions whose local faces differ from the fixed subdivision template."""
    resolutions = template.manifest.groupby("region_id")["resolution"].first().astype(int)
    invalid = set(faces["region_id"].astype(str)).difference(resolutions.index)
    for region_id, resolution in resolutions.items():
        actual = faces.loc[faces["region_id"] == region_id].sort_values("face_id")
        expected = make_subdivision_template(int(resolution)).faces
        face_ids = actual["face_id"].to_numpy(dtype=int)
        local_faces = actual[["local_v0", "local_v1", "local_v2"]].to_numpy(dtype=int)
        if (
            len(actual) != len(expected)
            or not np.array_equal(face_ids, np.arange(len(expected)))
            or not np.array_equal(local_faces, expected)
        ):
            invalid.add(str(region_id))
    return sorted(invalid)


def _candidate_quality_rank(row: pd.Series) -> int:
    """Rank shared-point candidates; snapped landmarks anchor global corners."""
    raw_unmapped = row.get("raw_is_unmapped", None)
    method = str(row.get("repair_method", "")).strip().lower()
    topology_role = str(row.get("topology_role", "")).strip().lower()
    if topology_role == "landmark" and method == "landmark_vertex":
        return -1
    if raw_unmapped is not None and not pd.isna(raw_unmapped) and not _as_bool(raw_unmapped):
        return 0
    ranks = {
        "mapped": 0,
        "landmark_vertex": 1,
        "smooth_near_vertex": 2,
        "smooth_internal": 3,
    }
    return ranks.get(method, 4)


def _distance_status(distance: float, warning_mm: float, fail_mm: float) -> str:
    if distance <= warning_mm:
        return "PASS"
    if distance <= fail_mm:
        return "WARNING"
    return "FAIL"


def _as_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _single_value(frame: pd.DataFrame, column: str, default: str) -> str:
    if column not in frame or frame.empty:
        return default
    values = frame[column].dropna().astype(str).unique()
    if len(values) > 1:
        raise ValueError(f"{column} must have one value per sample")
    return values[0] if len(values) else default


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")


def _edge_id(lm_start: str, lm_end: str) -> str:
    return f"{lm_start}__{lm_end}"
