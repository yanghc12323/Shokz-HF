"""Run-scoped locations for every pipeline output layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


RESERVATION_MARKER = ".pipeline-reservation"
_DEFAULT_REFERENCE_SAMPLE = "MQ_S076L"
_REFERENCE_SAMPLE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


def prepare_empty_output_root(output_root: Path) -> Path:
    root = Path(output_root)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"output root is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    try:
        (root / RESERVATION_MARKER).touch(exist_ok=False)
    except FileExistsError as exc:
        raise FileExistsError(f"output root is not empty: {root}") from exc
    return root


def _reference_sample_token(reference_sample: str | None) -> str:
    token = _DEFAULT_REFERENCE_SAMPLE if reference_sample is None else reference_sample
    if not isinstance(token, str) or _REFERENCE_SAMPLE_TOKEN.fullmatch(token) is None:
        raise ValueError(f"invalid reference sample path token: {reference_sample!r}")
    return token


@dataclass(frozen=True)
class PipelineOutputLayout:
    output_root: Path
    canonical_dir: Path
    raw_dir: Path
    repaired_dir: Path
    salvaged_dir: Path
    raw_mesh_dir: Path
    repaired_mesh_dir: Path
    salvaged_mesh_dir: Path
    qc_dir: Path
    weld_dir: Path
    aligned_dir: Path
    pca_dir: Path
    reference_aligned_dir: Path
    reference_pca_dir: Path

    @classmethod
    def from_output_root(
        cls,
        output_root: Path,
        reference_sample: str | None = None,
    ) -> "PipelineOutputLayout":
        root = Path(output_root)
        reference_token = _reference_sample_token(reference_sample)
        points = root / "parameterized_points_r24"
        remesh = root / "remesh_r24"
        whole_ear = root / "whole_ear_r24"
        return cls(
            output_root=root,
            canonical_dir=root / "canonical_inputs_r24",
            raw_dir=points / "raw",
            repaired_dir=points / "repaired",
            salvaged_dir=points / "salvaged",
            raw_mesh_dir=remesh / "raw",
            repaired_mesh_dir=remesh / "repaired",
            salvaged_mesh_dir=remesh / "salvaged",
            qc_dir=root / "remesh_qc_r24",
            weld_dir=whole_ear / "weld_repaired",
            aligned_dir=whole_ear / "aligned_gpa",
            pca_dir=root / "pca_gpa_r24",
            reference_aligned_dir=whole_ear / f"aligned_reference_{reference_token}",
            reference_pca_dir=root / f"pca_reference_{reference_token}_r24",
        )

    def pipeline_config_kwargs(self) -> dict[str, Path]:
        return {
            name: getattr(self, name)
            for name in (
                "canonical_dir", "raw_dir", "repaired_dir", "salvaged_dir",
                "raw_mesh_dir", "repaired_mesh_dir", "salvaged_mesh_dir",
                "qc_dir", "weld_dir", "aligned_dir", "pca_dir",
                "reference_aligned_dir", "reference_pca_dir",
            )
        }
