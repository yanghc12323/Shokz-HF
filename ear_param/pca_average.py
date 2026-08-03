"""PCA-ready whole-ear loading, PCA fitting, and average-ear export."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import trimesh


REPAIRED_LAYER = "weld_repaired"
POINT_COLUMNS = ("global_vertex_id", "x", "y", "z")
FACE_COLUMNS = ("global_face_id", "global_v0", "global_v1", "global_v2")


@dataclass(frozen=True)
class PcaInput:
    """Topology-consistent aligned ears that passed PCA provenance gates."""

    sample_tags: tuple[str, ...]
    points: np.ndarray
    vertex_ids: np.ndarray
    faces: np.ndarray
    face_ids: np.ndarray
    manifest: pd.DataFrame


@dataclass(frozen=True)
class PcaResult:
    """Centered PCA result with only nonzero shape components retained."""

    mean_points: np.ndarray
    components: np.ndarray
    scores: np.ndarray
    explained_variance: np.ndarray
    explained_variance_ratio: np.ndarray
    cumulative_explained_variance_ratio: np.ndarray
    n_components_75: int


def load_pca_inputs(aligned_dir: Path, weld_dir: Path) -> PcaInput:
    """Load aligned repaired ears after validating provenance and topology."""
    aligned_dir = Path(aligned_dir)
    weld_dir = Path(weld_dir)
    manifest = build_pca_input_manifest(aligned_dir, weld_dir)
    included = manifest.loc[manifest["included"]].copy()
    if len(included) < 2:
        raise ValueError("At least two eligible aligned whole-ear samples are required.")

    expected_vertex_ids: np.ndarray | None = None
    expected_faces: np.ndarray | None = None
    expected_face_ids: np.ndarray | None = None
    point_blocks: list[np.ndarray] = []
    sample_tags = tuple(included["sample_tag"].astype(str))
    for sample_tag in sample_tags:
        vertex_ids, coordinates = _load_points(
            aligned_dir / f"{sample_tag}_aligned_whole_ear_points.csv"
        )
        face_ids, faces = _load_faces(
            aligned_dir / f"{sample_tag}_aligned_whole_ear_faces.csv"
        )
        if not np.isin(faces, vertex_ids).all():
            raise ValueError(f"faces reference missing vertices: {sample_tag}")
        if expected_vertex_ids is None:
            expected_vertex_ids = vertex_ids
            expected_faces = faces
            expected_face_ids = face_ids
        else:
            if not np.array_equal(vertex_ids, expected_vertex_ids):
                raise ValueError(f"global vertex ids mismatch: {sample_tag}")
            if not np.array_equal(face_ids, expected_face_ids):
                raise ValueError(f"global face ids mismatch: {sample_tag}")
            if not np.array_equal(faces, expected_faces):
                raise ValueError(f"global face topology mismatch: {sample_tag}")
        point_blocks.append(coordinates)

    assert expected_vertex_ids is not None
    assert expected_faces is not None
    assert expected_face_ids is not None
    return PcaInput(
        sample_tags=sample_tags,
        points=np.stack(point_blocks),
        vertex_ids=expected_vertex_ids,
        faces=expected_faces,
        face_ids=expected_face_ids,
        manifest=manifest,
    )


def build_pca_input_manifest(aligned_dir: Path, weld_dir: Path) -> pd.DataFrame:
    """Create an auditable inclusion decision for each aligned sample record."""
    alignment_path = Path(aligned_dir) / "alignment_qc_summary.csv"
    if not alignment_path.is_file():
        raise ValueError(f"missing alignment summary: {alignment_path}")
    alignment = pd.read_csv(alignment_path)
    _require_columns(alignment, {"sample_tag", "status", "input_layer"}, alignment_path)
    if alignment["sample_tag"].astype(str).duplicated().any():
        raise ValueError("alignment summary contains duplicate sample_tag values")

    records: list[dict[str, object]] = []
    for row in alignment.sort_values("sample_tag").itertuples(index=False):
        sample_tag = str(row.sample_tag)
        alignment_status = _normalized_text(row.status)
        alignment_layer = _normalized_text(row.input_layer)
        record: dict[str, object] = {
            "sample_tag": sample_tag,
            "alignment_status": alignment_status,
            "alignment_input_layer": alignment_layer,
            "weld_status": "",
            "weld_pca_ready": False,
            "weld_input_layer": "",
            "included": False,
            "exclusion_reason": "",
        }
        if alignment_status != "PASS":
            record["exclusion_reason"] = "alignment_status_not_pass"
        elif alignment_layer != REPAIRED_LAYER.upper():
            record["exclusion_reason"] = "alignment_input_layer_not_repaired"
        else:
            _apply_weld_gate(record, Path(weld_dir) / f"{sample_tag}_weld_qc_summary.csv")
        records.append(record)
    return pd.DataFrame(records)


def fit_pca(inputs: PcaInput, variance_threshold: float = 0.75) -> PcaResult:
    """Fit centered PCA by SVD without rescaling physical coordinates."""
    if not 0.0 < variance_threshold <= 1.0:
        raise ValueError("variance_threshold must be in (0, 1]")
    sample_count = len(inputs.sample_tags)
    if sample_count < 2:
        raise ValueError("At least two samples are required for PCA.")

    matrix = inputs.points.reshape(sample_count, -1)
    mean_vector = matrix.mean(axis=0)
    centered = matrix - mean_vector
    _, singular_values, right_vectors = np.linalg.svd(centered, full_matrices=False)
    all_variance = singular_values**2 / (sample_count - 1)
    variance_tolerance = np.finfo(float).eps * max(float(all_variance.max()), 1.0)
    keep = all_variance > variance_tolerance
    if not np.any(keep):
        raise ValueError("PCA input has zero shape variance")
    explained_variance = all_variance[keep]
    components = right_vectors[keep]
    scores = centered @ components.T
    explained_ratio = explained_variance / explained_variance.sum()
    cumulative_ratio = np.cumsum(explained_ratio)
    retained_count = int(np.searchsorted(cumulative_ratio, variance_threshold) + 1)
    return PcaResult(
        mean_points=mean_vector.reshape(inputs.points.shape[1:]),
        components=components,
        scores=scores,
        explained_variance=explained_variance,
        explained_variance_ratio=explained_ratio,
        cumulative_explained_variance_ratio=cumulative_ratio,
        n_components_75=retained_count,
    )


def write_pca_outputs(
    inputs: PcaInput,
    result: PcaResult,
    out_dir: Path,
    variance_threshold: float = 0.75,
) -> None:
    """Write PCA statistics, mean mesh, and +/-2 SD retained-PC meshes."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    inputs.manifest.to_csv(out_dir / "pca_input_manifest.csv", index=False)
    pd.DataFrame({
        "global_vertex_id": inputs.vertex_ids,
        "x": result.mean_points[:, 0],
        "y": result.mean_points[:, 1],
        "z": result.mean_points[:, 2],
    }).to_csv(out_dir / "mean_whole_ear_points.csv", index=False)
    pd.DataFrame({
        "global_face_id": inputs.face_ids,
        "global_v0": inputs.faces[:, 0],
        "global_v1": inputs.faces[:, 1],
        "global_v2": inputs.faces[:, 2],
    }).to_csv(out_dir / "mean_whole_ear_faces.csv", index=False)
    _export_mesh(out_dir / "mean_whole_ear.ply", result.mean_points, inputs.faces)
    np.save(out_dir / "components.npy", result.components)

    component_names = [f"PC{index:02d}" for index in range(1, len(result.components) + 1)]
    scores = pd.DataFrame(result.scores, columns=component_names)
    scores.insert(0, "sample_tag", inputs.sample_tags)
    scores.to_csv(out_dir / "scores.csv", index=False)
    explained = pd.DataFrame({
        "component": np.arange(1, len(result.components) + 1),
        "explained_variance": result.explained_variance,
        "explained_variance_ratio": result.explained_variance_ratio,
        "cumulative_explained_variance_ratio": result.cumulative_explained_variance_ratio,
        "retained_for_threshold": np.arange(1, len(result.components) + 1)
        <= result.n_components_75,
    })
    explained.to_csv(out_dir / "explained_variance.csv", index=False)
    pd.DataFrame([{
        "included_sample_count": len(inputs.sample_tags),
        "excluded_sample_count": int((~inputs.manifest["included"]).sum()),
        "vertex_count": len(inputs.vertex_ids),
        "face_count": len(inputs.faces),
        "variance_threshold": variance_threshold,
        "retained_component_count": result.n_components_75,
        "retained_cumulative_explained_variance_ratio": (
            result.cumulative_explained_variance_ratio[result.n_components_75 - 1]
        ),
    }]).to_csv(out_dir / "pca_summary.csv", index=False)

    mode_dir = out_dir / "pc_modes"
    mode_dir.mkdir(exist_ok=True)
    mode_count = min(
        len(result.components),
        max(result.n_components_75, 2),
    )
    for component_index in range(mode_count):
        displacement = result.components[component_index].reshape(result.mean_points.shape)
        scale = 2.0 * np.sqrt(result.explained_variance[component_index])
        mode_name = f"PC{component_index + 1:02d}"
        _export_mesh(mode_dir / f"{mode_name}_plus_2sd.ply", result.mean_points + scale * displacement, inputs.faces)
        _export_mesh(mode_dir / f"{mode_name}_minus_2sd.ply", result.mean_points - scale * displacement, inputs.faces)


