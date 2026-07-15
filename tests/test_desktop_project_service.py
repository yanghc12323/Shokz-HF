from __future__ import annotations

import json
from pathlib import Path

from desktop_app.project_service import ProjectService


def _write_sources(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    mesh_dir = root / "source_mesh"
    landmarks_dir = root / "source_landmarks"
    config_dir = root / "source_config"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    config_dir.mkdir()
    mesh = mesh_dir / "T001_L.ply"
    mesh.write_bytes(b"mesh-bytes")
    (landmarks_dir / "T001_L_landmarks.csv").write_text(
        "landmark_id,x,y,z\nL1,0,0,0\n",
        encoding="utf-8",
    )
    regions = config_dir / "custom_regions.csv"
    regions.write_text(
        "region_id,lm_a,lm_b,lm_c,resolution\nT001,L1,L2,L3,24\n",
        encoding="utf-8",
    )
    controls = config_dir / "custom_controls.csv"
    controls.write_text(
        "edge_start,edge_end,control_point\nL1,L2,M1\n",
        encoding="utf-8",
    )
    return mesh_dir, landmarks_dir, regions, controls, mesh


def test_project_import_copies_inputs_without_modifying_source(tmp_path: Path):
    mesh_dir, landmarks_dir, regions, controls, source_mesh = _write_sources(tmp_path)
    service = ProjectService()
    project = service.create(tmp_path / "project", "耳形态项目")

    imported = service.import_inputs(
        project,
        mesh_dir=mesh_dir,
        landmarks_dir=landmarks_dir,
        region_table=regions,
        edge_controls=controls,
    )

    assert (imported.mesh_dir / "T001_L.ply").read_bytes() == b"mesh-bytes"
    assert source_mesh.read_bytes() == b"mesh-bytes"
    assert imported.region_table_path.name == "region_table.csv"
    assert imported.edge_controls_path.name == "edge_control_points.csv"
    metadata = json.loads((imported.root / "project.json").read_text(encoding="utf-8"))
    assert metadata["name"] == "耳形态项目"


def test_project_creation_rejects_nonempty_directory(tmp_path: Path):
    root = tmp_path / "occupied"
    root.mkdir()
    (root / "keep.txt").write_text("do not overwrite", encoding="utf-8")

    try:
        ProjectService().create(root, "项目")
    except ValueError as exc:
        assert "not empty" in str(exc)
    else:
        raise AssertionError("expected non-empty project directory to be rejected")
