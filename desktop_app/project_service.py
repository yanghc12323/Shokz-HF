"""Project creation and immutable input-copy services."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

from desktop_app.models import ProjectRecord


class ProjectService:
    """Own project metadata and local copies of analysis inputs."""

    def create(self, root: Path, name: str) -> ProjectRecord:
        root = Path(root)
        if root.exists() and any(root.iterdir()):
            raise ValueError(f"project directory is not empty: {root}")
        root.mkdir(parents=True, exist_ok=True)
        project = ProjectRecord(root=root, name=name)
        self._write_metadata(project)
        return project

    def open(self, root: Path) -> ProjectRecord:
        root = Path(root)
        metadata_path = root / "project.json"
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return ProjectRecord(root=root, name=str(payload["name"]))

    def import_inputs(
        self,
        project: ProjectRecord,
        *,
        mesh_dir: Path,
        landmarks_dir: Path,
        region_table: Path,
        edge_controls: Path,
    ) -> ProjectRecord:
        self._require_project_path(project, project.inputs_dir)
        if project.inputs_dir.exists() and any(project.inputs_dir.iterdir()):
            raise ValueError("project inputs already exist and will not be overwritten")

        mesh_dir = Path(mesh_dir)
        landmarks_dir = Path(landmarks_dir)
        region_table = Path(region_table)
        edge_controls = Path(edge_controls)
        if not mesh_dir.is_dir() or not landmarks_dir.is_dir():
            raise ValueError("mesh and landmark sources must be directories")
        if not region_table.is_file() or not edge_controls.is_file():
            raise ValueError("region table and edge controls must be files")

        project.mesh_dir.mkdir(parents=True)
        project.landmarks_dir.mkdir(parents=True)
        project.config_dir.mkdir(parents=True)
        for path in mesh_dir.glob("*.ply"):
            shutil.copy2(path, project.mesh_dir / path.name)
        for path in landmarks_dir.glob("*_landmarks.csv"):
            shutil.copy2(path, project.landmarks_dir / path.name)
        shutil.copy2(region_table, project.region_table_path)
        shutil.copy2(edge_controls, project.edge_controls_path)
        self._write_metadata(project)
        return project

    @staticmethod
    def _require_project_path(project: ProjectRecord, path: Path) -> None:
        if not path.resolve().is_relative_to(project.root.resolve()):
            raise ValueError(f"path escapes project root: {path}")

    @staticmethod
    def _write_metadata(project: ProjectRecord) -> None:
        path = project.root / "project.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"schema_version": 1, "name": project.name}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
