# Run-Scoped Pipeline Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in run-scoped output isolation and a durable `manifest.json` to the existing W2-to-W3 pipeline without changing legacy CLI defaults or numerical algorithms.

**Architecture:** A new `PipelineOutputLayout` maps one output root to every existing stage directory. `run_full_pipeline.py --output-root` injects those paths into `PipelineConfig`, while calls without the option preserve all current defaults. A separate manifest module records inputs, parameters, code/runtime identity, lifecycle status, and final summaries.

**Tech Stack:** Python 3.11+, pathlib, dataclasses, argparse, json, pandas, NumPy, pytest.

## Global Constraints

- Windows 10/11 is the target platform.
- Do not change Remesh, Salvage, Weld, Alignment, or PCA numerical behavior or QC thresholds.
- Do not modify files under `data/` or `config/`.
- Existing CLI commands without `--output-root` must retain their current output directories.
- Scoped runs must reject a non-empty output root rather than overwrite it.
- All new paths are passed through existing script arguments; algorithms remain in `ear_param` and existing scripts.
- Update README and relevant technical documents with every behavior change.
- Do not commit unless the user explicitly authorizes Git commits; conditional commit steps are checkpoints only.

---

## File Structure

**Create**

- `ear_param/run_artifacts.py`: output-root layout, empty-root guard, file metadata helpers.
- `ear_param/run_manifest.py`: manifest construction, atomic write, lifecycle updates.
- `tests/test_run_artifacts.py`: path layout and overwrite-guard tests.
- `tests/test_run_manifest.py`: manifest content and lifecycle tests.

**Modify**

- `ear_param/pipeline.py`: add run-scoped remesh PLY directories and pass them to the existing Remesh CLI.
- `scripts/run_full_pipeline.py`: expose `--output-root`, build scoped config, create/finalize manifest.
- `tests/test_pipeline.py`: cover command construction and config compatibility.
- `README.md`: document scoped and legacy modes.
- `docs/W2 Remesh 使用说明.md`: document per-run W2 locations.
- `docs/整耳全局模板、边界焊接与刚体统一坐标系.md`: document per-run Weld/Alignment locations.
- `docs/W3 PCA 与平均耳技术路线.md`: document per-run PCA locations.

## Interfaces Produced

- `PipelineOutputLayout.from_output_root(output_root: Path) -> PipelineOutputLayout`
- `PipelineOutputLayout.pipeline_config_kwargs() -> dict[str, Path]`
- `prepare_empty_output_root(output_root: Path) -> Path`
- `create_run_manifest(config, run_dir, output_root, project_root, argv) -> dict[str, object]`
- `write_manifest(path: Path, manifest: dict[str, object]) -> None`
- `finish_manifest(path, status, result=None, error="") -> dict[str, object]`

---

### Task 1: Define the run-scoped output layout

**Files:**

- Create: `ear_param/run_artifacts.py`
- Create: `tests/test_run_artifacts.py`

**Interfaces:**

- Consumes: one user-selected `Path` used as a batch output root.
- Produces: `PipelineOutputLayout.from_output_root()` and `pipeline_config_kwargs()` for Task 3.

- [ ] **Step 1: Write the failing path-layout test**

```python
from pathlib import Path


def test_pipeline_output_layout_maps_every_stage_under_one_root(tmp_path: Path):
    from ear_param.run_artifacts import PipelineOutputLayout

    root = tmp_path / "run_001"
    layout = PipelineOutputLayout.from_output_root(root)

    assert layout.output_root == root
    assert layout.canonical_dir == root / "canonical_inputs_r24"
    assert layout.raw_dir == root / "parameterized_points_r24" / "raw"
    assert layout.repaired_dir == root / "parameterized_points_r24" / "repaired"
    assert layout.salvaged_dir == root / "parameterized_points_r24" / "salvaged"
    assert layout.raw_mesh_dir == root / "remesh_r24" / "raw"
    assert layout.repaired_mesh_dir == root / "remesh_r24" / "repaired"
    assert layout.salvaged_mesh_dir == root / "remesh_r24" / "salvaged"
    assert layout.qc_dir == root / "remesh_qc_r24"
    assert layout.weld_dir == root / "whole_ear_r24" / "weld_repaired"
    assert layout.aligned_dir == root / "whole_ear_r24" / "aligned_gpa"
    assert layout.pca_dir == root / "pca_gpa_r24"
    assert layout.reference_aligned_dir == root / "whole_ear_r24" / "aligned_reference_T076_L"
    assert layout.reference_pca_dir == root / "pca_reference_T076_L_r24"
```

