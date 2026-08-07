"""Durable provenance for formal pipeline runs."""

from __future__ import annotations

from typing import Any
from datetime import datetime, timezone
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import subprocess

from ear_param.io_utils import read_csv_robust
from ear_param.pipeline import (
    PipelineConfig,
    PipelineResult,
    _effective_parallel_workers,
    discover_sample_inputs,
)


RAW_QC_POLICY = {
    "fail_unmapped_ratio": 0.2,
    "fail_on_any_degenerate_face": True,
    "warning_on_any_unmapped_point": True,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_metadata(path: Path, project_root: Path) -> dict[str, object]:
    path = Path(path)
    try:
        shown_path = str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        shown_path = str(path.resolve())
    if not path.is_file():
        return {"path": shown_path, "exists": False}
    stat = path.stat()
    return {
        "path": shown_path,
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _region_resolution(path: Path) -> dict[str, object]:
    table = read_csv_robust(Path(path))
    required_columns = {"region_id", "resolution"}
    missing_columns = required_columns.difference(table.columns)
    if missing_columns:
        raise ValueError(
            f"region table is missing required columns: {sorted(missing_columns)}"
        )
    table = table.loc[:, ["region_id", "resolution"]]
    by_region = {
        str(row.region_id): int(row.resolution)
        for row in table.itertuples(index=False)
    }
    return {
        "region_count": len(table),
        "unique_values": sorted(set(by_region.values())),
        "by_region": by_region,
    }


def _resolved_from_project(path: Path, project_root: Path) -> Path:
    path = Path(path)
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def _output_path(
    path: Path,
    *,
    project_root: Path,
    output_root: Path | None,
) -> str:
    resolved = _resolved_from_project(path, project_root)
    base = _resolved_from_project(output_root or project_root, project_root)
    try:
        return str(resolved.relative_to(base))
    except ValueError:
        if output_root is not None:
            raise ValueError(f"isolated output path escapes output_root: {resolved}")
        return str(resolved)


def _git_code_state(project_root: Path) -> dict[str, object]:
    def run(*args: str) -> str:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "unknown"
        return completed.stdout.strip() if completed.returncode == 0 else "unknown"

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    return {"commit": commit or "unknown", "dirty": status not in {"", "unknown"}}


def create_run_manifest(
    *,
    config: PipelineConfig,
    run_dir: Path,
    output_root: Path | None,
    project_root: Path,
    argv: list[str],
) -> dict[str, object]:
    """Collect JSON-safe provenance without changing pipeline inputs or outputs."""
    region_resolution = _region_resolution(config.regions)
    discovered = discover_sample_inputs(config.mesh_dir, config.landmarks_dir)
    if config.sample_tags:
        discovered = discovered[discovered["sample_tag"].isin(config.sample_tags)]
    inputs = []
    for row in discovered.itertuples(index=False):
        inputs.append({
            "sample_tag": str(row.sample_tag),
            "mesh": _file_metadata(Path(row.mesh_path), project_root),
            "landmarks": _file_metadata(Path(row.landmarks_path), project_root),
        })
    edge_controls = config.regions.parent / "edge_control_points.csv"
    return {
        "schema_version": 1,
        "run_id": Path(run_dir).name,
        "status": "RUNNING",
        "created_at": _utc_now(),
        "finished_at": None,
        "project_root": str(project_root.resolve()),
        "run_dir": str(Path(run_dir).resolve()),
        "output_scope": "isolated" if output_root is not None else "legacy_shared",
        "output_root": str(Path(output_root).resolve()) if output_root else None,
        "argv": list(argv),
        "parameters": {
            "samples": list(config.sample_tags),
            "skip_remesh_qc": config.skip_remesh_qc,
            "skip_pca": config.skip_pca,
            "disable_side_normalization": config.disable_side_normalization,
            "canonical_side": config.canonical_side,
            "mirror_axis": config.mirror_axis,
            "region_resolution": region_resolution,
            "max_salvage_unmapped_ratio": config.max_salvage_unmapped_ratio,
            "max_salvage_degenerate_ratio": config.max_salvage_degenerate_ratio,
            "raw_qc_policy": dict(RAW_QC_POLICY),
            "pca_variance_threshold": config.pca_variance_threshold,
            "alignment_mode": config.alignment_mode,
            "reference_sample": config.reference_sample,
            "parallel_workers_requested": config.parallel_workers,
            "parallel_workers_effective": _effective_parallel_workers(
                config.parallel_workers
            ),
            "remesh_backend_requested": config.remesh_backend,
        },
        "inputs": inputs,
        "config_files": {
            "region_table": _file_metadata(config.regions, project_root),
            "edge_control_points": _file_metadata(edge_controls, project_root),
        },
        "outputs": {
            name: _output_path(
                getattr(config, name),
                project_root=project_root,
                output_root=output_root,
            )
            for name in (
                "canonical_dir", "raw_dir", "repaired_dir", "salvaged_dir",
                "raw_mesh_dir", "repaired_mesh_dir", "salvaged_mesh_dir",
                "qc_dir", "weld_dir", "aligned_dir", "pca_dir",
                "reference_aligned_dir", "reference_pca_dir",
            )
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": _package_version("numpy"),
            "pandas": _package_version("pandas"),
            "cupy": _package_version("cupy"),
        },
        "code": _git_code_state(project_root),
        "result": None,
        "error": "",
    }


def write_manifest(path: Path, manifest: dict[str, object]) -> None:
    """Atomically write a UTF-8 JSON manifest."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _count(records: Any, column: str, value: str) -> int:
    return int((records[column] == value).sum()) if column in records else 0


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return str(value)


def finish_manifest(
    path: Path,
    *,
    status: str,
    result: PipelineResult | None = None,
    error: str = "",
) -> dict[str, object]:
    """Record a terminal pipeline status without leaving non-finite JSON values."""
    path = Path(path)
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    manifest["status"] = status
    manifest["finished_at"] = _utc_now()
    manifest["error"] = error
    if result is not None:
        records = result.records
        remesh_backend = _json_safe(getattr(result, "remesh_backend_summary", {}))
        if remesh_backend:
            parameters = manifest.setdefault("parameters", {})
            runtime = manifest.setdefault("runtime", {})
            parameters["remesh_backend_effective"] = remesh_backend.get("effective", "cpu")
            parameters["remesh_backend_fallback_reason"] = remesh_backend.get(
                "fallback_reason", ""
            )
            runtime["remesh_backend"] = remesh_backend
        manifest["result"] = {
            "sample_count": len(records),
            "ready_count": _count(records, "discovery", "READY"),
            "salvage_pass_count": _count(records, "salvage", "PASS"),
            "weld_pass_count": _count(records, "weld", "PASS"),
            "alignment_pass_count": _count(records, "alignment", "PASS"),
            "pca_included_count": _count(records, "pca_included", "YES"),
            "reference_alignment_pass_count": _count(
                records, "reference_alignment", "PASS"
            ),
            "reference_pca_included_count": _count(
                records, "reference_pca_included", "YES"
            ),
            "pca_status": result.pca_status,
            "reference_pca_status": result.reference_pca_status,
            "pca_result": _json_safe(result.pca_result),
            "reference_pca_result": _json_safe(result.reference_pca_result),
            "timing_record_count": len(result.stage_timings),
            "total_elapsed_seconds": round(
                sum(float(item.get("elapsed_seconds", 0.0)) for item in result.stage_timings),
                6,
            ),
        }
    write_manifest(path, manifest)
    return manifest
