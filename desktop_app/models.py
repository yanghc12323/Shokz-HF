"""Stable data models shared by desktop services and UI components."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RunStatus(StrEnum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSE_REQUESTED = "PAUSE_REQUESTED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class StageName(StrEnum):
    REMESH = "REMESH"
    REMESH_QC = "REMESH_QC"
    WELD = "WELD"
    ALIGNMENT = "ALIGNMENT"
    GPA_PCA = "GPA_PCA"
    FIXED_REFERENCE_ALIGNMENT = "FIXED_REFERENCE_ALIGNMENT"
    FIXED_REFERENCE_PCA = "FIXED_REFERENCE_PCA"


class LayerName(StrEnum):
    RAW = "RAW"
    REPAIRED = "REPAIRED"
    SALVAGED = "SALVAGED"
    WHOLE_EAR = "WHOLE_EAR"
    AVERAGE_EAR = "AVERAGE_EAR"


@dataclass(frozen=True)
class ProjectRecord:
    root: Path
    name: str

    @property
    def inputs_dir(self) -> Path:
        return self.root / "inputs"

    @property
    def mesh_dir(self) -> Path:
        return self.inputs_dir / "clean_mesh"

    @property
    def landmarks_dir(self) -> Path:
        return self.inputs_dir / "landmarks"

    @property
    def config_dir(self) -> Path:
        return self.inputs_dir / "config"

    @property
    def region_table_path(self) -> Path:
        return self.config_dir / "region_table.csv"

@dataclass(frozen=True)
class AttemptRecord:
    project_root: Path
    logical_run_id: str
    attempt_id: str
    status: RunStatus
    parent_attempt_id: str | None = None

    @property
    def root(self) -> Path:
        return self.project_root / "runs" / self.logical_run_id / "attempts" / self.attempt_id

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts"

    @classmethod
    def create(
        cls,
        project_root: Path,
        logical_run_id: str,
        attempt_id: str,
        parent_attempt_id: str | None = None,
    ) -> "AttemptRecord":
        return cls(
            project_root=Path(project_root),
            logical_run_id=logical_run_id,
            attempt_id=attempt_id,
            status=RunStatus.CREATED,
            parent_attempt_id=parent_attempt_id,
        )


@dataclass(frozen=True)
class RunOptions:
    sample_tags: tuple[str, ...] = ()
    skip_remesh_qc: bool = False
    max_salvage_unmapped_ratio: float = 0.35
    max_salvage_degenerate_ratio: float = 0.015
    pca_variance_threshold: float = 0.75
    reference_sample: str | None = None
    qc_figure_mode: str = "all"
    alignment_mode: str = "gpa"
    parallel_workers: int = 0


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    path: Path | None = None


@dataclass(frozen=True)
class ArtifactRef:
    label: str
    path: Path