- [ ] **Step 2: Run the test and verify the missing module failure**

Run:

```powershell
python -m pytest tests/test_run_artifacts.py::test_pipeline_output_layout_maps_every_stage_under_one_root -v --basetemp .pytest_basetemp_desktop_layout_red
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ear_param.run_artifacts'`.

- [ ] **Step 3: Implement the immutable layout**

```python
"""Run-scoped locations for every pipeline output layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
    def from_output_root(cls, output_root: Path) -> "PipelineOutputLayout":
        root = Path(output_root)
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
            reference_aligned_dir=whole_ear / "aligned_reference_T076_L",
            reference_pca_dir=root / "pca_reference_T076_L_r24",
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
```

- [ ] **Step 4: Test the config mapping as well as the paths**

Append to the test:

```python
    config_paths = layout.pipeline_config_kwargs()
    assert set(config_paths) == {
        "canonical_dir", "raw_dir", "repaired_dir", "salvaged_dir",
        "raw_mesh_dir", "repaired_mesh_dir", "salvaged_mesh_dir",
        "qc_dir", "weld_dir", "aligned_dir", "pca_dir",
        "reference_aligned_dir", "reference_pca_dir",
    }
    assert all(root in path.parents for path in config_paths.values())
```

- [ ] **Step 5: Run the focused tests**

Run:

```powershell
python -m pytest tests/test_run_artifacts.py -v --basetemp .pytest_basetemp_desktop_layout_green
```

Expected: PASS.

- [ ] **Step 6: Review checkpoint**

Run `git diff --check`. If the user has explicitly authorized commits, commit only these two files with message `feat: define run-scoped pipeline layout`; otherwise leave them unstaged.

---

### Task 2: Prevent accidental reuse of a scoped output root

**Files:**

- Modify: `ear_param/run_artifacts.py`
- Modify: `tests/test_run_artifacts.py`

**Interfaces:**

- Consumes: `output_root: Path` before any stage starts.
- Produces: `prepare_empty_output_root(output_root) -> Path`, used by Task 4.

- [ ] **Step 1: Write failing tests for new, empty, and non-empty roots**

```python
import pytest


def test_prepare_empty_output_root_creates_missing_directory(tmp_path: Path):
    from ear_param.run_artifacts import prepare_empty_output_root

    root = tmp_path / "new_run"
    assert prepare_empty_output_root(root) == root
    assert root.is_dir()


def test_prepare_empty_output_root_accepts_existing_empty_directory(tmp_path: Path):
    from ear_param.run_artifacts import prepare_empty_output_root

    root = tmp_path / "empty_run"
    root.mkdir()
    assert prepare_empty_output_root(root) == root


def test_prepare_empty_output_root_rejects_non_empty_directory(tmp_path: Path):
    from ear_param.run_artifacts import prepare_empty_output_root

    root = tmp_path / "existing_run"
    root.mkdir()
    (root / "old_result.csv").write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(FileExistsError, match="output root is not empty"):
        prepare_empty_output_root(root)
```

- [ ] **Step 2: Verify the tests fail because the function is missing**

Run:

```powershell
python -m pytest tests/test_run_artifacts.py -k prepare_empty_output_root -v --basetemp .pytest_basetemp_desktop_guard_red
```

Expected: FAIL on import.

- [ ] **Step 3: Add the minimal guard**

```python
def prepare_empty_output_root(output_root: Path) -> Path:
    root = Path(output_root)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"output root is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    return root
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m pytest tests/test_run_artifacts.py -v --basetemp .pytest_basetemp_desktop_guard_green
```

Expected: all tests in `test_run_artifacts.py` PASS.

- [ ] **Step 5: Review checkpoint**

Run `git diff --check`. If commits are authorized, commit Task 2 as `feat: guard scoped pipeline outputs`; otherwise leave changes unstaged.

---

### Task 3: Route Remesh CSV and PLY outputs through PipelineConfig

**Files:**

