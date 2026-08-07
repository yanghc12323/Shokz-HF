"""Shared discovery and orchestration helpers for the formal batch pipeline."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Lock
from time import perf_counter
from typing import Callable

import pandas as pd
from ear_param.canonicalization import canonicalize_sample


_MQ_SAMPLE_TAG = re.compile(r"MQ_S(\d{3})([LR])\Z")


def split_sample_tag(sample_tag: str) -> tuple[str, str]:
    """Return the display sample identifier and side for legacy or MQ tags."""
    mq_match = _MQ_SAMPLE_TAG.fullmatch(sample_tag)
    if mq_match:
        return f"MQ_S{mq_match.group(1)}", mq_match.group(2)
    if "_" in sample_tag:
        sample_id, side = sample_tag.rsplit("_", 1)
        if side.upper() in {"L", "R"}:
            return sample_id, side.upper()
    raise ValueError(f"sample tag must end in _L/_R or use MQ_S###L/R: {sample_tag}")


def compose_sample_tag(sample_id: str, side: str) -> str:
    """Rebuild a formal sample tag from fields stored in result CSV files."""
    normalized_side = str(side).upper()
    normalized_id = str(sample_id)
    if re.fullmatch(r"MQ_S\d{3}", normalized_id) and normalized_side in {"L", "R"}:
        return f"{normalized_id}{normalized_side}"
    return f"{normalized_id}_{normalized_side}"


def landmark_tag_for_sample(sample_tag: str) -> str:
    """Translate an MQ mesh tag to its landmark tag; preserve legacy tags."""
    mq_match = _MQ_SAMPLE_TAG.fullmatch(sample_tag)
    if mq_match:
        return f"T{mq_match.group(1)}_{mq_match.group(2)}"
    return sample_tag


def discover_sample_inputs(mesh_dir: Path, landmarks_dir: Path) -> pd.DataFrame:
    """Resolve actual mesh/landmark paths while keeping model names as sample tags."""
    mesh_dir = Path(mesh_dir)
    landmarks_dir = Path(landmarks_dir)
    meshes = {
        path.stem: path for path in mesh_dir.glob("*.ply")
    } if mesh_dir.exists() else {}
    landmarks = {
        path.name.removesuffix("_landmarks.csv"): path
        for path in landmarks_dir.glob("*_landmarks.csv")
    } if landmarks_dir.exists() else {}

    records: list[dict[str, object]] = []
    consumed_landmarks: set[str] = set()
    for sample_tag, mesh_path in sorted(meshes.items()):
        landmark_tag = landmark_tag_for_sample(sample_tag)
        landmarks_path = landmarks.get(landmark_tag)
        if landmarks_path is None:
            discovery, reason = "MISSING_LANDMARKS", "missing_landmarks"
            landmarks_path = landmarks_dir / f"{landmark_tag}_landmarks.csv"
        else:
            discovery, reason = "READY", ""
            consumed_landmarks.add(landmark_tag)
        try:
            sample_id, side = split_sample_tag(sample_tag)
        except ValueError:
            sample_id, side = sample_tag, ""
        records.append({
            "sample_tag": sample_tag,
            "discovery": discovery,
            "reason": reason,
            "sample_id": sample_id,
            "side": side,
            "mesh_path": mesh_path,
            "landmarks_path": landmarks_path,
        })

    for landmark_tag, landmarks_path in sorted(landmarks.items()):
        if landmark_tag in consumed_landmarks:
            continue
        mesh_path = mesh_dir / f"{landmark_tag}.ply"
        try:
            sample_id, side = split_sample_tag(landmark_tag)
        except ValueError:
            sample_id, side = landmark_tag, ""
        records.append({
            "sample_tag": landmark_tag,
            "discovery": "MISSING_MESH",
            "reason": "missing_mesh",
            "sample_id": sample_id,
            "side": side,
            "mesh_path": mesh_path,
            "landmarks_path": landmarks_path,
        })

    columns = [
        "sample_tag", "discovery", "reason", "sample_id", "side", "mesh_path",
        "landmarks_path",
    ]
    return pd.DataFrame(records, columns=columns).sort_values(
        "sample_tag", kind="stable"
    ).reset_index(drop=True)


def discover_samples(mesh_dir: Path, landmarks_dir: Path) -> pd.DataFrame:
    """Return every mesh/landmark tag and its paired-input readiness state."""
    return discover_sample_inputs(mesh_dir, landmarks_dir).loc[
        :, ["sample_tag", "discovery", "reason"]
    ].copy()


@dataclass(frozen=True)
class PipelineConfig:
    """Input locations required before the stage-specific options are applied."""

    mesh_dir: Path
    landmarks_dir: Path
    regions: Path = Path("config/region_table.csv")
    raw_dir: Path = Path("output/parameterized_points_r24/raw")
    repaired_dir: Path = Path("output/parameterized_points_r24/repaired")
    salvaged_dir: Path = Path("output/parameterized_points_r24/salvaged")
    raw_mesh_dir: Path = Path("output/remesh_r24/raw")
    repaired_mesh_dir: Path = Path("output/remesh_r24/repaired")
    salvaged_mesh_dir: Path = Path("output/remesh_r24/salvaged")
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
    max_salvage_degenerate_ratio: float = 0.03
    sample_tags: tuple[str, ...] = ()
    skip_remesh_qc: bool = False
    skip_pca: bool = False
    reference_sample: str | None = None
    reporter: Callable[[str], None] | None = None
    max_salvage_unmapped_ratio: float = 0.45
    pca_variance_threshold: float = 0.75
    event_reporter: Callable[[str, dict[str, object]], None] | None = None
    checkpoint: Callable[[], None] | None = None
    event_log: Path | None = None
    qc_figure_mode: str = "all"
    alignment_mode: str = "gpa"
    parallel_workers: int = 1
    weld_warning_mm: float = 0.5
    weld_fail_mm: float = 1.5
    remesh_backend: str = "cpu"


def _effective_parallel_workers(requested: int) -> int:
    """Resolve desktop automatic mode without oversubscribing local workstations."""
    if requested < 0:
        raise ValueError("parallel_workers must be zero or a positive integer")
    if requested:
        return requested
    return min(4, max(1, (os.cpu_count() or 1) - 1))


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
    remesh_events: Callable[[str], list[dict[str, object]]] | None = None
    poll_remesh_events: Callable[[str], list[dict[str, object]]] | None = None
    finalize_remesh_qc: Callable[[], None] | None = None


@dataclass(frozen=True)
class PipelineResult:
    """Sample-level stage states plus final PCA status."""

    records: pd.DataFrame
    pca_status: str
    pca_result: dict[str, object]
    reference_pca_status: str = "SKIPPED_BY_OPTION"
    reference_pca_result: dict[str, object] = field(default_factory=dict)
    stage_timings: list[dict[str, object]] = field(default_factory=list)
    remesh_backend_summary: dict[str, object] = field(default_factory=dict)


def write_pipeline_outputs(result: PipelineResult, run_dir: Path) -> None:
    """Write durable batch records, aggregate counts, and a plain-text log."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    result.records.to_csv(run_dir / "pipeline_batch_summary.csv", index=False)
    pd.DataFrame(
        result.stage_timings,
        columns=["stage", "sample_tag", "elapsed_seconds", "status"],
    ).to_csv(run_dir / "pipeline_timing_summary.csv", index=False)
    _write_sample_processing_time_text(result.stage_timings, run_dir / "sample_processing_time.txt")
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


