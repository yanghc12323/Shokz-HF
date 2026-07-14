"""Batch matching, alignment, and result summaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .io import write_json
from .pipeline import DEFAULT_LANDMARK_IDS, AlignmentResult, align_and_export_mesh


CSV_SUFFIXES = ("landmarks", "landmark", "markers", "marker", "points", "point")


def sample_key(path: str | Path) -> str:
    """Return the case-insensitive sample key used to pair a mesh and CSV."""

    stem = Path(path).stem.strip()
    suffix_pattern = "|".join(CSV_SUFFIXES)
    stem = re.sub(rf"(?:[-_\s]+(?:{suffix_pattern}))+$", "", stem, flags=re.IGNORECASE)
    return re.sub(r"[-_\s]+", "_", stem).strip("_").casefold()


def _unique_by_key(paths: list[str | Path], label: str) -> dict[str, Path]:
    indexed: dict[str, Path] = {}
    for value in paths:
        path = Path(value)
        key = sample_key(path)
        if not key:
            raise ValueError(f"cannot derive a sample name from {path}")
        if key in indexed:
            raise ValueError(
                f"duplicate {label} sample key {key!r}: {indexed[key]} and {path}"
            )
        indexed[key] = path
    return indexed


@dataclass(frozen=True)
class BatchItemResult:
    sample_id: str
    model_path: Path
    csv_path: Path | None
    status: str
    result: AlignmentResult | None = None
    error: str | None = None


@dataclass(frozen=True)
class BatchAlignmentResult:
    items: list[BatchItemResult]
    summary_path: Path
    unmatched_csv_paths: list[Path]

    @property
    def success_count(self) -> int:
        return sum(item.status == "success" for item in self.items)

    @property
    def failure_count(self) -> int:
        return sum(item.status == "failed" for item in self.items)


def batch_align_and_export(
    ref_mesh_path: str | Path,
    ref_landmark_csv: str | Path,
    moving_mesh_paths: list[str | Path],
    moving_landmark_csv_paths: list[str | Path],
    output_directory: str | Path,
    landmark_ids: tuple[str, ...] = DEFAULT_LANDMARK_IDS,
    auto_mirror: bool = True,
    mirror_axis: str = "x",
    center_reference: bool = True,
) -> BatchAlignmentResult:
    """Align every matched sample and continue after per-sample failures."""

    if not moving_mesh_paths:
        raise ValueError("no moving mesh files were selected")
    if not moving_landmark_csv_paths:
        raise ValueError("no moving landmark CSV files were selected")

    model_index = _unique_by_key(moving_mesh_paths, "mesh")
    csv_index = _unique_by_key(moving_landmark_csv_paths, "CSV")
    output_root = Path(output_directory)
    output_root.mkdir(parents=True, exist_ok=True)
    reference_written = False
    items: list[BatchItemResult] = []

    for key, model_path in model_index.items():
        csv_path = csv_index.get(key)
        sample_id = model_path.stem
        if csv_path is None:
            items.append(
                BatchItemResult(
                    sample_id=sample_id,
                    model_path=model_path,
                    csv_path=None,
                    status="failed",
                    error="no matching landmark CSV",
                )
            )
            continue

        sample_output = output_root / sample_id
        try:
            result = align_and_export_mesh(
                ref_mesh_path=ref_mesh_path,
                moving_mesh_path=model_path,
                ref_landmark_csv=ref_landmark_csv,
                moving_landmark_csv=csv_path,
                output_obj_path=sample_output / f"{sample_id}_aligned.obj",
                output_stl_path=sample_output / f"{sample_id}_aligned.stl",
                landmark_ids=landmark_ids,
                auto_mirror=auto_mirror,
                mirror_axis=mirror_axis,
                center_reference=center_reference,
                output_reference_obj_path=output_root / f"{Path(ref_mesh_path).stem}_centered.obj",
                output_reference_stl_path=output_root / f"{Path(ref_mesh_path).stem}_centered.stl",
                output_reference_landmarks_path=output_root / f"{Path(ref_mesh_path).stem}_landmarks_centered.csv",
                export_centered_reference=not reference_written,
            )
            reference_written = reference_written or center_reference
            items.append(
                BatchItemResult(
                    sample_id=sample_id,
                    model_path=model_path,
                    csv_path=csv_path,
                    status="success",
                    result=result,
                )
            )
        except Exception as exc:
            items.append(
                BatchItemResult(
                    sample_id=sample_id,
                    model_path=model_path,
                    csv_path=csv_path,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    unmatched_csvs = [path for key, path in csv_index.items() if key not in model_index]
    summary_path = output_root / "batch_summary.json"
    write_json(
        summary_path,
        {
            "reference_model": str(ref_mesh_path),
            "reference_landmarks": str(ref_landmark_csv),
            "center_reference": center_reference,
            "origin_landmark_ids": list(landmark_ids),
            "success_count": sum(item.status == "success" for item in items),
            "failure_count": sum(item.status == "failed" for item in items),
            "unmatched_csv_paths": [str(path) for path in unmatched_csvs],
            "items": [
                {
                    "sample_id": item.sample_id,
                    "model": str(item.model_path),
                    "landmarks": str(item.csv_path) if item.csv_path else None,
                    "status": item.status,
                    "error": item.error,
                    "rms_error": item.result.metrics["rms_error"] if item.result else None,
                    "output_obj": str(item.result.output_obj_path) if item.result else None,
                    "output_stl": str(item.result.output_stl_path) if item.result else None,
                }
                for item in items
            ],
        },
    )
    return BatchAlignmentResult(items=items, summary_path=summary_path, unmatched_csv_paths=unmatched_csvs)