- Modify: `ear_param/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**

- Consumes: `raw_mesh_dir`, `repaired_mesh_dir`, and `salvaged_mesh_dir` from `PipelineConfig`.
- Produces: a Remesh subprocess command in which all six CSV/PLY output directories are explicit.

- [ ] **Step 1: Write the failing default-path test**

```python
def test_pipeline_config_keeps_legacy_remesh_mesh_defaults(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig

    config = PipelineConfig(
        mesh_dir=tmp_path / "clean_mesh",
        landmarks_dir=tmp_path / "landmarks",
    )

    assert config.raw_mesh_dir == Path("output/remesh_r24/raw")
    assert config.repaired_mesh_dir == Path("output/remesh_r24/repaired")
    assert config.salvaged_mesh_dir == Path("output/remesh_r24/salvaged")
```

- [ ] **Step 2: Run the default-path test and verify it fails**

Run:

```powershell
python -m pytest tests/test_pipeline.py::test_pipeline_config_keeps_legacy_remesh_mesh_defaults -v --basetemp .pytest_basetemp_pipeline_mesh_paths_red
```

Expected: FAIL because the three fields do not exist.

- [ ] **Step 3: Add the legacy-compatible config fields**

Add beside the existing raw/repaired/salvaged CSV directories:

```python
    raw_mesh_dir: Path = Path("output/remesh_r24/raw")
    repaired_mesh_dir: Path = Path("output/remesh_r24/repaired")
    salvaged_mesh_dir: Path = Path("output/remesh_r24/salvaged")
```

- [ ] **Step 4: Write a failing command-construction test**

```python
def test_subprocess_remesh_receives_all_scoped_output_directories(
    tmp_path: Path,
    monkeypatch,
):
    import ear_param.pipeline as pipeline

    root = tmp_path / "run"
    config = pipeline.PipelineConfig(
        mesh_dir=tmp_path / "data" / "clean_mesh",
        landmarks_dir=tmp_path / "data" / "landmarks",
        canonical_dir=root / "canonical",
        raw_dir=root / "points" / "raw",
        repaired_dir=root / "points" / "repaired",
        salvaged_dir=root / "points" / "salvaged",
        raw_mesh_dir=root / "meshes" / "raw",
        repaired_mesh_dir=root / "meshes" / "repaired",
        salvaged_mesh_dir=root / "meshes" / "salvaged",
    )
    commands: list[list[str]] = []

    def fake_run(command: list[str], cwd: Path) -> None:
        commands.append(command)
        config.raw_dir.mkdir(parents=True, exist_ok=True)
        config.salvaged_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"status": ["PASS"]}).to_csv(
            config.raw_dir / "T001_L_remesh_qc.csv", index=False
        )
        pd.DataFrame({"status": ["PASS"]}).to_csv(
            config.salvaged_dir / "T001_L_remesh_qc.csv", index=False
        )

    monkeypatch.setattr(pipeline, "_run_command", fake_run)
    pipeline.build_subprocess_stages(config).remesh_sample("T001_L")

    command = commands[0]
    assert command[command.index("--mesh_out_dir") + 1] == str(config.raw_mesh_dir)
    assert command[command.index("--repaired_mesh_out_dir") + 1] == str(config.repaired_mesh_dir)
    assert command[command.index("--salvaged_mesh_out_dir") + 1] == str(config.salvaged_mesh_dir)
```

- [ ] **Step 5: Run the command test and verify the missing arguments**

Run:

```powershell
python -m pytest tests/test_pipeline.py::test_subprocess_remesh_receives_all_scoped_output_directories -v --basetemp .pytest_basetemp_pipeline_mesh_command_red
```

Expected: FAIL because `--mesh_out_dir` is not present.

- [ ] **Step 6: Pass all PLY output paths to the existing script**

Insert after the matching CSV arguments in `remesh_sample()`:

```python
            "--mesh_out_dir", str(config.raw_mesh_dir),
            "--repaired_mesh_out_dir", str(config.repaired_mesh_dir),
            "--salvaged_mesh_out_dir", str(config.salvaged_mesh_dir),
```

- [ ] **Step 7: Run focused and pipeline tests**

Run:

```powershell
python -m pytest tests/test_pipeline.py -v --basetemp .pytest_basetemp_pipeline_mesh_green
```

Expected: all pipeline tests PASS.

- [ ] **Step 8: Review checkpoint**

Run `git diff --check`. If commits are authorized, commit Task 3 as `feat: route remesh meshes through pipeline config`; otherwise leave changes unstaged.

---

### Task 4: Expose opt-in `--output-root` without changing legacy defaults

**Files:**

- Modify: `scripts/run_full_pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**

- Consumes: CLI option `--output-root <path>`.
- Produces: `build_pipeline_config(args) -> tuple[PipelineConfig, Path, PipelineOutputLayout | None]`.

- [ ] **Step 1: Write failing config-builder tests**

