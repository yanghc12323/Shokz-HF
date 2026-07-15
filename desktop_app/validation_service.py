"""Preflight validation for imported desktop project inputs."""

from __future__ import annotations

from desktop_app.models import ProjectRecord, ValidationIssue
from ear_param.io_utils import read_csv_robust
from ear_param.pipeline import discover_samples


class ValidationService:
    """Return all deterministic blocking project-input issues at once."""

    def validate(self, project: ProjectRecord) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not project.mesh_dir.is_dir():
            issues.append(ValidationIssue("MISSING_MESH_DIR", "ERROR", "缺少模型目录", project.mesh_dir))
        if not project.landmarks_dir.is_dir():
            issues.append(ValidationIssue("MISSING_LANDMARK_DIR", "ERROR", "缺少特征点目录", project.landmarks_dir))
        if project.mesh_dir.is_dir() and project.landmarks_dir.is_dir():
            pairs = discover_samples(project.mesh_dir, project.landmarks_dir)
            for row in pairs.itertuples(index=False):
                if row.discovery != "READY":
                    issues.append(
                        ValidationIssue(
                            str(row.discovery),
                            "ERROR",
                            f"样本 {row.sample_tag} 输入不完整：{row.reason}",
                        )
                    )
        issues.extend(self._validate_region_table(project))
        if not project.edge_controls_path.is_file():
            issues.append(
                ValidationIssue(
                    "MISSING_EDGE_CONTROLS",
                    "ERROR",
                    "缺少边界控制点配置",
                    project.edge_controls_path,
                )
            )
        return issues

    @staticmethod
    def _validate_region_table(project: ProjectRecord) -> list[ValidationIssue]:
        path = project.region_table_path
        if not path.is_file():
            return [ValidationIssue("MISSING_REGION_TABLE", "ERROR", "缺少区域配置", path)]
        try:
            table = read_csv_robust(path)
        except Exception as exc:
            return [ValidationIssue("INVALID_REGION_TABLE", "ERROR", f"区域配置无法读取：{exc}", path)]
        required = {"region_id", "resolution"}
        missing = sorted(required.difference(table.columns))
        if missing:
            return [
                ValidationIssue(
                    "INVALID_REGION_TABLE",
                    "ERROR",
                    f"区域配置缺少字段：{', '.join(missing)}",
                    path,
                )
            ]
        return []
