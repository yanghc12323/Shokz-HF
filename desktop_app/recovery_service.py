"""Allocate isolated recovery attempts from integrity-checked parent outputs."""

from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from pathlib import Path

from desktop_app.models import AttemptRecord, ProjectRecord, RunStatus


class RecoveryOption(StrEnum):
    WELD = "WELD"
    ALIGNMENT = "ALIGNMENT"
    PCA = "PCA"


_SOURCES = {
    RecoveryOption.WELD: "salvaged_dir",
    RecoveryOption.ALIGNMENT: "weld_dir",
    RecoveryOption.PCA: "aligned_dir",
}


class RecoveryService:
    def plan(self, parent: AttemptRecord) -> list[RecoveryOption]:
        return [option for option in RecoveryOption if self._source_path(parent, option) is not None]

    def create_attempt(self, parent: AttemptRecord, option: RecoveryOption) -> AttemptRecord:
        source = self._source_path(parent, option)
        if source is None:
            raise ValueError(f"父运行没有可验证的 {option} 恢复输入")
        attempts_root = parent.root.parent
        existing = {path.name for path in attempts_root.iterdir() if path.is_dir()}
        number = 2
        while f"attempt-{number:03d}" in existing:
            number += 1
        child = AttemptRecord.create(parent.project_root, parent.logical_run_id, f"attempt-{number:03d}", parent.attempt_id)
        child.root.mkdir(parents=True, exist_ok=False)
        manifest = parent.artifacts_dir / "manifest.json"
        provenance = {"parent_attempt": parent.attempt_id, "source_stage": option, "source_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(), "source_path": str(source)}
        self._write_json(child.root / "recovery.json", provenance)
        self._write_json(child.root / "desktop_state.json", {"logical_run_id": child.logical_run_id, "attempt_id": child.attempt_id, "parent_attempt_id": parent.attempt_id, "status": RunStatus.CREATED})
        return child

    def build_command(
        self,
        project: ProjectRecord,
        parent: AttemptRecord,
        child: AttemptRecord,
        option: RecoveryOption,
    ) -> list[str]:
        source = self._source_path(parent, option)
        if source is None or child.parent_attempt_id != parent.attempt_id:
            raise ValueError("恢复命令必须引用已验证的父 attempt 输出")
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        if option is RecoveryOption.WELD:
            return [
                str(scripts / "build_whole_ear.py"),
                "--input_dir", str(source), "--regions", str(project.region_table_path),
                "--mesh_dir", str(project.mesh_dir), "--enable_edge_repair",
                "--out_dir", str(child.artifacts_dir / "whole_ear_r24" / "weld_repaired"),
            ]
        if option is RecoveryOption.ALIGNMENT:
            return [
                str(scripts / "align_whole_ear.py"),
                "--whole_ear_dir", str(source), "--landmarks_dir", str(project.landmarks_dir),
                "--canonical_side", "L",
                "--out_dir", str(child.artifacts_dir / "whole_ear_r24" / "aligned_gpa"),
            ]
        weld_dir = self._source_path(parent, RecoveryOption.ALIGNMENT)
        if weld_dir is None:
            raise ValueError("PCA 恢复缺少已验证的 Weld 输出")
        return [
            str(scripts / "build_average_ear.py"),
            "--aligned_dir", str(source), "--weld_dir", str(weld_dir),
            "--out_dir", str(child.artifacts_dir / "pca_gpa_r24"),
        ]

    @staticmethod
    def _source_path(parent: AttemptRecord, option: RecoveryOption) -> Path | None:
        manifest_path = parent.artifacts_dir / "manifest.json"
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            claimed = payload["outputs"][_SOURCES[option]]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return None
        if not isinstance(claimed, str) or Path(claimed).is_absolute():
            return None
        root = parent.artifacts_dir.resolve()
        path = (root / claimed).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return None
        return path if path.is_dir() else None

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
