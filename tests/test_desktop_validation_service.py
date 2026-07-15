from __future__ import annotations

from pathlib import Path

from desktop_app.project_service import ProjectService
from desktop_app.validation_service import ValidationService


def test_validation_reports_unpaired_mesh_as_blocking_issue(tmp_path: Path):
    project = ProjectService().create(tmp_path / "project", "项目")
    project.mesh_dir.mkdir(parents=True)
    project.landmarks_dir.mkdir(parents=True)
    project.config_dir.mkdir(parents=True)
    (project.mesh_dir / "T001_L.ply").write_bytes(b"mesh")
    project.region_table_path.write_text(
        "region_id,lm_a,lm_b,lm_c,resolution\nT001,L1,L2,L3,24\n",
        encoding="utf-8",
    )
    project.edge_controls_path.write_text(
        "edge_start,edge_end,control_point\nL1,L2,M1\n",
        encoding="utf-8",
    )

    issues = ValidationService().validate(project)

    assert {(issue.code, issue.severity) for issue in issues} >= {
        ("MISSING_LANDMARKS", "ERROR"),
    }


def test_validation_rejects_region_table_without_resolution(tmp_path: Path):
    project = ProjectService().create(tmp_path / "project", "项目")
    project.mesh_dir.mkdir(parents=True)
    project.landmarks_dir.mkdir(parents=True)
    project.config_dir.mkdir(parents=True)
    project.region_table_path.write_text("region_id\nT001\n", encoding="utf-8")
    project.edge_controls_path.write_text("edge_start\nL1\n", encoding="utf-8")

    issues = ValidationService().validate(project)

    assert ("INVALID_REGION_TABLE", "ERROR") in {
        (issue.code, issue.severity) for issue in issues
    }
