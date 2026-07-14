"""Shared discovery and orchestration helpers for the formal batch pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import sys
from typing import Callable

import pandas as pd
from ear_param.canonicalization import canonicalize_sample


def discover_samples(mesh_dir: Path, landmarks_dir: Path) -> pd.DataFrame:
    """Return every mesh/landmark tag and its paired-input readiness state."""
    mesh_dir = Path(mesh_dir)
    landmarks_dir = Path(landmarks_dir)
    mesh_tags = {path.stem for path in mesh_dir.glob("*.ply")} if mesh_dir.exists() else set()
    landmark_tags = {
        path.name.removesuffix("_landmarks.csv")
        for path in landmarks_dir.glob("*_landmarks.csv")
    } if landmarks_dir.exists() else set()

    records: list[dict[str, str]] = []
    for sample_tag in sorted(mesh_tags | landmark_tags):
        has_mesh = sample_tag in mesh_tags
        has_landmarks = sample_tag in landmark_tags
        if has_mesh and has_landmarks:
            discovery, reason = "READY", ""
        elif has_mesh:
            discovery, reason = "MISSING_LANDMARKS", "missing_landmarks"
        else:
            discovery, reason = "MISSING_MESH", "missing_mesh"
        records.append({
            "sample_tag": sample_tag,
            "discovery": discovery,
            "reason": reason,
        })
    return pd.DataFrame(records, columns=["sample_tag", "discovery", "reason"])


@dataclass(frozen=True)
class PipelineConfig:
    """Input locations required before the stage-specific options are applied."""

    mesh_dir: Path
    landmarks_dir: Path
    regions: Path = Path("config/region_table.csv")
    raw_dir: Path = Path("output/parameterized_points_r24/raw")
    repaired_dir: Path = Path("output/parameterized_points_r24/repaired")
    salvaged_dir: Path = Path("output/parameterized_points_r24/salvaged")
    qc_dir: Path = Path("output/qc_visualizations_r24")
    weld_dir: Path = Path("output/whole_ear_r24/weld_repaired")
    aligned_dir: Path = Path("output/whole_ear_r24/aligned_weld_repaired")
    pca_dir: Path = Path("output/w3_pca_r24")
    reference_aligned_dir: Path = Path("output/whole_ear_r24/aligned_reference_weld_repaired")
    reference_pca_dir: Path = Path("output/w3_pca_reference_r24")
    canonical_dir: Path = Path("output/canonical_inputs_r24")
    canonical_side: str = "L"
    mirror_axis: str = "x"
    disable_side_normalization: bool = True
    sample_tags: tuple[str, ...] = ()
    skip_remesh_qc: bool = False
    skip_pca: bool = False
    reference_sample: str | None = None
    reporter: Callable[[str], None] | None = None


@dataclass(frozen=True)
class StageFunctions:
    """Injectable stage calls used by the batch state machine."""

    remesh_sample: Callable[[str], dict[str, str]]
    remesh_qc: Callable[[str], str]
    weld_batch: Callable[[list[str]], pd.DataFrame]
    alignment_batch: Callable[[list[str]], pd.DataFrame]
    pca_batch: Callable[[], dict[str, object]]
    fixed_reference_alignment_batch: Callable[[list[str], str], pd.DataFrame] | None = None
    fixed_reference_pca_batch: Callable[[], dict[str, object]] | None = None


@dataclass(frozen=True)
class PipelineResult:
    """Sample-level stage states plus final PCA status."""

    records: pd.DataFrame
    pca_status: str
    pca_result: dict[str, object]
    reference_pca_status: str = "SKIPPED_BY_OPTION"
    reference_pca_result: dict[str, object] = field(default_factory=dict)


def write_pipeline_outputs(result: PipelineResult, run_dir: Path) -> None:
    """Write durable batch records, aggregate counts, and a plain-text log."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    result.records.to_csv(run_dir / "pipeline_batch_summary.csv", index=False)
    summary = {
        "discovered_sample_count": len(result.records),
        "ready_sample_count": int((result.records["discovery"] == "READY").sum()),
        "missing_pair_count": int((result.records["discovery"] != "READY").sum()),
        "salvage_pass_count": int((result.records["salvage"] == "PASS").sum()),
        "weld_pass_count": int((result.records["weld"] == "PASS").sum()),
        "alignment_pass_count": int((result.records["alignment"] == "PASS").sum()),
        "pca_included_count": int((result.records["pca_included"] == "YES").sum()),
        "reference_alignment_pass_count": int((result.records["reference_alignment"] == "PASS").sum()),
        "reference_pca_included_count": int((result.records["reference_pca_included"] == "YES").sum()),
        "pca_status": result.pca_status,
        "reference_pca_status": result.reference_pca_status,
    }
    for key, value in result.pca_result.items():
        if isinstance(value, (str, int, float, bool)):
            summary[f"pca_{key}"] = value
    for key, value in result.reference_pca_result.items():
        if isinstance(value, (str, int, float, bool)):
            summary[f"reference_pca_{key}"] = value
    pd.DataFrame([summary]).to_csv(run_dir / "pipeline_run_summary.csv", index=False)
    lines = [
        f"GPA PCA status: {result.pca_status}",
        f"Fixed-reference PCA status: {result.reference_pca_status}",
        "",
        result.records.to_string(index=False),
    ]
    (run_dir / "pipeline_run.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_pipeline(
    config: PipelineConfig,
    *,
    stage_functions: StageFunctions,
) -> PipelineResult:
    """Run staged sample processing while isolating failures to one sample."""
    records = discover_samples(config.mesh_dir, config.landmarks_dir).copy()
    if config.sample_tags:
        records = records[records["sample_tag"].isin(config.sample_tags)].reset_index(drop=True)
    for column in (
        "remesh", "salvage", "remesh_qc", "weld", "alignment", "pca_included",
        "reference_alignment", "reference_pca_included",
    ):
        records[column] = "SKIPPED"
    records["source_side"] = ""
    records["canonical_side"] = ""
    records["mirrored"] = False
    records["mirror_axis"] = ""
    for index, row in records.iterrows():
        if row["discovery"] != "READY":
            continue
        sample_tag = str(row["sample_tag"])
        if config.disable_side_normalization:
            continue
        try:
            canonical = canonicalize_sample(sample_tag, config.mesh_dir / f"{sample_tag}.ply", config.landmarks_dir / f"{sample_tag}_landmarks.csv", config.canonical_dir, canonical_side=config.canonical_side, mirror_axis=config.mirror_axis)
            records.at[index, "source_side"] = canonical.source_side
            records.at[index, "canonical_side"] = canonical.canonical_side
            records.at[index, "mirrored"] = canonical.mirrored
            records.at[index, "mirror_axis"] = canonical.mirror_axis
        except Exception as exc:
            records.at[index, "discovery"] = "INVALID_SIDE"
            records.at[index, "reason"] = _append_reason(row["reason"], f"canonicalization_error:{exc}")

    for index, row in records.iterrows():
        if row["discovery"] != "READY":
            continue
        sample_tag = str(row["sample_tag"])
        _report(config, f"{sample_tag} REMESH ...")
        try:
            outcome = stage_functions.remesh_sample(sample_tag)
        except Exception as exc:
            records.at[index, "remesh"] = "ERROR"
            records.at[index, "reason"] = _append_reason(row["reason"], f"remesh_error:{exc}")
            _report(config, f"{sample_tag} REMESH ... ERROR")
            continue

        remesh_status = str(outcome.get("remesh", "ERROR")).upper()
        salvage_status = str(outcome.get("salvage", "SKIPPED")).upper()
        records.at[index, "remesh"] = remesh_status
        records.at[index, "salvage"] = salvage_status
        _report(config, f"{sample_tag} REMESH={remesh_status} SALVAGE={salvage_status}")
        if salvage_status != "PASS":
            records.at[index, "reason"] = _append_reason(
                row["reason"], "salvage_not_pass"
            )
        if config.skip_remesh_qc:
            records.at[index, "remesh_qc"] = "SKIPPED_BY_OPTION"
        else:
            try:
                _report(config, f"{sample_tag} REMESH_QC ...")
                records.at[index, "remesh_qc"] = str(
                    stage_functions.remesh_qc(sample_tag)
                ).upper()
                _report(config, f"{sample_tag} REMESH_QC={records.at[index, 'remesh_qc']}")
            except Exception as exc:
                records.at[index, "remesh_qc"] = "ERROR"
                records.at[index, "reason"] = _append_reason(
                    records.at[index, "reason"], f"remesh_qc_error:{exc}"
                )
                _report(config, f"{sample_tag} REMESH_QC ... ERROR")

    weld_tags = records.loc[records["salvage"] == "PASS", "sample_tag"].astype(str).tolist()
    if weld_tags:
        _report(config, f"WELD_REPAIRED ... {len(weld_tags)} samples")
        try:
            _apply_weld_statuses(records, stage_functions.weld_batch(weld_tags))
        except Exception as exc:
            _mark_stage_error(records, weld_tags, "weld", "weld_error", exc)

    alignment_tags = records.loc[records["weld"] == "PASS", "sample_tag"].astype(str).tolist()
    if alignment_tags:
        _report(config, f"ALIGNMENT ... {len(alignment_tags)} samples")
        try:
            _apply_alignment_statuses(records, stage_functions.alignment_batch(alignment_tags))
        except Exception as exc:
            _mark_stage_error(records, alignment_tags, "alignment", "alignment_error", exc)

    pca_tags = records.loc[records["alignment"] == "PASS", "sample_tag"].astype(str).tolist()
    if len(pca_tags) < 2:
        pca_status, pca_result = "SKIPPED_INSUFFICIENT_SAMPLES", {"included_tags": []}
    elif config.skip_pca:
        pca_status, pca_result = "SKIPPED_BY_OPTION", {"included_tags": []}
    else:
        _report(config, f"GPA PCA ... {len(pca_tags)} aligned samples")
        try:
            pca_result = stage_functions.pca_batch()
            pca_status = str(pca_result.get("status", "ERROR")).upper()
            _apply_pca_inclusion(records, pca_tags, pca_result, "pca_included", "pca_error")
        except Exception as exc:
            _mark_pca_error(records, pca_tags, "pca_included", "pca_error", exc)
            pca_status, pca_result = "ERROR", {"included_tags": []}

    reference_pca_status, reference_pca_result = _run_fixed_reference_branch(
        records,
        config,
        stage_functions,
    )
    return PipelineResult(
        records=records,
        pca_status=pca_status,
        pca_result=pca_result,
        reference_pca_status=reference_pca_status,
        reference_pca_result=reference_pca_result,
    )