def _write_sample_processing_time_text(
    stage_timings: list[dict[str, object]],
    out_path: Path,
) -> None:
    """Write a compact operator-facing per-sample time summary."""
    timings = pd.DataFrame(
        stage_timings,
        columns=["stage", "sample_tag", "elapsed_seconds", "status"],
    )
    per_sample = timings.loc[timings["sample_tag"].fillna("").astype(str).ne("")].copy()
    lines = [
        "样本处理耗时汇总（Remesh 与 Remesh QC）",
        "样本\tRemesh(秒)\tQC(秒)\t总耗时(秒)\t最终阶段状态",
    ]
    if per_sample.empty:
        lines.append("本次运行没有可汇总的样本阶段耗时。")
    else:
        for sample_tag, group in per_sample.groupby("sample_tag", sort=True):
            remesh = group.loc[group["stage"] == "REMESH", "elapsed_seconds"].sum()
            qc = group.loc[group["stage"] == "REMESH_QC", "elapsed_seconds"].sum()
            total = group["elapsed_seconds"].sum()
            status = str(group.iloc[-1]["status"])
            lines.append(f"{sample_tag}\t{remesh:.2f}\t{qc:.2f}\t{total:.2f}\t{status}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_pipeline(
    config: PipelineConfig,
    *,
    stage_functions: StageFunctions,
) -> PipelineResult:
    """Run staged sample processing while isolating failures to one sample."""
    if config.alignment_mode not in {"gpa", "fixed-reference"}:
        raise ValueError(f"unsupported alignment mode: {config.alignment_mode!r}")
    if config.remesh_backend not in {"cpu", "cuda", "auto"}:
        raise ValueError(f"unsupported remesh backend: {config.remesh_backend!r}")
    if config.alignment_mode == "fixed-reference" and not config.reference_sample:
        raise ValueError("fixed-reference alignment requires reference_sample")
    discovered_inputs = discover_sample_inputs(config.mesh_dir, config.landmarks_dir)
    records = discovered_inputs.loc[:, ["sample_tag", "discovery", "reason"]].copy()
    if config.sample_tags:
        records = records[records["sample_tag"].isin(config.sample_tags)].reset_index(drop=True)
    inputs_by_tag = {
        str(row.sample_tag): row
        for row in discovered_inputs.itertuples(index=False)
    }
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
            source = inputs_by_tag[sample_tag]
            canonical = canonicalize_sample(
                sample_tag,
                Path(source.mesh_path),
                Path(source.landmarks_path),
                config.canonical_dir,
                canonical_side=config.canonical_side,
                mirror_axis=config.mirror_axis,
            )
            records.at[index, "source_side"] = canonical.source_side
            records.at[index, "canonical_side"] = canonical.canonical_side
            records.at[index, "mirrored"] = canonical.mirrored
            records.at[index, "mirror_axis"] = canonical.mirror_axis
        except Exception as exc:
            records.at[index, "discovery"] = "INVALID_SIDE"
            records.at[index, "reason"] = _append_reason(row["reason"], f"canonicalization_error:{exc}")

    stage_timings = _run_remesh_and_qc_batch(records, config, stage_functions)

    weld_tags = records.loc[records["salvage"] == "PASS", "sample_tag"].astype(str).tolist()
    if weld_tags:
        _checkpoint(config)
        _report(config, f"WELD_REPAIRED ... {len(weld_tags)} samples")
        _emit(config, "stage_started", stage="WELD", sample_count=len(weld_tags))
        stage_started = perf_counter()
        try:
            _apply_weld_statuses(records, stage_functions.weld_batch(weld_tags))
        except Exception as exc:
            _mark_stage_error(records, weld_tags, "weld", "weld_error", exc)
            _emit(config, "stage_error", stage="WELD", error=str(exc))
            stage_timings.append(_timing_record("WELD", "", stage_started, "ERROR"))
        else:
            status = _aggregate_status_values(records.loc[records["sample_tag"].isin(weld_tags), "weld"])
            _emit(
                config,
                "stage_finished",
                stage="WELD",
                status=status,
            )
            stage_timings.append(_timing_record("WELD", "", stage_started, status))

    if config.alignment_mode == "fixed-reference":
        reference_pca_status, reference_pca_result = _run_fixed_reference_branch(
            records, config, stage_functions, stage_timings
        )
        _promote_fixed_reference_results(records)
        pca_status, pca_result = reference_pca_status, reference_pca_result
    else:
        alignment_tags = records.loc[records["weld"] == "PASS", "sample_tag"].astype(str).tolist()
        if alignment_tags:
            _checkpoint(config)
            _report(config, f"ALIGNMENT ... {len(alignment_tags)} samples")
            _emit(config, "stage_started", stage="ALIGNMENT", sample_count=len(alignment_tags))
            stage_started = perf_counter()
            try:
                _apply_alignment_statuses(records, stage_functions.alignment_batch(alignment_tags))
            except Exception as exc:
                _mark_stage_error(records, alignment_tags, "alignment", "alignment_error", exc)
                _emit(config, "stage_error", stage="ALIGNMENT", error=str(exc))
                stage_timings.append(_timing_record("ALIGNMENT", "", stage_started, "ERROR"))
            else:
                status = _aggregate_status_values(
                    records.loc[records["sample_tag"].isin(alignment_tags), "alignment"]
                )
                _emit(
                    config,
                    "stage_finished",
                    stage="ALIGNMENT",
                    status=status,
                )
                stage_timings.append(_timing_record("ALIGNMENT", "", stage_started, status))

        pca_tags = records.loc[records["alignment"] == "PASS", "sample_tag"].astype(str).tolist()
        if len(pca_tags) < 2:
            pca_status, pca_result = "SKIPPED_INSUFFICIENT_SAMPLES", {"included_tags": []}
        elif config.skip_pca:
            pca_status, pca_result = "SKIPPED_BY_OPTION", {"included_tags": []}
        else:
            _checkpoint(config)
            _report(config, f"GPA PCA ... {len(pca_tags)} aligned samples")
            _emit(config, "stage_started", stage="GPA_PCA", sample_count=len(pca_tags))
            stage_started = perf_counter()
            try:
                pca_result = stage_functions.pca_batch()
                pca_status = str(pca_result.get("status", "ERROR")).upper()
                _apply_pca_inclusion(records, pca_tags, pca_result, "pca_included", "pca_error")
            except Exception as exc:
                _mark_pca_error(records, pca_tags, "pca_included", "pca_error", exc)
                pca_status, pca_result = "ERROR", {"included_tags": []}
                _emit(config, "stage_error", stage="GPA_PCA", error=str(exc))
                stage_timings.append(_timing_record("GPA_PCA", "", stage_started, "ERROR"))
            else:
                _emit(config, "stage_finished", stage="GPA_PCA", status=pca_status)
                stage_timings.append(_timing_record("GPA_PCA", "", stage_started, pca_status))

        reference_pca_status, reference_pca_result = _run_fixed_reference_branch(
            records, config, stage_functions, stage_timings
        )
    return PipelineResult(
        records=records,
        pca_status=pca_status,
        pca_result=pca_result,
        reference_pca_status=reference_pca_status,
        reference_pca_result=reference_pca_result,
        stage_timings=stage_timings,
        remesh_backend_summary=_summarize_remesh_backends(config),
    )


