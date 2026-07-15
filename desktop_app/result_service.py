"""Translate pipeline statuses and machine-readable gate reasons for the UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from desktop_app.artifact_indexer import ArtifactIndex
from desktop_app.models import ArtifactRef


@dataclass(frozen=True)
class SampleDetails:
    sample_tag: str
    raw_status: str
    salvage_status: str
    weld_status: str
    alignment_status: str
    pca_status: str
    reason_zh: str
    evidence: tuple[ArtifactRef, ...]


_REASON_ZH = {
    "MISSING_MESH": "缺少原始网格文件。",
    "MISSING_LANDMARKS": "缺少对应的地标 CSV 文件。",
    "salvage_not_pass": "Salvage 修复未通过，后续整耳阶段被拦截。",
    "weld_not_pca_ready": "Weld 整耳拼接或边界 QC 未达到 PCA 准入条件，PCA 被拦截。",
    "alignment_not_pass": "整耳对齐 QC 未通过，PCA 被拦截。",
    "pca_error": "PCA 阶段执行失败，未纳入统计。",
    "reference_alignment_not_pass": "固定参考耳对齐未通过。",
}


class ResultService:
    """Produce sample-focused status cards backed by indexed evidence files."""

    def sample_details(self, index: ArtifactIndex, sample_tag: str) -> SampleDetails:
        row = self._sample_row(index.batch_summary, sample_tag)
        raw_status = self._text(row, "remesh", fallback=self._text(row, "discovery"))
        salvage_status = self._text(row, "salvage")
        weld_status = self._text(row, "weld")
        alignment_status = self._text(row, "alignment")
        pca_status = self._pca_status(row)
        reason_zh = self._reason_zh(self._text(row, "reason"), pca_status)
        return SampleDetails(
            sample_tag=sample_tag,
            raw_status=raw_status,
            salvage_status=salvage_status,
            weld_status=weld_status,
            alignment_status=alignment_status,
            pca_status=pca_status,
            reason_zh=reason_zh,
            evidence=self._sample_evidence(index, sample_tag),
        )

    @staticmethod
    def _sample_row(summary: pd.DataFrame, sample_tag: str) -> pd.Series:
        if "sample_tag" not in summary.columns:
            raise KeyError("批处理汇总中没有 sample_tag 列")
        rows = summary.loc[summary["sample_tag"].astype(str) == sample_tag]
        if len(rows) != 1:
            raise KeyError(f"找不到唯一的样本记录: {sample_tag}")
        return rows.iloc[0]

    @staticmethod
    def _text(row: pd.Series, column: str, fallback: str = "未运行") -> str:
        if column not in row.index or pd.isna(row[column]):
            return fallback
        value = str(row[column]).strip()
        return value or fallback

    def _pca_status(self, row: pd.Series) -> str:
        status = self._text(row, "pca_included", fallback="SKIPPED")
        if status.upper() == "YES":
            return "纳入"
        if self._text(row, "weld").upper() != "PASS" or self._text(row, "alignment").upper() != "PASS":
            return "拦截"
        if status.upper() in {"NO", "SKIPPED"}:
            return "未纳入"
        return status

    @staticmethod
    def _reason_zh(reason: str, pca_status: str) -> str:
        tokens = [token.strip() for token in reason.split(";") if token.strip()]
        translated = [_REASON_ZH.get(token, token) for token in tokens]
        if not translated and pca_status == "拦截":
            translated.append("前置质量门未通过，PCA 被拦截。")
        return "；".join(translated) or "该样本已通过当前阶段。"

    @staticmethod
    def _sample_evidence(index: ArtifactIndex, sample_tag: str) -> tuple[ArtifactRef, ...]:
        refs: list[ArtifactRef] = []
        for ref in index.evidence:
            if ref.path.name in {"manifest.json", "pipeline_batch_summary.csv", "pipeline_run_summary.csv"}:
                refs.append(ref)
            elif sample_tag in ref.path.name:
                refs.append(ref)
        return tuple(refs)