def _run_fixed_reference_branch(
    records: pd.DataFrame,
    config: PipelineConfig,
    stage_functions: StageFunctions,
) -> tuple[str, dict[str, object]]:
    """Run the optional reference-ear branch without affecting GPA states."""
    if not config.reference_sample:
        return "SKIPPED_BY_OPTION", {"included_tags": []}
    if (
        stage_functions.fixed_reference_alignment_batch is None
        or stage_functions.fixed_reference_pca_batch is None
    ):
        return "ERROR", {"included_tags": [], "reason": "reference_stage_not_configured"}

    weld_tags = records.loc[records["weld"] == "PASS", "sample_tag"].astype(str).tolist()
    if config.reference_sample not in weld_tags:
        matching = records["sample_tag"] == config.reference_sample
        records.loc[matching, "reason"] = records.loc[matching, "reason"].map(
            lambda value: _append_reason(value, "reference_sample_not_weld_pass")
        )
        return "SKIPPED_REFERENCE_NOT_WELD_PASS", {"included_tags": []}

    _report(config, f"FIXED_REFERENCE_ALIGNMENT ... {len(weld_tags)} samples")
    try:
        _apply_reference_alignment_statuses(
            records,
            stage_functions.fixed_reference_alignment_batch(weld_tags, config.reference_sample),
        )
    except Exception as exc:
        _mark_stage_error(
            records,
            weld_tags,
            "reference_alignment",
            "reference_alignment_error",
            exc,
        )
        return "ERROR", {"included_tags": []}

    reference_tags = records.loc[
        records["reference_alignment"] == "PASS", "sample_tag"
    ].astype(str).tolist()
    if len(reference_tags) < 2:
        return "SKIPPED_INSUFFICIENT_SAMPLES", {"included_tags": []}
    if config.skip_pca:
        return "SKIPPED_BY_OPTION", {"included_tags": []}

    _report(config, f"FIXED_REFERENCE PCA ... {len(reference_tags)} aligned samples")
    try:
        result = stage_functions.fixed_reference_pca_batch()
        _apply_pca_inclusion(
            records,
            reference_tags,
            result,
            "reference_pca_included",
            "reference_pca_error",
        )
        return str(result.get("status", "ERROR")).upper(), result
    except Exception as exc:
        _mark_pca_error(
            records,
            reference_tags,
            "reference_pca_included",
            "reference_pca_error",
            exc,
        )
        return "ERROR", {"included_tags": []}