def _run_remesh_and_qc_batch(
    records: pd.DataFrame,
    config: PipelineConfig,
    stage_functions: StageFunctions,
) -> list[dict[str, object]]:
    """Run independent sample work concurrently and commit states on this thread."""
    ready_items = [
        (int(index), str(row["sample_tag"]))
        for index, row in records.iterrows()
        if row["discovery"] == "READY"
    ]
    if not ready_items:
        return []

    worker_count = min(_effective_parallel_workers(config.parallel_workers), len(ready_items))
    timings: list[dict[str, object]] = []
    pending = iter(ready_items)
    in_flight: dict[Future[dict[str, object]], tuple[int, str]] = {}
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="ear-remesh") as executor:
        while True:
            while len(in_flight) < worker_count:
                try:
                    index, sample_tag = next(pending)
                except StopIteration:
                    break
                _checkpoint(config)
                _report(config, f"{sample_tag} REMESH ...")
                _emit(config, "sample_started", sample_tag=sample_tag, stage="REMESH")
                future = executor.submit(_run_sample_remesh_and_qc, sample_tag, config, stage_functions)
                in_flight[future] = (index, sample_tag)

            if not in_flight:
                break

            _relay_in_flight_remesh_events(config, stage_functions, in_flight.values())
            completed, _ = wait(in_flight, timeout=0.1, return_when=FIRST_COMPLETED)
            _relay_in_flight_remesh_events(config, stage_functions, in_flight.values())
            if not completed:
                continue
            for future in completed:
                index, sample_tag = in_flight.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # Defensive boundary for unexpected worker failures.
                    result = {
                        "sample_tag": sample_tag,
                        "remesh_error": str(exc),
                        "timings": [{
                            "stage": "REMESH",
                            "sample_tag": sample_tag,
                            "elapsed_seconds": 0.0,
                            "status": "ERROR",
                        }],
                    }
                _relay_remesh_events(config, stage_functions, sample_tag)
                timings.extend(result.get("timings", []))
                _apply_sample_remesh_result(records, index, config, result)
    if stage_functions.finalize_remesh_qc is not None:
        stage_functions.finalize_remesh_qc()
    return timings