```python
def test_full_pipeline_output_root_scopes_every_stage(tmp_path: Path):
    from scripts.run_full_pipeline import build_parser, build_pipeline_config

    root = tmp_path / "scoped_run"
    args = build_parser().parse_args([
        "--mesh_dir", str(tmp_path / "clean_mesh"),
        "--landmarks_dir", str(tmp_path / "landmarks"),
        "--output-root", str(root),
        "--reference-sample", "T076_L",
    ])

    config, run_dir, layout = build_pipeline_config(args)

    assert layout is not None
    assert run_dir == root
    assert config.raw_dir == root / "parameterized_points_r24" / "raw"
    assert config.raw_mesh_dir == root / "remesh_r24" / "raw"
    assert config.weld_dir == root / "whole_ear_r24" / "weld_repaired"
    assert config.reference_pca_dir == root / "pca_reference_T076_L_r24"


def test_full_pipeline_without_output_root_keeps_legacy_stage_paths(tmp_path: Path):
    from scripts.run_full_pipeline import build_parser, build_pipeline_config

    args = build_parser().parse_args([
        "--mesh_dir", str(tmp_path / "clean_mesh"),
        "--landmarks_dir", str(tmp_path / "landmarks"),
        "--run_dir", str(tmp_path / "summary_only"),
    ])

    config, run_dir, layout = build_pipeline_config(args)

    assert layout is None
    assert run_dir == tmp_path / "summary_only"
    assert config.raw_dir == Path("output/parameterized_points_r24/raw")
    assert config.weld_dir == Path("output/whole_ear_r24/weld_repaired")
```

- [ ] **Step 2: Verify the public builder is missing**

Run:

```powershell
python -m pytest tests/test_pipeline.py -k "full_pipeline_output_root or full_pipeline_without_output_root" -v --basetemp .pytest_basetemp_output_root_red
```

Expected: FAIL because `build_parser` and `build_pipeline_config` do not exist.

- [ ] **Step 3: Refactor parser construction and add the option**

Add these imports:

```python
import argparse

from ear_param.run_artifacts import (
    PipelineOutputLayout,
    prepare_empty_output_root,
)
```

Replace the parser inside `main()` with this single public parser:

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run remesh, QC, weld repair, GPA-PCA, and optional fixed-reference PCA."
    )
    parser.add_argument("--mesh_dir", default="data/clean_mesh")
    parser.add_argument("--landmarks_dir", default="data/landmarks")
    parser.add_argument("--regions", default="config/region_table.csv")
    parser.add_argument(
        "--samples", nargs="+", help="Optional sample tags, e.g. T076_L T077_L."
    )
    parser.add_argument("--skip-remesh-qc", action="store_true")
    parser.add_argument("--canonical-side", default="L", choices=("L",))
    parser.add_argument("--mirror-axis", default="x", choices=("x", "y", "z"))
    parser.add_argument(
        "--max-salvage-degenerate-ratio",
        type=float,
        default=0.015,
        help="Maximum raw degenerate-face ratio eligible for salvaged UV repair.",
    )
    parser.add_argument("--skip-pca", action="store_true")
    parser.add_argument(
        "--reference-sample",
        help="Optional fixed-reference ear tag, e.g. T076_L; enables the second PCA branch.",
    )
    parser.add_argument("--run_dir", help="Directory for this run's summary artifacts.")
    parser.add_argument(
        "--output-root",
        help="Optional isolated root for every stage output; must be empty.",
    )
    return parser