def _apply_reference_alignment_statuses(records: pd.DataFrame, summary: pd.DataFrame) -> None:
    required = {"sample_tag", "status"}
    missing = required.difference(summary.columns)
    if missing:
        raise ValueError(f"reference alignment summary missing columns: {sorted(missing)}")
    for row in summary.itertuples(index=False):
        matching = records["sample_tag"] == str(row.sample_tag)
        status = str(row.status).upper()
        records.loc[matching, "reference_alignment"] = status
        if status != "PASS":
            records.loc[matching, "reason"] = records.loc[matching, "reason"].map(
                lambda value: _append_reason(value, "reference_alignment_not_pass")
            )


def _apply_pca_inclusion(
    records: pd.DataFrame,
    eligible_tags: list[str],
    pca_result: dict[str, object],
    column: str,
    error_reason: str,
) -> None:
    included_tags = {str(tag) for tag in pca_result.get("included_tags", [])}
    records.loc[records["sample_tag"].isin(included_tags), column] = "YES"
    records.loc[
        records["sample_tag"].isin(eligible_tags) & ~records["sample_tag"].isin(included_tags),
        column,
    ] = "NO"
    if str(pca_result.get("status", "ERROR")).upper() != "PASS":
        records.loc[records["sample_tag"].isin(eligible_tags), "reason"] = records.loc[
            records["sample_tag"].isin(eligible_tags), "reason"
        ].map(lambda value: _append_reason(value, error_reason))