def _run_sample_remesh_and_qc(
    sample_tag: str,
    config: PipelineConfig,
    stage_functions: StageFunctions,
) -> dict[str, object]:
    """Do one sample's independent Remesh and QC without shared record mutation."""
    timings: list[dict[str, object]] = []
    remesh_started = perf_counter()
    try:
        outcome = stage_functions.remesh_sample(sample_tag)
    except Exception as exc:
        timings.append(_timing_record("REMESH", sample_tag, remesh_started, "ERROR"))
        return {"sample_tag": sample_tag, "remesh_error": str(exc), "timings": timings}

    remesh_status = str(outcome.get("remesh", "ERROR")).upper()
    salvage_status = str(outcome.get("salvage", "SKIPPED")).upper()
    timings.append(_timing_record("REMESH", sample_tag, remesh_started, salvage_status))
    result: dict[str, object] = {
        "sample_tag": sample_tag,
        "remesh_status": remesh_status,
        "salvage_status": salvage_status,
        "timings": timings,
    }
    if config.skip_remesh_qc:
        result["remesh_qc_status"] = "SKIPPED_BY_OPTION"
        return result

    _checkpoint(config)
    qc_started = perf_counter()
    try:
        result["remesh_qc_status"] = str(stage_functions.remesh_qc(sample_tag)).upper()
    except Exception as exc:
        result["remesh_qc_error"] = str(exc)
        result["remesh_qc_status"] = "ERROR"
    timings.append(
        _timing_record("REMESH_QC", sample_tag, qc_started, str(result["remesh_qc_status"]))
    )
    return result


