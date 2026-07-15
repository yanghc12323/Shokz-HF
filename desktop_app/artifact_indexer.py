"""Read completed run artifacts without trusting paths from their manifest."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pandas as pd

from desktop_app.models import ArtifactRef, AttemptRecord


class ArtifactIntegrityError(ValueError):
    """Raised when an artifact manifest is incomplete or leaves its attempt root."""


@dataclass
class ArtifactIndex:
    attempt: AttemptRecord
    manifest: dict[str, object]
    output_dirs: dict[str, Path]
    batch_summary: pd.DataFrame
    run_summary: pd.DataFrame
    weld_summary: pd.DataFrame
    alignment_summary: pd.DataFrame
    pca_input_manifest: pd.DataFrame
    evidence: tuple[ArtifactRef, ...]


class ArtifactIndexer:
    """Build a safe, read-only view of a completed pipeline attempt."""

    _ROOT_EVIDENCE = (
        ("批处理汇总", "pipeline_batch_summary.csv"),
        ("运行汇总", "pipeline_run_summary.csv"),
        ("运行日志", "pipeline_run.log"),
    )

    def index(self, attempt: AttemptRecord) -> ArtifactIndex:
        root = attempt.artifacts_dir.resolve()
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise ArtifactIntegrityError(f"缺少运行清单: {manifest_path}")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError(f"无法读取运行清单: {manifest_path}") from exc
        if str(manifest.get("status", "")).upper() != "COMPLETED":
            raise ArtifactIntegrityError("仅可复核状态为 COMPLETED 的运行结果")
        if manifest.get("output_scope") != "isolated":
            raise ArtifactIntegrityError("结果清单不是隔离输出，拒绝加载")

        output_dirs = self._output_dirs(root, manifest)
        evidence: list[ArtifactRef] = [ArtifactRef("运行清单", manifest_path)]
        for label, name in self._ROOT_EVIDENCE:
            path = root / name
            if path.is_file():
                evidence.append(ArtifactRef(label, path))

        batch_path = root / "pipeline_batch_summary.csv"
        run_path = root / "pipeline_run_summary.csv"
        batch_summary = self._read_csv(batch_path)
        run_summary = self._read_csv(run_path)
        weld_summary, weld_refs = self._sample_qc_tables(
            output_dirs.get("weld_dir"), "*_weld_qc_summary.csv", "Weld QC"
        )
        alignment_path = self._declared_file(output_dirs.get("aligned_dir"), "alignment_qc_summary.csv")
        alignment_summary = self._read_csv(alignment_path)
        pca_path = self._declared_file(output_dirs.get("pca_dir"), "pca_input_manifest.csv")
        pca_input_manifest = self._read_csv(pca_path)
        evidence.extend(weld_refs)
        for label, path in (("对齐 QC", alignment_path), ("PCA 输入清单", pca_path)):
            if path is not None and path.is_file():
                evidence.append(ArtifactRef(label, path))

        return ArtifactIndex(
            attempt=attempt,
            manifest=manifest,
            output_dirs=output_dirs,
            batch_summary=batch_summary,
            run_summary=run_summary,
            weld_summary=weld_summary,
            alignment_summary=alignment_summary,
            pca_input_manifest=pca_input_manifest,
            evidence=tuple(evidence),
        )

    @staticmethod
    def _read_csv(path: Path | None) -> pd.DataFrame:
        if path is None or not path.is_file():
            return pd.DataFrame()
        try:
            return pd.read_csv(path)
        except (OSError, UnicodeDecodeError, pd.errors.ParserError) as exc:
            raise ArtifactIntegrityError(f"无法读取结果表: {path}") from exc

    @staticmethod
    def _declared_file(directory: Path | None, name: str) -> Path | None:
        return None if directory is None else directory / name

    @staticmethod
    def _sample_qc_tables(
        directory: Path | None,
        pattern: str,
        label: str,
    ) -> tuple[pd.DataFrame, list[ArtifactRef]]:
        if directory is None or not directory.is_dir():
            return pd.DataFrame(), []
        paths = sorted(directory.glob(pattern))
        tables: list[pd.DataFrame] = []
        refs: list[ArtifactRef] = []
        for path in paths:
            try:
                tables.append(pd.read_csv(path))
            except (OSError, UnicodeDecodeError, pd.errors.ParserError) as exc:
                raise ArtifactIntegrityError(f"无法读取结果表: {path}") from exc
            refs.append(ArtifactRef(label, path))
        return (pd.concat(tables, ignore_index=True) if tables else pd.DataFrame(), refs)

    @staticmethod
    def _output_dirs(root: Path, manifest: dict[str, object]) -> dict[str, Path]:
        outputs = manifest.get("outputs")
        if not isinstance(outputs, dict):
            raise ArtifactIntegrityError("运行清单缺少 outputs 映射")
        result: dict[str, Path] = {}
        for name, claimed_path in outputs.items():
            if not isinstance(name, str) or not isinstance(claimed_path, str):
                raise ArtifactIntegrityError("运行清单包含无效输出路径")
            path = Path(claimed_path)
            if path.is_absolute():
                raise ArtifactIntegrityError(f"输出路径必须为相对路径: {claimed_path}")
            resolved = (root / path).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ArtifactIntegrityError(f"输出路径越出当前运行目录: {claimed_path}") from exc
            result[name] = resolved
        return result