def _mark_pca_error(
    records: pd.DataFrame,
    sample_tags: list[str],
    column: str,
    reason: str,
    error: Exception,
) -> None:
    matching = records["sample_tag"].isin(sample_tags)
    records.loc[matching, column] = "NO"
    records.loc[matching, "reason"] = records.loc[matching, "reason"].map(
        lambda value: _append_reason(value, f"{reason}:{error}")
    )


def _apply_weld_statuses(records: pd.DataFrame, summary: pd.DataFrame) -> None:
    required = {"sample_tag", "status", "pca_ready"}
    missing = required.difference(summary.columns)
    if missing:
        raise ValueError(f"weld summary missing columns: {sorted(missing)}")
    for row in summary.itertuples(index=False):
        matching = records["sample_tag"] == str(row.sample_tag)
        status = str(row.status).upper()
        records.loc[matching, "weld"] = status
        if status != "PASS" or not _as_bool(row.pca_ready):
            records.loc[matching, "reason"] = records.loc[matching, "reason"].map(
                lambda value: _append_reason(value, "weld_not_pca_ready")
            )


def _apply_alignment_statuses(records: pd.DataFrame, summary: pd.DataFrame) -> None:
    required = {"sample_tag", "status"}
    missing = required.difference(summary.columns)
    if missing:
        raise ValueError(f"alignment summary missing columns: {sorted(missing)}")
    for row in summary.itertuples(index=False):
        matching = records["sample_tag"] == str(row.sample_tag)
        status = str(row.status).upper()
        records.loc[matching, "alignment"] = status
        if status != "PASS":
            records.loc[matching, "reason"] = records.loc[matching, "reason"].map(
                lambda value: _append_reason(value, "alignment_not_pass")
            )