def _timing_record(stage: str, sample_tag: str, started: float, status: str) -> dict[str, object]:
    return {
        "stage": stage,
        "sample_tag": sample_tag,
        "elapsed_seconds": round(perf_counter() - started, 6),
        "status": status,
    }


def _relay_remesh_events(
    config: PipelineConfig,
    stage_functions: StageFunctions,
    sample_tag: str,
) -> None:
    if stage_functions.remesh_events is None:
        return
    _relay_event_payloads(config, stage_functions.remesh_events(sample_tag))


def _relay_in_flight_remesh_events(
    config: PipelineConfig,
    stage_functions: StageFunctions,
    in_flight_items: object,
) -> None:
    if stage_functions.poll_remesh_events is None:
        return
    for _, sample_tag in in_flight_items:  # type: ignore[union-attr]
        _relay_event_payloads(config, stage_functions.poll_remesh_events(sample_tag))


def _relay_event_payloads(
    config: PipelineConfig,
    payloads: list[dict[str, object]],
) -> None:
    for payload in payloads:
        event = str(payload.get("event", ""))
        if not event:
            continue
        fields = {
            str(key): value
            for key, value in payload.items()
            if key not in {"event", "timestamp"}
        }
        _emit(config, event, **fields)


def _read_jsonl_events_incrementally(
    path: Path,
    offset: int,
) -> tuple[list[dict[str, object]], int]:
    """Read complete JSONL records appended after *offset* without consuming a partial line."""
    path = Path(path)
    if not path.is_file():
        return [], offset
    with path.open("rb") as stream:
        stream.seek(offset)
        chunk = stream.read()
    events: list[dict[str, object]] = []
    consumed = 0
    for line in chunk.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            break
        consumed += len(line)
        try:
            payload = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events, offset + consumed


def _apply_sample_remesh_result(
    records: pd.DataFrame,
    index: int,
    config: PipelineConfig,
    result: dict[str, object],
) -> None:
    sample_tag = str(result["sample_tag"])
    if "remesh_error" in result:
        error = str(result["remesh_error"])
        records.at[index, "remesh"] = "ERROR"
        records.at[index, "reason"] = _append_reason(
            records.at[index, "reason"], f"remesh_error:{error}"
        )
        _report(config, f"{sample_tag} REMESH ... ERROR")
        _emit(config, "sample_finished", sample_tag=sample_tag, stage="REMESH", status="ERROR", error=error)
        return

    remesh_status = str(result["remesh_status"])
    salvage_status = str(result["salvage_status"])
    records.at[index, "remesh"] = remesh_status
    records.at[index, "salvage"] = salvage_status
    _report(config, f"{sample_tag} REMESH={remesh_status} SALVAGE={salvage_status}")
    _emit(
        config,
        "sample_finished",
        sample_tag=sample_tag,
        stage="REMESH",
        status=salvage_status,
        remesh_status=remesh_status,
    )
    if salvage_status != "PASS":
        records.at[index, "reason"] = _append_reason(records.at[index, "reason"], "salvage_not_pass")
    qc_status = str(result.get("remesh_qc_status", "SKIPPED_BY_OPTION"))
    records.at[index, "remesh_qc"] = qc_status
    if qc_status == "SKIPPED_BY_OPTION":
        return
    _report(config, f"{sample_tag} REMESH_QC={qc_status}")
    _emit(config, "sample_started", sample_tag=sample_tag, stage="REMESH_QC")
    if "remesh_qc_error" in result:
        error = str(result["remesh_qc_error"])
        records.at[index, "reason"] = _append_reason(
            records.at[index, "reason"], f"remesh_qc_error:{error}"
        )
        _emit(config, "sample_finished", sample_tag=sample_tag, stage="REMESH_QC", status="ERROR", error=error)
        return
    _emit(config, "sample_finished", sample_tag=sample_tag, stage="REMESH_QC", status=qc_status)