```

- [ ] **Step 4: Implement the config builder**

```python
def build_pipeline_config(
    args: argparse.Namespace,
) -> tuple[PipelineConfig, Path, PipelineOutputLayout | None]:
    output_root = Path(args.output_root) if args.output_root else None
    run_dir = (
        Path(args.run_dir)
        if args.run_dir
        else output_root
        if output_root is not None
        else Path("output/pipeline_runs") / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    layout = (
        PipelineOutputLayout.from_output_root(output_root)
        if output_root is not None
        else None
    )
    config_kwargs: dict[str, object] = {
        "mesh_dir": Path(args.mesh_dir),
        "landmarks_dir": Path(args.landmarks_dir),
        "regions": Path(args.regions),
        "sample_tags": tuple(args.samples or ()),
        "skip_remesh_qc": args.skip_remesh_qc,
        "canonical_side": args.canonical_side,
        "mirror_axis": args.mirror_axis,
        "max_salvage_degenerate_ratio": args.max_salvage_degenerate_ratio,
        "disable_side_normalization": False,
        "skip_pca": args.skip_pca,
        "reference_sample": args.reference_sample,
        "reporter": print,
    }
    if layout is not None:
        config_kwargs.update(layout.pipeline_config_kwargs())
    return PipelineConfig(**config_kwargs), run_dir, layout
```

- [ ] **Step 5: Make `main()` consume the public functions and guard scoped roots**

```python
def main() -> None:
    args = build_parser().parse_args()
    config, run_dir, layout = build_pipeline_config(args)
    if layout is not None:
        prepare_empty_output_root(layout.output_root)
    result = run_pipeline(config, stage_functions=build_subprocess_stages(config))
    write_pipeline_outputs(result, run_dir)
    _print_final_summary(result, run_dir)
```

Use this helper so the existing terminal output remains stable:

```python
def _print_final_summary(result: PipelineResult, run_dir: Path) -> None:
    print("\n[Pipeline] Final summary:")
    print(result.records.to_string(index=False))
    print(f"[Pipeline] PCA status: {result.pca_status}")
    print(f"[Pipeline] Fixed-reference PCA status: {result.reference_pca_status}")
    print(f"[Pipeline] Run artifacts: {run_dir}")
```

Add `PipelineResult` to the existing import from `ear_param.pipeline`.

- [ ] **Step 6: Run the focused tests and CLI help smoke test**

Run:

```powershell
python -m pytest tests/test_pipeline.py -k "output_root or legacy_stage_paths" -v --basetemp .pytest_basetemp_output_root_green
python scripts/run_full_pipeline.py --help
```

Expected: tests PASS; help lists `--output-root`; no pipeline starts.

- [ ] **Step 7: Review checkpoint**

Run `git diff --check`. If commits are authorized, commit Task 4 as `feat: add isolated pipeline output root`; otherwise leave changes unstaged.

---

### Task 5: Create a durable manifest with input and environment provenance

**Files:**

- Create: `ear_param/run_manifest.py`
- Create: `tests/test_run_manifest.py`

**Interfaces:**

- Consumes: `PipelineConfig`, run directory, optional output root, project root, and CLI argv.
- Produces: JSON-safe manifest dictionaries and atomic UTF-8 JSON files.

- [ ] **Step 1: Write a failing manifest-content test**

```python
from pathlib import Path

import json


def test_create_run_manifest_records_inputs_parameters_and_outputs(tmp_path: Path):
    from ear_param.pipeline import PipelineConfig
    from ear_param.run_manifest import create_run_manifest, write_manifest

    mesh_dir = tmp_path / "data" / "clean_mesh"
    landmarks_dir = tmp_path / "data" / "landmarks"
    config_dir = tmp_path / "config"
    mesh_dir.mkdir(parents=True)
    landmarks_dir.mkdir(parents=True)
    config_dir.mkdir()
    (mesh_dir / "T076_L.ply").write_bytes(b"ply")
    (landmarks_dir / "T076_L_landmarks.csv").write_text(
        "landmark_id,x,y,z\nL7,0,0,0\n", encoding="utf-8"
    )
    regions = config_dir / "region_table.csv"
    regions.write_text("region_id,a,b,c\nT001,L1,L2,L3\n", encoding="utf-8")
    (config_dir / "edge_control_points.csv").write_text(
        "edge_start,edge_end,control_point\nL1,L2,M1\n", encoding="utf-8"
    )
    run_dir = tmp_path / "output" / "pipeline_runs" / "run_001"
    config = PipelineConfig(
        mesh_dir=mesh_dir,
        landmarks_dir=landmarks_dir,
        regions=regions,
        sample_tags=("T076_L",),
        reference_sample="T076_L",
        disable_side_normalization=False,
    )

    manifest = create_run_manifest(
        config=config,
        run_dir=run_dir,
        output_root=run_dir,
        project_root=tmp_path,
        argv=["--reference-sample", "T076_L"],
    )
    write_manifest(run_dir / "manifest.json", manifest)
    saved = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert saved["schema_version"] == 1
    assert saved["status"] == "RUNNING"
    assert saved["run_id"] == "run_001"
    assert saved["parameters"]["reference_sample"] == "T076_L"
    assert saved["parameters"]["canonical_side"] == "L"
    assert saved["inputs"][0]["sample_tag"] == "T076_L"
    assert saved["inputs"][0]["mesh"]["size_bytes"] == 3
    assert saved["config_files"]["region_table"]["exists"] is True
    assert saved["config_files"]["edge_control_points"]["exists"] is True
    assert saved["runtime"]["python"]
    assert saved["code"]["commit"]
```

- [ ] **Step 2: Run the test and verify the module is missing**

Run:

```powershell
python -m pytest tests/test_run_manifest.py::test_create_run_manifest_records_inputs_parameters_and_outputs -v --basetemp .pytest_basetemp_manifest_red
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement metadata and manifest construction**

Create `ear_param/run_manifest.py` with these concrete helpers:

```python
"""Durable provenance for formal pipeline runs."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
from typing import Any

from ear_param.pipeline import PipelineConfig, PipelineResult, discover_samples


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_metadata(path: Path, project_root: Path) -> dict[str, object]:
    path = Path(path)
    try:
        shown_path = str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        shown_path = str(path.resolve())
    if not path.is_file():
        return {"path": shown_path, "exists": False}
    stat = path.stat()
    return {
        "path": shown_path,
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _git_code_state(project_root: Path) -> dict[str, object]:
    def run(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args], cwd=project_root, capture_output=True,
            text=True, timeout=5, check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else "unknown"

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    return {"commit": commit or "unknown", "dirty": status not in {"", "unknown"}}
```

`create_run_manifest()` must then assemble exactly these top-level keys:

```python
def create_run_manifest(
    *,
    config: PipelineConfig,
    run_dir: Path,
    output_root: Path | None,
    project_root: Path,
    argv: list[str],
) -> dict[str, object]:
    discovered = discover_samples(config.mesh_dir, config.landmarks_dir)
    if config.sample_tags:
        discovered = discovered[discovered["sample_tag"].isin(config.sample_tags)]
    inputs = []
    for sample_tag in discovered["sample_tag"].astype(str):
        inputs.append({
            "sample_tag": sample_tag,
            "mesh": _file_metadata(config.mesh_dir / f"{sample_tag}.ply", project_root),
            "landmarks": _file_metadata(
                config.landmarks_dir / f"{sample_tag}_landmarks.csv", project_root
            ),
        })
    edge_controls = config.regions.parent / "edge_control_points.csv"
    return {
        "schema_version": 1,
        "run_id": Path(run_dir).name,
        "status": "RUNNING",
        "created_at": _utc_now(),
        "finished_at": None,
        "project_root": str(project_root.resolve()),
        "run_dir": str(Path(run_dir).resolve()),
        "output_scope": "isolated" if output_root is not None else "legacy_shared",
        "output_root": str(Path(output_root).resolve()) if output_root else None,
        "argv": list(argv),
        "parameters": {
            "samples": list(config.sample_tags),
            "skip_remesh_qc": config.skip_remesh_qc,
            "skip_pca": config.skip_pca,
            "canonical_side": config.canonical_side,
            "mirror_axis": config.mirror_axis,
            "max_salvage_degenerate_ratio": config.max_salvage_degenerate_ratio,
            "reference_sample": config.reference_sample,
        },
        "inputs": inputs,
        "config_files": {
            "region_table": _file_metadata(config.regions, project_root),
            "edge_control_points": _file_metadata(edge_controls, project_root),
        },
        "outputs": {
            name: str(getattr(config, name).resolve())
            for name in (
                "canonical_dir", "raw_dir", "repaired_dir", "salvaged_dir",
                "raw_mesh_dir", "repaired_mesh_dir", "salvaged_mesh_dir",
                "qc_dir", "weld_dir", "aligned_dir", "pca_dir",
                "reference_aligned_dir", "reference_pca_dir",
            )
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": _package_version("numpy"),
            "pandas": _package_version("pandas"),
        },
        "code": _git_code_state(project_root),
        "result": None,
        "error": "",
    }
```

- [ ] **Step 4: Implement atomic JSON writing**

```python
def write_manifest(path: Path, manifest: dict[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
```

- [ ] **Step 5: Run the focused test**

Run:

```powershell
python -m pytest tests/test_run_manifest.py::test_create_run_manifest_records_inputs_parameters_and_outputs -v --basetemp .pytest_basetemp_manifest_green
```

Expected: PASS.

- [ ] **Step 6: Review checkpoint**

Run `git diff --check`. If commits are authorized, commit Task 5 as `feat: record pipeline run provenance`; otherwise leave changes unstaged.

---

### Task 6: Finalize the manifest on completion and failure

**Files:**

- Modify: `ear_param/run_manifest.py`
- Modify: `tests/test_run_manifest.py`
- Modify: `scripts/run_full_pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**

- Consumes: a RUNNING manifest and optional `PipelineResult`.
- Produces: terminal manifest status `COMPLETED` or `ERROR` with final batch counts.

- [ ] **Step 1: Write failing lifecycle tests**

```python
import pandas as pd


def test_finish_manifest_records_completed_pipeline_summary(tmp_path: Path):
    from ear_param.pipeline import PipelineResult
    from ear_param.run_manifest import finish_manifest, write_manifest

    path = tmp_path / "manifest.json"
    write_manifest(path, {
        "status": "RUNNING", "finished_at": None, "result": None, "error": ""
    })
    result = PipelineResult(
        records=pd.DataFrame({
            "discovery": ["READY", "READY"],
            "salvage": ["PASS", "FAIL"],
            "weld": ["PASS", "SKIPPED"],
            "alignment": ["PASS", "SKIPPED"],
            "pca_included": ["YES", "NO"],
            "reference_alignment": ["PASS", "SKIPPED"],
            "reference_pca_included": ["YES", "NO"],
        }),
        pca_status="PASS",
        pca_result={"retained_component_count": 3},
        reference_pca_status="PASS",
        reference_pca_result={"retained_component_count": 3},
    )

    saved = finish_manifest(path, status="COMPLETED", result=result)

    assert saved["status"] == "COMPLETED"
    assert saved["finished_at"]
    assert saved["result"]["sample_count"] == 2
    assert saved["result"]["salvage_pass_count"] == 1
    assert saved["result"]["pca_included_count"] == 1
    assert saved["result"]["pca_status"] == "PASS"


def test_finish_manifest_records_top_level_error(tmp_path: Path):
    from ear_param.run_manifest import finish_manifest, write_manifest

    path = tmp_path / "manifest.json"
    write_manifest(path, {
        "status": "RUNNING", "finished_at": None, "result": None, "error": ""
    })

    saved = finish_manifest(path, status="ERROR", error="pipeline exploded")

    assert saved["status"] == "ERROR"
    assert saved["error"] == "pipeline exploded"
    assert saved["finished_at"]
```

- [ ] **Step 2: Run lifecycle tests and verify the function is missing**

Run:

```powershell
python -m pytest tests/test_run_manifest.py -k finish_manifest -v --basetemp .pytest_basetemp_manifest_finish_red
```

Expected: FAIL on import.

- [ ] **Step 3: Implement final result summarization**

```python
def _count(records, column: str, value: str) -> int:
    return int((records[column] == value).sum()) if column in records else 0


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return str(value)


def finish_manifest(
    path: Path,
    *,
    status: str,
    result: PipelineResult | None = None,
    error: str = "",
) -> dict[str, object]:
    path = Path(path)
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    manifest["status"] = status
    manifest["finished_at"] = _utc_now()
    manifest["error"] = error
    if result is not None:
        records = result.records
        manifest["result"] = {
            "sample_count": len(records),
            "ready_count": _count(records, "discovery", "READY"),
            "salvage_pass_count": _count(records, "salvage", "PASS"),
            "weld_pass_count": _count(records, "weld", "PASS"),
            "alignment_pass_count": _count(records, "alignment", "PASS"),
            "pca_included_count": _count(records, "pca_included", "YES"),
            "reference_alignment_pass_count": _count(
                records, "reference_alignment", "PASS"
            ),
            "reference_pca_included_count": _count(
                records, "reference_pca_included", "YES"
            ),
            "pca_status": result.pca_status,
            "reference_pca_status": result.reference_pca_status,
            "pca_result": _json_safe(result.pca_result),
            "reference_pca_result": _json_safe(result.reference_pca_result),
        }
    write_manifest(path, manifest)
    return manifest
```

- [ ] **Step 4: Run manifest tests**

Run:

```powershell
python -m pytest tests/test_run_manifest.py -v --basetemp .pytest_basetemp_manifest_finish_green
```

Expected: all manifest tests PASS.

- [ ] **Step 5: Write a failing execution-wrapper test**

Add a public `execute(args)` test by monkeypatching stage execution:

```python
import pytest


def test_full_pipeline_execute_finalizes_manifest_on_error(tmp_path: Path, monkeypatch):
    import json
    import scripts.run_full_pipeline as cli

    root = tmp_path / "failed_run"
    args = cli.build_parser().parse_args([
        "--mesh_dir", str(tmp_path / "clean_mesh"),
        "--landmarks_dir", str(tmp_path / "landmarks"),
        "--output-root", str(root),
    ])
    (tmp_path / "clean_mesh").mkdir()
    (tmp_path / "landmarks").mkdir()
    monkeypatch.setattr(cli, "build_subprocess_stages", lambda config: object())
    monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        cli.execute(args)

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "ERROR"
    assert "boom" in manifest["error"]
```

- [ ] **Step 6: Implement `execute(args)` lifecycle ownership**

```python
def execute(args: argparse.Namespace) -> PipelineResult:
    config, run_dir, layout = build_pipeline_config(args)
    if layout is not None:
        prepare_empty_output_root(layout.output_root)
    manifest_path = run_dir / "manifest.json"
    manifest = create_run_manifest(
        config=config,
        run_dir=run_dir,
        output_root=layout.output_root if layout else None,
        project_root=_PROJECT_ROOT,
        argv=sys.argv[1:],
    )
    write_manifest(manifest_path, manifest)
    try:
        result = run_pipeline(config, stage_functions=build_subprocess_stages(config))
        write_pipeline_outputs(result, run_dir)
    except BaseException as exc:
        finish_manifest(manifest_path, status="ERROR", error=str(exc))
        raise
    finish_manifest(manifest_path, status="COMPLETED", result=result)
    _print_final_summary(result, run_dir)
    return result
```

`main()` becomes `execute(build_parser().parse_args())`.

- [ ] **Step 7: Run pipeline and manifest tests**

Run:

```powershell
python -m pytest tests/test_pipeline.py tests/test_run_artifacts.py tests/test_run_manifest.py -v --basetemp .pytest_basetemp_run_scope_green
```

Expected: all focused tests PASS.

- [ ] **Step 8: Review checkpoint**

Run `git diff --check`. If commits are authorized, commit Task 6 as `feat: finalize pipeline run manifests`; otherwise leave changes unstaged.

---

### Task 7: Document scoped runs and perform regression verification

**Files:**

- Modify: `README.md`
- Modify: `docs/W2 Remesh 使用说明.md`
- Modify: `docs/整耳全局模板、边界焊接与刚体统一坐标系.md`
- Modify: `docs/W3 PCA 与平均耳技术路线.md`

**Interfaces:**

- Consumes: final CLI and directory behavior from Tasks 1-6.
- Produces: user-facing commands and directory descriptions for both isolated and legacy modes.

- [ ] **Step 1: Add the formal isolated-run command**

Use this exact example in README:

```powershell
python scripts/run_full_pipeline.py `
  --reference-sample T076_L `
  --output-root output/pipeline_runs/full28_T076_20260715
```

Explain that `--output-root` must point to a missing or empty directory and that every canonical, W2, QC, Weld, Alignment, PCA, summary, and manifest file stays beneath it.

- [ ] **Step 2: Document the compatibility rule**

Add this explicit statement to README and the three technical documents:

```text
不传 --output-root 时，所有阶段继续使用原有固定 output/... 目录；
--run_dir 仍只控制批次汇总目录。桌面软件必须传 --output-root，
不能依赖旧的共享输出模式。
```

- [ ] **Step 3: Document the exact scoped directory tree**

```text
<output-root>/
  manifest.json
  pipeline_batch_summary.csv
  pipeline_run_summary.csv
  pipeline_run.log
  canonical_inputs_r24/
  parameterized_points_r24/{raw,repaired,salvaged}/
  remesh_r24/{raw,repaired,salvaged}/
  remesh_qc_r24/
  whole_ear_r24/{weld_repaired,aligned_gpa,aligned_reference_T076_L}/
  pca_gpa_r24/
  pca_reference_T076_L_r24/
```

- [ ] **Step 4: Run documentation and whitespace checks**

Run:

```powershell
rg -n "output-root|manifest.json|legacy_shared|共享输出" README.md docs
git diff --check
```

Expected: all four current documents contain the new behavior; no whitespace errors.

- [ ] **Step 5: Run the complete automated test suite**

Run with an approved writable base temp directory:

```powershell
python -m pytest -q --basetemp .pytest_basetemp_desktop_run_scope_full
```

Expected: all tests PASS; baseline before this milestone is 70 passing tests.

- [ ] **Step 6: Run a non-computing CLI smoke check**

```powershell
python scripts/run_full_pipeline.py --help
```

Expected: exit code 0 and both `--run_dir` and `--output-root` are documented.

- [ ] **Step 7: Final review checkpoint**

Inspect `git status --short` and ensure only planned source/test/doc files plus pre-existing user changes are present. Do not alter `data/landmarks/T002_L_landmarks.csv` or `data/landmarks/T003_L_landmarks.csv`. If commits are authorized, commit documentation and any remaining milestone files as `docs: explain isolated pipeline runs`; otherwise report the complete unstaged diff.

---

## Milestone 1 Completion Criteria

- `--output-root` maps every existing stage output, including Remesh PLY files, below one root.
- A non-empty scoped root is rejected before computation starts.
- Commands without `--output-root` retain current stage paths.
- `manifest.json` is written before processing and finalized as `COMPLETED` or `ERROR`.
- Manifest contains input metadata, configuration, output paths, runtime, code state, parameters, and result counts.
- Existing numerical/QC behavior is unchanged.
- Focused and full automated tests pass.
- README and W2/Weld/W3 documents describe both modes accurately.
