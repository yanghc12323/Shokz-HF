from __future__ import annotations

from pathlib import Path

from desktop_app.models import RunOptions
from desktop_app.project_service import ProjectService
from desktop_app.run_controller import RunController
from scripts.run_full_pipeline import build_parser, build_pipeline_config


class FakeProcess:
    def setProgram(self, program: str) -> None:
        self.program = program

    def setArguments(self, arguments: list[str]) -> None:
        self.arguments = arguments

    def setWorkingDirectory(self, path: str) -> None:
        self.working_directory = path

    def start(self) -> None:
        pass


def project_with_copied_inputs(tmp_path: Path):
    project = ProjectService().create(tmp_path / "project", "一致性项目")
    project.mesh_dir.mkdir(parents=True)
    project.landmarks_dir.mkdir(parents=True)
    project.config_dir.mkdir(parents=True)
    project.region_table_path.write_text(
        "region_id,lm_a,lm_b,lm_c,resolution\nR01,L1,L2,L3,24\n",
        encoding="utf-8",
    )
    return project


def test_desktop_command_builds_the_same_pipeline_config_as_cli(tmp_path: Path):
    controller = RunController(process_factory=FakeProcess)
    options = RunOptions(
        sample_tags=("T001_L",),
        skip_remesh_qc=True,
        max_salvage_unmapped_ratio=0.2,
        max_salvage_degenerate_ratio=0.01,
        pca_variance_threshold=0.8,
        reference_sample="T001_L",
    )
    attempt = controller.start(project_with_copied_inputs(tmp_path), options)

    config, run_dir, layout = build_pipeline_config(
        build_parser().parse_args(controller.last_command[2:])
    )

    assert run_dir == attempt.artifacts_dir
    assert layout is not None
    assert config.sample_tags == options.sample_tags
    assert config.skip_remesh_qc is True
    assert config.max_salvage_unmapped_ratio == 0.2
    assert config.max_salvage_degenerate_ratio == 0.01
    assert config.pca_variance_threshold == 0.8
    assert config.reference_sample == "T001_L"