def _promote_fixed_reference_results(records: pd.DataFrame) -> None:
    """Expose the selected fixed-reference branch through the primary result columns."""
    records["alignment"] = records["reference_alignment"]
    records["pca_included"] = records["reference_pca_included"]


def _run_fixed_reference_branch(
    records: pd.DataFrame,
    config: PipelineConfig,
    stage_functions: StageFunctions,
    stage_timings: list[dict[str, object]],
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
    _checkpoint(config)
    _emit(config, "stage_started", stage="FIXED_REFERENCE_ALIGNMENT", sample_count=len(weld_tags))
    stage_started = perf_counter()
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
        _emit(config, "stage_error", stage="FIXED_REFERENCE_ALIGNMENT", error=str(exc))
        stage_timings.append(_timing_record("FIXED_REFERENCE_ALIGNMENT", "", stage_started, "ERROR"))
        return "ERROR", {"included_tags": []}
    status = _aggregate_status_values(
        records.loc[records["sample_tag"].isin(weld_tags), "reference_alignment"]
    )
    _emit(
        config,
        "stage_finished",
        stage="FIXED_REFERENCE_ALIGNMENT",
        status=status,
    )
    stage_timings.append(_timing_record("FIXED_REFERENCE_ALIGNMENT", "", stage_started, status))

    reference_tags = records.loc[
        records["reference_alignment"] == "PASS", "sample_tag"
    ].astype(str).tolist()
    if len(reference_tags) < 2:
        return "SKIPPED_INSUFFICIENT_SAMPLES", {"included_tags": []}
    if config.skip_pca:
        return "SKIPPED_BY_OPTION", {"included_tags": []}

    _report(config, f"FIXED_REFERENCE PCA ... {len(reference_tags)} aligned samples")
    _checkpoint(config)
    _emit(config, "stage_started", stage="FIXED_REFERENCE_PCA", sample_count=len(reference_tags))
    stage_started = perf_counter()
    try:
        result = stage_functions.fixed_reference_pca_batch()
        _apply_pca_inclusion(
            records,
            reference_tags,
            result,
            "reference_pca_included",
            "reference_pca_error",
        )
        status = str(result.get("status", "ERROR")).upper()
        _emit(config, "stage_finished", stage="FIXED_REFERENCE_PCA", status=status)
        stage_timings.append(_timing_record("FIXED_REFERENCE_PCA", "", stage_started, status))
        return status, result
    except Exception as exc:
        _mark_pca_error(
            records,
            reference_tags,
            "reference_pca_included",
            "reference_pca_error",
            exc,
        )
        _emit(config, "stage_error", stage="FIXED_REFERENCE_PCA", error=str(exc))
        stage_timings.append(_timing_record("FIXED_REFERENCE_PCA", "", stage_started, "ERROR"))
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
    child_event_logs: dict[str, Path] = {}
    child_event_offsets: dict[str, int] = {}
    child_event_lock = Lock()
    qc_summary_tags: set[str] = set()
    qc_summary_lock = Lock()

    def child_event_log(sample_tag: str) -> Path | None:
        if config.event_log is None:
            return None
        if _effective_parallel_workers(config.parallel_workers) <= 1:
            return config.event_log
        path = config.event_log.parent / "remesh_events" / f"{sample_tag}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with child_event_lock:
            child_event_logs[sample_tag] = path
            child_event_offsets[sample_tag] = 0
        return path

    def remesh_sample(sample_tag: str) -> dict[str, str]:
        sample_id, side = _split_sample_tag(sample_tag)
        event_log = child_event_log(sample_tag)
        _run_command([
            sys.executable, str(project_root / "scripts" / "parameterize_ear_remesh.py"),
            "--sample_id", sample_id, "--side", side,
            "--sample-tag", sample_tag,
            "--mesh", str(config.canonical_dir / f"{sample_tag}.ply"),
            "--landmarks", str(config.canonical_dir / f"{sample_tag}_landmarks.csv"),
            "--regions", str(config.regions),
            "--salvaged_out_dir", str(config.salvaged_dir),
            "--salvaged_mesh_out_dir", str(config.salvaged_mesh_dir),
            "--max_salvage_unmapped_ratio", str(config.max_salvage_unmapped_ratio),
            "--max_salvage_degenerate_ratio", str(config.max_salvage_degenerate_ratio),
            "--remesh-backend", config.remesh_backend,
            *( ["--event-log", str(event_log)] if event_log else [] ),
        ], project_root)
        salvaged_qc_path = config.salvaged_dir / f"{sample_tag}_remesh_qc.csv"
        return {
            "remesh": _aggregate_raw_status_from_salvaged_qc(salvaged_qc_path),
            "salvage": _aggregate_qc_status(salvaged_qc_path),
        }

    def remesh_qc(sample_tag: str) -> str:
        summary_dir: Path | None = None
        if _effective_parallel_workers(config.parallel_workers) > 1:
            summary_dir = config.qc_dir / "_sample_summaries" / sample_tag
            with qc_summary_lock:
                qc_summary_tags.add(sample_tag)
        _run_command([
            sys.executable, str(project_root / "scripts" / "visualize_remesh_qc.py"),
            "--samples", sample_tag,
            "--data_dir", str(config.mesh_dir.parent),
            "--regions", str(config.regions),
            "--out_dir", str(config.qc_dir),
            *( ["--summary-dir", str(summary_dir)] if summary_dir else [] ),
            "--figure-mode", config.qc_figure_mode,
            "--max_salvage_unmapped_ratio", str(config.max_salvage_unmapped_ratio),
            "--max_salvage_degenerate_ratio", str(config.max_salvage_degenerate_ratio),
        ], project_root)
        summary_root = summary_dir or config.qc_dir
        summary_path = summary_root / "salvaged" / "qc_visualization_summary.csv"
        summary = pd.read_csv(summary_path)
        return _aggregate_status_values(summary.loc[summary["sample_tag"] == sample_tag, "status"])

    def finalize_remesh_qc() -> None:
        with qc_summary_lock:
            sample_tags = sorted(qc_summary_tags)
        if sample_tags:
            _merge_private_qc_summaries(config.qc_dir, sample_tags)

    def weld_batch(sample_tags: list[str]) -> pd.DataFrame:
        _run_command([
            sys.executable, str(project_root / "scripts" / "build_whole_ear.py"),
            "--input_dir", str(config.salvaged_dir), "--regions", str(config.regions),
            "--mesh_dir", str(config.canonical_dir), "--enable_edge_repair",
            "--weld_warning_mm", str(config.weld_warning_mm),
            "--weld_fail_mm", str(config.weld_fail_mm),
            "--out_dir", str(config.weld_dir), "--samples", *sample_tags,
        ], project_root)
        summary = pd.read_csv(config.weld_dir / "whole_ear_weld_summary.csv")
        summary["sample_tag"] = [
            compose_sample_tag(sample_id, side)
            for sample_id, side in zip(summary["sample_id"], summary["side"])
        ]
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
            "--variance_threshold", str(config.pca_variance_threshold),
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
            "--variance_threshold", str(config.pca_variance_threshold),
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

    def poll_remesh_events(sample_tag: str) -> list[dict[str, object]]:
        with child_event_lock:
            path = child_event_logs.get(sample_tag)
            offset = child_event_offsets.get(sample_tag, 0)
        if path is None:
            return []
        events, next_offset = _read_jsonl_events_incrementally(path, offset)
        with child_event_lock:
            if child_event_logs.get(sample_tag) == path:
                child_event_offsets[sample_tag] = next_offset
        return events

    def remesh_events(sample_tag: str) -> list[dict[str, object]]:
        events = poll_remesh_events(sample_tag)
        with child_event_lock:
            child_event_logs.pop(sample_tag, None)
            child_event_offsets.pop(sample_tag, None)
        return events

    return StageFunctions(
        remesh_sample,
        remesh_qc,
        weld_batch,
        alignment_batch,
        pca_batch,
        fixed_reference_alignment_batch,
        fixed_reference_pca_batch,
        remesh_events,
        poll_remesh_events,
        finalize_remesh_qc,
    )


def _merge_private_qc_summaries(qc_dir: Path, sample_tags: list[str]) -> None:
    """Restore legacy QC summary files after parallel sample-specific writes."""
    qc_dir = Path(qc_dir)
    for layer in ("raw", "repaired", "salvaged"):
        tables: list[pd.DataFrame] = []
        for sample_tag in sorted(sample_tags):
            path = qc_dir / "_sample_summaries" / sample_tag / layer / "qc_visualization_summary.csv"
            if not path.is_file():
                raise FileNotFoundError(f"missing private QC summary: {path}")
            tables.append(pd.read_csv(path))
        combined = pd.concat(tables, ignore_index=True)
        sort_columns = [name for name in ("sample_tag", "region_id") if name in combined.columns]
        if sort_columns:
            combined = combined.sort_values(sort_columns, kind="stable").reset_index(drop=True)
        destination = qc_dir / layer / "qc_visualization_summary.csv"
        destination.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(destination, index=False)


def _run_command(command: list[str], cwd: Path) -> None:
    kwargs: dict[str, object] = {"cwd": cwd, "check": True}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.run(command, **kwargs)


def _aggregate_qc_status(path: Path) -> str:
    return _aggregate_status_values(pd.read_csv(path)["status"])


def _aggregate_raw_status_from_salvaged_qc(path: Path) -> str:
    """Recover raw QC status from the sole retained per-sample Salvaged QC file."""
    qc = pd.read_csv(path)
    column = "raw_status" if "raw_status" in qc.columns else "status"
    return _aggregate_status_values(qc[column])


def _summarize_remesh_backends(config: PipelineConfig) -> dict[str, object]:
    """Aggregate per-sample backend diagnostics without requiring CuPy in CPU runs."""
    reports: list[dict[str, object]] = []
    for path in sorted(Path(config.salvaged_dir).glob("*_remesh_backend.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            reports.append(payload)

    if not reports:
        from ear_param.remesh_backend import backend_diagnostics

        return backend_diagnostics(config.remesh_backend)

    effective_values = {
        str(report.get("effective", "cpu")) for report in reports
    }
    fallback_reasons = sorted({
        str(report.get("fallback_reason", ""))
        for report in reports
        if str(report.get("fallback_reason", ""))
    })
    return {
        "requested": config.remesh_backend,
        "effective": next(iter(effective_values)) if len(effective_values) == 1 else "mixed",
        "fallback_reason": " | ".join(fallback_reasons),
        "gpu_peak_bytes": max(
            (int(report.get("gpu_peak_bytes", 0) or 0) for report in reports),
            default=0,
        ),
        "sample_count": len(reports),
        "gpu_timing": _aggregate_gpu_timing(reports),
    }


def _aggregate_gpu_timing(reports: list[dict[str, object]]) -> dict[str, float | int]:
    """Add per-sample GPU timing counters into the run-level manifest summary."""
    timing_keys = (
        "lock_wait_seconds",
        "host_to_device_seconds",
        "harmonic_solve_seconds",
        "uv_lookup_seconds",
        "map_to_3d_seconds",
        "device_to_host_seconds",
        "region_wall_seconds",
    )
    summary: dict[str, float | int] = {
        "region_count": 0,
        **{key: 0.0 for key in timing_keys},
    }
    for report in reports:
        timing = report.get("gpu_timing")
        if not isinstance(timing, dict):
            continue
        try:
            summary["region_count"] = int(summary["region_count"]) + int(
                timing.get("region_count", 0) or 0
            )
        except (TypeError, ValueError):
            pass
        for key in timing_keys:
            try:
                value = float(timing.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if value >= 0.0:
                summary[key] = float(summary[key]) + value
    return {
        "region_count": int(summary["region_count"]),
        **{key: round(float(summary[key]), 6) for key in timing_keys},
    }


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
    return split_sample_tag(sample_tag)


def _report(config: PipelineConfig, message: str) -> None:
    if config.reporter is not None:
        config.reporter(f"[Pipeline] {message}")


def _emit(config: PipelineConfig, event: str, **fields: object) -> None:
    if config.event_reporter is not None:
        config.event_reporter(event, fields)


def _checkpoint(config: PipelineConfig) -> None:
    if config.checkpoint is not None:
        config.checkpoint()