def _apply_weld_gate(record: dict[str, object], summary_path: Path) -> None:
    if not summary_path.is_file():
        record["exclusion_reason"] = "missing_weld_summary"
        return
    summary = pd.read_csv(summary_path)
    required = {"status", "pca_ready", "input_layer"}
    try:
        _require_columns(summary, required, summary_path)
    except ValueError:
        record["exclusion_reason"] = "invalid_weld_summary"
        return
    if len(summary) != 1:
        record["exclusion_reason"] = "invalid_weld_summary"
        return
    row = summary.iloc[0]
    record["weld_status"] = _normalized_text(row["status"])
    record["weld_pca_ready"] = _as_bool(row["pca_ready"])
    record["weld_input_layer"] = _normalized_text(row["input_layer"])
    if record["weld_status"] != "PASS":
        record["exclusion_reason"] = "weld_status_not_pass"
    elif not bool(record["weld_pca_ready"]):
        record["exclusion_reason"] = "weld_not_pca_ready"
    elif record["weld_input_layer"] != REPAIRED_LAYER.upper():
        record["exclusion_reason"] = "weld_input_layer_not_repaired"
    else:
        record["included"] = True


def _load_points(path: Path) -> tuple[np.ndarray, np.ndarray]:
    table = pd.read_csv(path)
    _require_columns(table, set(POINT_COLUMNS), path)
    ids = table["global_vertex_id"].to_numpy(dtype=int)
    if len(np.unique(ids)) != len(ids):
        raise ValueError(f"duplicate global_vertex_id values: {path.name}")
    order = np.argsort(ids)
    ids = ids[order]
    coordinates = table.loc[:, ["x", "y", "z"]].to_numpy(dtype=float)[order]
    if not np.isfinite(coordinates).all():
        raise ValueError(f"non-finite coordinates: {path.name}")
    return ids, coordinates


def _load_faces(path: Path) -> tuple[np.ndarray, np.ndarray]:
    table = pd.read_csv(path)
    _require_columns(table, set(FACE_COLUMNS), path)
    ids = table["global_face_id"].to_numpy(dtype=int)
    if len(np.unique(ids)) != len(ids):
        raise ValueError(f"duplicate global_face_id values: {path.name}")
    order = np.argsort(ids)
    return ids[order], table.loc[:, ["global_v0", "global_v1", "global_v2"]].to_numpy(dtype=int)[order]


def _export_mesh(path: Path, vertices: np.ndarray, faces: np.ndarray) -> None:
    trimesh.Trimesh(vertices=vertices, faces=faces, process=False).export(path)


def _require_columns(table: pd.DataFrame, required: set[str], path: Path) -> None:
    missing = required.difference(table.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")


def _normalized_text(value: object) -> str:
    return str(value).strip().upper()


def _as_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}