def _append_reason(current: object, addition: str) -> str:
    current = str(current).strip()
    return addition if not current else f"{current};{addition}"


def _mark_stage_error(
    records: pd.DataFrame,
    sample_tags: list[str],
    stage: str,
    reason: str,
    error: Exception,
) -> None:
    matching = records["sample_tag"].isin(sample_tags)
    records.loc[matching, stage] = "ERROR"
    records.loc[matching, "reason"] = records.loc[matching, "reason"].map(
        lambda value: _append_reason(value, f"{reason}:{error}")
    )


def _as_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def build_subprocess_stages(config: PipelineConfig) -> StageFunctions:
    """Create default runners that preserve the existing stage CLI contracts."""
    project_root = Path(__file__).resolve().parent.parent

    def remesh_sample(sample_tag: str) -> dict[str, str]:
        sample_id, side = _split_sample_tag(sample_tag)
        _run_command([
            sys.executable, str(project_root / "scripts" / "parameterize_ear_remesh.py"),
            "--sample_id", sample_id, "--side", side,
            "--mesh", str(config.canonical_dir / f"{sample_tag}.ply"),
            "--landmarks", str(config.canonical_dir / f"{sample_tag}_landmarks.csv"),
            "--regions", str(config.regions),
            "--out_dir", str(config.raw_dir),
            "--repaired_out_dir", str(config.repaired_dir),
            "--salvaged_out_dir", str(config.salvaged_dir),
        ], project_root)
        return {
            "remesh": _aggregate_qc_status(config.raw_dir / f"{sample_tag}_remesh_qc.csv"),
            "salvage": _aggregate_qc_status(config.salvaged_dir / f"{sample_tag}_remesh_qc.csv"),
        }

    def remesh_qc(sample_tag: str) -> str:
        _run_command([
            sys.executable, str(project_root / "scripts" / "visualize_remesh_qc.py"),
            "--samples", sample_tag,
            "--data_dir", str(config.mesh_dir.parent),
            "--regions", str(config.regions),
            "--out_dir", str(config.qc_dir),
        ], project_root)
        summary_path = config.qc_dir / "salvaged" / "qc_visualization_summary.csv"
        summary = pd.read_csv(summary_path)
        return _aggregate_status_values(summary.loc[summary["sample_tag"] == sample_tag, "status"])

    def weld_batch(sample_tags: list[str]) -> pd.DataFrame:
        _run_command([
            sys.executable, str(project_root / "scripts" / "build_whole_ear.py"),
            "--input_dir", str(config.salvaged_dir), "--regions", str(config.regions),
            "--mesh_dir", str(config.canonical_dir), "--enable_edge_repair",
            "--out_dir", str(config.weld_dir), "--samples", *sample_tags,
        ], project_root)
        summary = pd.read_csv(config.weld_dir / "whole_ear_weld_summary.csv")
        summary["sample_tag"] = summary["sample_id"].astype(str) + "_" + summary["side"].astype(str)
        return summary.loc[summary["sample_tag"].isin(sample_tags)]

    def alignment_batch(sample_tags: list[str]) -> pd.DataFrame:
        _run_command([
            sys.executable, str(project_root / "scripts" / "align_whole_ear.py"),
            "--whole_ear_dir", str(config.weld_dir),
            "--landmarks_dir", str(config.canonical_dir), "--out_dir", str(config.aligned_dir),
            "--canonical_side", config.canonical_side, "--samples", *sample_tags,
        ], project_root)
        return pd.read_csv(config.aligned_dir / "alignment_qc_summary.csv")

    def pca_batch() -> dict[str, object]:
        _run_command([
            sys.executable, str(project_root / "scripts" / "build_average_ear.py"),
            "--aligned_dir", str(config.aligned_dir), "--weld_dir", str(config.weld_dir),
            "--out_dir", str(config.pca_dir),
        ], project_root)
        manifest = pd.read_csv(config.pca_dir / "pca_input_manifest.csv")
        summary = pd.read_csv(config.pca_dir / "pca_summary.csv").iloc[0]
        return {
            "status": "PASS",
            "included_tags": manifest.loc[manifest["included"], "sample_tag"].astype(str).tolist(),
            "retained_component_count": int(summary["retained_component_count"]),
            "retained_cumulative_explained_variance_ratio": float(
                summary["retained_cumulative_explained_variance_ratio"]
            ),
        }

    def fixed_reference_alignment_batch(
        sample_tags: list[str],
        reference_sample: str,
    ) -> pd.DataFrame:
        _run_command([
            sys.executable, str(project_root / "scripts" / "align_whole_ear.py"),
            "--whole_ear_dir", str(config.weld_dir),
            "--landmarks_dir", str(config.canonical_dir),
            "--out_dir", str(config.reference_aligned_dir),
            "--alignment_mode", "fixed_reference",
            "--reference_sample", reference_sample,
            "--canonical_side", config.canonical_side,
            "--samples", *sample_tags,
        ], project_root)
        return pd.read_csv(config.reference_aligned_dir / "alignment_qc_summary.csv")

    def fixed_reference_pca_batch() -> dict[str, object]:
        _run_command([
            sys.executable, str(project_root / "scripts" / "build_average_ear.py"),
            "--aligned_dir", str(config.reference_aligned_dir),
            "--weld_dir", str(config.weld_dir),
            "--out_dir", str(config.reference_pca_dir),
        ], project_root)
        manifest = pd.read_csv(config.reference_pca_dir / "pca_input_manifest.csv")
        summary = pd.read_csv(config.reference_pca_dir / "pca_summary.csv").iloc[0]
        return {
            "status": "PASS",
            "included_tags": manifest.loc[manifest["included"], "sample_tag"].astype(str).tolist(),
            "retained_component_count": int(summary["retained_component_count"]),
            "retained_cumulative_explained_variance_ratio": float(
                summary["retained_cumulative_explained_variance_ratio"]
            ),
        }

    return StageFunctions(
        remesh_sample,
        remesh_qc,
        weld_batch,
        alignment_batch,
        pca_batch,
        fixed_reference_alignment_batch,
        fixed_reference_pca_batch,
    )


def _run_command(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def _aggregate_qc_status(path: Path) -> str:
    return _aggregate_status_values(pd.read_csv(path)["status"])


def _aggregate_status_values(values: pd.Series) -> str:
    statuses = {str(value).upper() for value in values}
    if not statuses:
        return "ERROR"
    if "ERROR" in statuses:
        return "ERROR"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARNING" in statuses:
        return "WARNING"
    return "PASS"


def _split_sample_tag(sample_tag: str) -> tuple[str, str]:
    if "_" not in sample_tag:
        raise ValueError(f"sample tag must look like <sample_id>_<side>: {sample_tag}")
    return tuple(sample_tag.rsplit("_", 1))  # type: ignore[return-value]


def _report(config: PipelineConfig, message: str) -> None:
    if config.reporter is not None:
        config.reporter(f"[Pipeline] {message}")
