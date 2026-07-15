# 3D Ear Engineering Desktop App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an installable Chinese Windows desktop application that runs the existing 3D-ear analysis pipeline in isolated project workspaces and makes all current results inspectable.

**Architecture:** A PySide6 application owns project files, validation, process state, artifact indexing, and UI. It invokes the existing Python pipeline as a controlled child process, while PyVista/VTK reads only indexed artifacts for 3D inspection. The algorithm modules remain GUI-free; optional run-control protocol additions are CLI-compatible and write machine-readable events/checkpoints.

**Tech Stack:** Python 3.11, PySide6 6.7+, PyVista 0.44+, pyvistaqt 0.11+, VTK via PyVista, PyInstaller 6.10+, pytest, existing NumPy/Pandas/SciPy/Trimesh/Matplotlib stack.

## Global Constraints

- Target Windows 10/11, Chinese-only UI; English algorithm names may appear with Chinese explanation.
- Every formal desktop attempt uses a new empty `--output-root`; never write to legacy shared `output/`.
- GUI code lives under `desktop_app/`; `ear_param/` must not import Qt, VTK, or GUI modules.
- Preserve existing CLI defaults and numerical behavior unless an explicit optional desktop protocol argument is passed.
- Preserve all current CSV, PLY, OBJ, STL, PNG, manifest, and log artifacts; do not add PDF/Word reports or measurement tools.
- One active local task at a time. Pause only at declared safe checkpoints; a cancelled or failed attempt is never indexed as valid downstream output.

---

## Planned File Structure

| Path | Responsibility |
|---|---|
| `requirements-desktop.txt` | Desktop-only dependencies pinned by compatible major versions. |
| `desktop_app/models.py` | Immutable project, attempt, validation, stage, and artifact data models. |
| `desktop_app/project_service.py` | Create/open projects, copy inputs, snapshot config, allocate attempts. |
| `desktop_app/validation_service.py` | Input pairing and CSV/config preflight validation. |
| `desktop_app/run_controller.py` | QProcess orchestration, control file writes, event tailing, and state transitions. |
| `desktop_app/artifact_indexer.py` | Validate manifests and build a typed artifact index. |
| `desktop_app/result_service.py` | Map raw statuses to Chinese gate explanations and evidence references. |
| `desktop_app/viewers/mesh_viewer.py` | PyVistaQt viewer and selected-layer/Region state. |
| `desktop_app/ui/*.py` | Main window, wizard, monitor, workbench, expert dialog, and run history UI. |
| `ear_param/run_control.py` | Optional file-backed safe-checkpoint protocol for the existing pipeline. |
| `scripts/run_full_pipeline.py` | Optional event/control arguments and `CANCELLED` terminal manifest status. |
| `tests/test_desktop_*.py` | Headless service/controller/indexing tests. |
| `tests/test_run_control.py` | Core safe-checkpoint and cancellation protocol tests. |
| `scripts/build_desktop.ps1` | Deterministic PyInstaller build command. |

## Task 1: Define Desktop Dependencies and Domain Models

**Files:**
- Create: `requirements-desktop.txt`
- Create: `desktop_app/__init__.py`
- Create: `desktop_app/models.py`
- Create: `tests/test_desktop_models.py`

**Interfaces:**
- Produces `RunStatus`, `StageName`, `ProjectRecord`, `AttemptRecord`, `RunOptions`, `ValidationIssue`, and `ArtifactRef` for every following desktop task.

- [ ] **Step 1: Write failing model tests**

```python
from pathlib import Path
from desktop_app.models import AttemptRecord, RunStatus

def test_attempt_record_uses_isolated_artifacts_directory(tmp_path: Path):
    attempt = AttemptRecord.create(tmp_path, "run-001", "attempt-001")
    assert attempt.artifacts_dir == tmp_path / "runs" / "run-001" / "attempts" / "attempt-001" / "artifacts"
    assert attempt.status is RunStatus.CREATED
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_desktop_models.py -v`
Expected: FAIL because `desktop_app` does not exist.

- [ ] **Step 3: Implement the model module and dependencies**

```python
class RunStatus(StrEnum):
    CREATED = "CREATED"; VALIDATING = "VALIDATING"; QUEUED = "QUEUED"
    RUNNING = "RUNNING"; PAUSE_REQUESTED = "PAUSE_REQUESTED"; PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"; FAILED = "FAILED"; COMPLETED = "COMPLETED"

@dataclass(frozen=True)
class AttemptRecord:
    project_root: Path; logical_run_id: str; attempt_id: str; status: RunStatus
    parent_attempt_id: str | None = None
    @property
    def artifacts_dir(self) -> Path:
        return self.project_root / "runs" / self.logical_run_id / "attempts" / self.attempt_id / "artifacts"
    @classmethod
    def create(cls, project_root: Path, logical_run_id: str, attempt_id: str) -> "AttemptRecord":
        return cls(project_root, logical_run_id, attempt_id, RunStatus.CREATED)

@dataclass(frozen=True)
class RunOptions:
    sample_tags: tuple[str, ...] = ()
    skip_remesh_qc: bool = False
    max_salvage_unmapped_ratio: float = 0.35
    max_salvage_degenerate_ratio: float = 0.015
    pca_variance_threshold: float = 0.75
    reference_sample: str | None = None
```

Put the following exact dependency floors in `requirements-desktop.txt`:

```text
-r requirements.txt
PySide6>=6.7,<7
pyvista>=0.44,<1
pyvistaqt>=0.11,<1
pyinstaller>=6.10,<7
```

- [ ] **Step 4: Run model tests**

Run: `python -m pytest tests/test_desktop_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add requirements-desktop.txt desktop_app/__init__.py desktop_app/models.py tests/test_desktop_models.py
git commit -m "feat: add desktop domain models"
```

## Task 2: Add CLI-Compatible Events and Safe Checkpoints

**Files:**
- Create: `ear_param/run_control.py`
- Modify: `ear_param/pipeline.py`
- Modify: `scripts/run_full_pipeline.py`
- Create: `tests/test_run_control.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- `FileRunControl(path: Path, poll_seconds: float = 0.25)` exposes `checkpoint() -> None` and raises `RunCancelled` only when control JSON says `CANCEL_REQUESTED`.
- `PipelineConfig.checkpoint: Callable[[], None] | None` runs before each sample and batch stage.
- CLI accepts optional `--event-log PATH` and `--control-path PATH`; omitted arguments preserve today’s behavior.

- [ ] **Step 1: Write failing checkpoint tests**

```python
def test_checkpoint_waits_for_running_then_returns(tmp_path, monkeypatch):
    control = tmp_path / "control.json"
    control.write_text('{"status":"PAUSE_REQUESTED"}', encoding="utf-8")
    calls = iter([None, None, control.write_text('{"status":"RUNNING"}', encoding="utf-8")])
    monkeypatch.setattr("ear_param.run_control.time.sleep", lambda _: next(calls, None))
    FileRunControl(control, poll_seconds=0).checkpoint()

def test_checkpoint_raises_for_cancellation(tmp_path):
    control = tmp_path / "control.json"
    control.write_text('{"status":"CANCEL_REQUESTED"}', encoding="utf-8")
    with pytest.raises(RunCancelled):
        FileRunControl(control).checkpoint()
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `python -m pytest tests/test_run_control.py -v`
Expected: FAIL because `ear_param.run_control` is missing.

- [ ] **Step 3: Implement the optional protocol**

```python
class RunCancelled(RuntimeError): pass

class FileRunControl:
    def checkpoint(self) -> None:
        while self._status() == "PAUSE_REQUESTED":
            time.sleep(self.poll_seconds)
        if self._status() == "CANCEL_REQUESTED":
            raise RunCancelled("run cancelled by desktop controller")
```

Add `checkpoint: Callable[[], None] | None = None` to `PipelineConfig`; add `_checkpoint(config)` and call it immediately before each sample remesh, remesh QC, Weld, alignment, GPA PCA, and fixed-reference branch. In the script, construct `JsonlEventWriter(Path(args.event_log))` only when `--event-log` is supplied and set `event_reporter=lambda name, fields: writer.emit(name, **fields)`. Catch `RunCancelled` in `execute()`, finish manifest with `status="CANCELLED"`, then return a process exit code reserved for cancellation rather than writing `ERROR`.

- [ ] **Step 4: Add pipeline event and cancellation assertions**

```python
def test_pipeline_calls_checkpoint_before_remesh_stage(tmp_path):
    mesh_dir = tmp_path / "mesh"; landmarks_dir = tmp_path / "landmarks"
    mesh_dir.mkdir(); landmarks_dir.mkdir()
    (mesh_dir / "T001_L.ply").write_bytes(b"mesh")
    (landmarks_dir / "T001_L_landmarks.csv").write_text("landmark_id,x,y,z\nL1,0,0,0\n", encoding="utf-8")
    checkpoints = []
    config = PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir, checkpoint=lambda: checkpoints.append("hit"))
    stages = StageFunctions(
        remesh_sample=lambda _: {"remesh": "PASS", "salvage": "FAIL"},
        remesh_qc=lambda _: "SKIPPED", weld_batch=lambda _: pd.DataFrame(),
        alignment_batch=lambda _: pd.DataFrame(), pca_batch=lambda: {"status": "PASS", "included_tags": []},
    )
    run_pipeline(config, stage_functions=stages)
    assert checkpoints
```

- [ ] **Step 5: Run focused and full core tests**

Run: `python -m pytest tests/test_run_control.py tests/test_events.py tests/test_pipeline.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add ear_param/run_control.py ear_param/pipeline.py scripts/run_full_pipeline.py tests/test_run_control.py tests/test_pipeline.py
git commit -m "feat: add controlled pipeline checkpoints"
```

## Task 3: Implement Project Creation, Import Copying, and Validation

**Files:**
- Create: `desktop_app/project_service.py`
- Create: `desktop_app/validation_service.py`
- Create: `tests/test_desktop_project_service.py`
- Create: `tests/test_desktop_validation_service.py`

**Interfaces:**
- `ProjectService.create(root: Path, name: str) -> ProjectRecord` rejects non-empty roots and writes `project.json`.
- `ProjectService.import_inputs(project: ProjectRecord, mesh_dir: Path, landmarks_dir: Path, region_table: Path, edge_controls: Path) -> ProjectRecord` copies files to `inputs/` and never mutates the source.
- `ValidationService.validate(project: ProjectRecord) -> list[ValidationIssue]` returns blocking issues with `severity="ERROR"` or non-blocking `"WARNING"`.

- [ ] **Step 1: Write failing service tests**

```python
def test_import_copies_mesh_landmarks_and_config_without_modifying_source(tmp_path):
    project = ProjectService().create(tmp_path / "project", "耳形态")
    imported = ProjectService().import_inputs(project, mesh_dir, landmark_dir, regions, controls)
    assert (imported.inputs_dir / "clean_mesh" / "T001_L.ply").read_bytes() == b"mesh"
    assert source_mesh.read_bytes() == b"mesh"

def test_validation_reports_unpaired_mesh_as_blocking_issue(tmp_path):
    issues = ValidationService().validate(project_with_mesh_only(tmp_path))
    assert {(issue.code, issue.severity) for issue in issues} >= {("MISSING_LANDMARKS", "ERROR")}
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_desktop_project_service.py tests/test_desktop_validation_service.py -v`
Expected: FAIL because the services are missing.

- [ ] **Step 3: Implement deterministic file and validation behavior**

Use `shutil.copy2` for files, reject symlinked destination escapes via `Path.resolve().is_relative_to(project.root.resolve())`, and store UTF-8 JSON with `ensure_ascii=False`. Validate pairing with `ear_param.pipeline.discover_samples`; require `region_id` and `resolution` in the imported region table and require the configured control CSV to exist. Never create an attempt during validation.

- [ ] **Step 4: Run service tests**

Run: `python -m pytest tests/test_desktop_project_service.py tests/test_desktop_validation_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add desktop_app/project_service.py desktop_app/validation_service.py tests/test_desktop_project_service.py tests/test_desktop_validation_service.py
git commit -m "feat: add desktop project import and validation"
```

## Task 4: Build Attempt Allocation and Controlled Process Execution

**Files:**
- Create: `desktop_app/run_controller.py`
- Create: `tests/test_desktop_run_controller.py`

**Interfaces:**
- `RunController.start(project: ProjectRecord, options: RunOptions) -> AttemptRecord` creates `runs/<logical-id>/attempts/<attempt-id>/`, writes `desktop_state.json`, and starts one `QProcess`.
- `RunController.request_pause()`, `resume()`, and `cancel()` update only the control JSON for the active attempt.
- Signals: `attempt_changed(AttemptRecord)`, `event_received(dict[str, object])`, `run_finished(AttemptRecord)`.

- [ ] **Step 1: Write failing controller tests using a fake process factory**

```python
def test_start_passes_only_project_scoped_paths_and_empty_artifacts(tmp_path):
    controller = RunController(process_factory=FakeProcess)
    attempt = controller.start(project, RunOptions())
    assert "--output-root" in controller.last_command
    assert str(attempt.artifacts_dir) in controller.last_command
    assert not attempt.artifacts_dir.exists()

def test_pause_resume_cancel_write_control_status(tmp_path):
    controller = running_controller(tmp_path)
    controller.request_pause(); assert read_status(controller) == "PAUSE_REQUESTED"
    controller.resume(); assert read_status(controller) == "RUNNING"
    controller.cancel(); assert read_status(controller) == "CANCEL_REQUESTED"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_desktop_run_controller.py -v`
Expected: FAIL because `RunController` is missing.

- [ ] **Step 3: Implement one-process state ownership**

Build the command as `sys.executable scripts/run_full_pipeline.py --mesh_dir <project>/inputs/clean_mesh --landmarks_dir <project>/inputs/landmarks --regions <project>/inputs/config/region_table.csv --output-root <attempt>/artifacts --event-log <attempt>/events.jsonl --control-path <attempt>/control.json`. Create `control.json` with `{"status":"RUNNING"}` and atomically replace JSON state files via a `.tmp` sibling. Reject `start()` when any process is active. Tailing events must ignore incomplete final lines and emit only JSON objects.

- [ ] **Step 4: Test terminal status mapping**

Add tests mapping manifest statuses `COMPLETED`, `CANCELLED`, and `ERROR` to `RunStatus.COMPLETED`, `CANCELLED`, and `FAILED`; require a manifest before reporting a completed attempt.

- [ ] **Step 5: Run controller tests**

Run: `python -m pytest tests/test_desktop_run_controller.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add desktop_app/run_controller.py tests/test_desktop_run_controller.py
git commit -m "feat: add desktop run controller"
```

## Task 5: Index Artifacts and Explain QC Gate Decisions

**Files:**
- Create: `desktop_app/artifact_indexer.py`
- Create: `desktop_app/result_service.py`
- Create: `tests/test_desktop_artifact_indexer.py`
- Create: `tests/test_desktop_result_service.py`

**Interfaces:**
- `ArtifactIndexer.index(attempt: AttemptRecord) -> ArtifactIndex` accepts only completed manifests and validates every claimed path remains under `attempt.artifacts_dir`.
- `ResultService.sample_details(index: ArtifactIndex, sample_tag: str) -> SampleDetails` returns raw/salvage/Weld/alignment/PCA statuses, a Chinese reason, and evidence `ArtifactRef` values.

- [ ] **Step 1: Write failing indexing and explanation tests**

```python
def test_index_rejects_manifest_that_claims_path_outside_artifacts(tmp_path):
    with pytest.raises(ArtifactIntegrityError):
        ArtifactIndexer().index(attempt_with_escape_manifest(tmp_path))

def test_weld_failure_explains_pca_interception(index):
    detail = ResultService().sample_details(index, "T049_L")
    assert detail.pca_status == "拦截"
    assert "Weld" in detail.reason_zh
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_desktop_artifact_indexer.py tests/test_desktop_result_service.py -v`
Expected: FAIL because indexer and result service are missing.

- [ ] **Step 3: Implement artifact evidence rules**

Parse `manifest.json`, `pipeline_batch_summary.csv`, `pipeline_run_summary.csv`, `weld_qc_summary.csv`, `alignment_qc_summary.csv`, and `pca_input_manifest.csv` only when present and declared by the manifest. Resolve every file and reject paths outside the current artifacts root. Define reason mappings for at least `MISSING_MESH`, `MISSING_LANDMARKS`, `salvage_not_pass`, `weld_not_pca_ready`, `alignment_not_pass`, and PCA exclusion; unknown machine reasons must display the original reason string rather than being discarded.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_desktop_artifact_indexer.py tests/test_desktop_result_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add desktop_app/artifact_indexer.py desktop_app/result_service.py tests/test_desktop_artifact_indexer.py tests/test_desktop_result_service.py
git commit -m "feat: index desktop artifacts and QC evidence"
```

## Task 6: Implement the Guided PySide6 Application Shell

**Files:**
- Create: `desktop_app/app.py`
- Create: `desktop_app/ui/main_window.py`
- Create: `desktop_app/ui/project_wizard.py`
- Create: `desktop_app/ui/run_monitor.py`
- Create: `tests/test_desktop_ui_flow.py`

**Interfaces:**
- `create_application(argv: list[str]) -> QApplication` and `MainWindow(project_service, validation_service, run_controller)`.
- Wizard page sequence is `ProjectPage -> ImportPage -> ValidationPage -> OptionsPage -> RunMonitorPage`; `OptionsPage` is unreachable while validation has an ERROR.

- [ ] **Step 1: Write failing Qt flow tests**

```python
def test_options_page_is_blocked_by_validation_error(qtbot, services):
    window = MainWindow(*services)
    qtbot.addWidget(window)
    window.open_project(project_with_invalid_inputs())
    assert not window.workflow.can_advance_to("options")
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_desktop_ui_flow.py -v`
Expected: FAIL because the application shell is missing.

- [ ] **Step 3: Implement Chinese-only workflow controls**

Create top-level destinations `项目`, `分析流程`, `结果复核`, `专家模式`, `运行记录`. Use the design-approved three-column workbench language and plain Chinese validation messages. Bind pause/cancel/resume buttons to RunController state, disabling actions that are invalid for the current `RunStatus`.

- [ ] **Step 4: Run headless Qt tests**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/test_desktop_ui_flow.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add desktop_app/app.py desktop_app/ui/main_window.py desktop_app/ui/project_wizard.py desktop_app/ui/run_monitor.py tests/test_desktop_ui_flow.py
git commit -m "feat: add guided desktop workflow"
```

## Task 7: Add 3D Layer Viewing and Result Workbench

**Files:**
- Create: `desktop_app/viewers/__init__.py`
- Create: `desktop_app/viewers/mesh_viewer.py`
- Create: `desktop_app/ui/result_workbench.py`
- Create: `tests/test_desktop_mesh_viewer.py`
- Create: `tests/test_desktop_result_workbench.py`

**Interfaces:**
- `MeshViewer.load_layer(layer: LayerName, artifact: ArtifactRef) -> None`, `reset_camera() -> None`, `set_region_highlight(region_id: str | None) -> None`.
- `ResultWorkbench.set_attempt(index: ArtifactIndex) -> None` and `select_sample(sample_tag: str) -> SampleDetails`.

- [ ] **Step 1: Write failing viewer/workbench tests**

```python
def test_unavailable_layer_is_disabled_with_reason(qtbot, artifact_index):
    workbench = ResultWorkbench()
    qtbot.addWidget(workbench)
    workbench.set_attempt(artifact_index)
    assert not workbench.layer_button("平均耳").isEnabled()
    assert "PCA" in workbench.layer_button("平均耳").toolTip()
```

- [ ] **Step 2: Run to verify failure**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/test_desktop_mesh_viewer.py tests/test_desktop_result_workbench.py -v`
Expected: FAIL because viewer and workbench are missing.

- [ ] **Step 3: Implement isolated rendering**

Use `pyvistaqt.QtInteractor` inside `MeshViewer`; load only file paths returned by `ArtifactIndexer`. Map Raw/Repaired/Salvaged to region meshes, Whole Ear to Weld/aligned meshes, and Mean Ear to PCA mean mesh. Use one stable actor per selected layer, clear the old actor before loading the next, and render Region/QC highlight as a separate actor. Do not add measurement widgets.

- [ ] **Step 4: Implement inspection synchronization**

On sample, layer, or region selection, refresh the right inspection pane from `ResultService`; show gate order and evidence buttons. Evidence buttons must call the operating system only for paths already approved by the indexer.

- [ ] **Step 5: Run UI tests**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/test_desktop_mesh_viewer.py tests/test_desktop_result_workbench.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add desktop_app/viewers desktop_app/ui/result_workbench.py tests/test_desktop_mesh_viewer.py tests/test_desktop_result_workbench.py
git commit -m "feat: add 3d result workbench"
```

## Task 8: Implement Recovery Attempts and Expert Stage Reruns

**Files:**
- Create: `desktop_app/recovery_service.py`
- Create: `desktop_app/ui/expert_mode.py`
- Modify: `desktop_app/models.py`
- Modify: `desktop_app/project_service.py`
- Modify: `desktop_app/run_controller.py`
- Create: `tests/test_desktop_recovery_service.py`
- Modify: `tests/test_desktop_run_controller.py`

**Interfaces:**
- `RecoveryService.plan(parent: AttemptRecord) -> list[RecoveryOption]` exposes only stages with validated parent outputs.
- `RecoveryService.create_attempt(parent: AttemptRecord, option: RecoveryOption) -> AttemptRecord` creates a new attempt with a new empty artifacts directory and records parent/source-stage provenance.
- Extend the `AttemptRecord.create` factory with a `parent_attempt_id: str | None = None` parameter to retain parent provenance for recovery attempts.

- [ ] **Step 1: Write failing recovery tests**

```python
def test_recovery_creates_new_attempt_and_preserves_parent_artifacts(tmp_path):
    child = RecoveryService().create_attempt(failed_weld_attempt(tmp_path), RecoveryOption.WELD)
    assert child.attempt_id != "attempt-001"
    assert not child.artifacts_dir.exists()
    assert child.parent_attempt_id == "attempt-001"

def test_recovery_hides_weld_when_salvaged_input_fails_integrity(tmp_path):
    assert RecoveryOption.WELD not in RecoveryService().plan(corrupt_attempt(tmp_path))
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_desktop_recovery_service.py -v`
Expected: FAIL because recovery service is missing.

- [ ] **Step 3: Implement stage-specific recovery commands**

Persist `run_history.json` with logical-run, parent-attempt, source-stage, and source-manifest hash. For WELD use the parent validated salvaged directory as `scripts/build_whole_ear.py --input_dir` and write only new Weld outputs to the new attempt. For alignment use parent validated Weld outputs with `scripts/align_whole_ear.py --whole_ear_dir`; for PCA use parent aligned/Weld outputs with `scripts/build_average_ear.py`. Write a recovery manifest containing `parent_attempt`, `source_stage`, `source_manifest_sha256`, and source paths; reject every source path outside the parent artifacts root.

- [ ] **Step 4: Wire expert mode and re-run tests**

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/test_desktop_recovery_service.py tests/test_desktop_run_controller.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add desktop_app/recovery_service.py desktop_app/ui/expert_mode.py desktop_app/project_service.py desktop_app/run_controller.py tests/test_desktop_recovery_service.py tests/test_desktop_run_controller.py
git commit -m "feat: add recovery attempts and expert reruns"
```

## Task 9: Package, Document, and Verify the Windows Application

**Files:**
- Create: `desktop_app/__main__.py`
- Create: `scripts/build_desktop.ps1`
- Modify: `README.md`
- Create: `docs/桌面工程软件使用说明.md`
- Create: `tests/test_desktop_cli_parity.py`

**Interfaces:**
- `python -m desktop_app` launches the application.
- `scripts/build_desktop.ps1` produces `dist/耳模型工程分析/耳模型工程分析.exe`.

- [ ] **Step 1: Write a failing CLI-parity fixture test**

```python
def test_desktop_command_matches_cli_manifest_parameters(small_project, cli_result):
    attempt = run_desktop_pipeline(small_project)
    assert manifest_parameters(attempt) == manifest_parameters(cli_result)
    assert batch_statuses(attempt) == batch_statuses(cli_result)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_desktop_cli_parity.py -v`
Expected: FAIL until the desktop runner fixture exists.

- [ ] **Step 3: Add packaging and user documentation**

`build_desktop.ps1` must run `python -m PyInstaller --noconfirm --windowed --name 耳模型工程分析 --collect-all pyvista --collect-all vtkmodules --collect-all pyvistaqt -m desktop_app`. Document installation, project creation, input copying, normal workflow, status meanings, recovery restrictions, and all retained artifact types in Chinese. Update README with the desktop entry point while retaining all CLI commands as the reference baseline.

- [ ] **Step 4: Execute regression suite**

Run: `python -m pytest tests -q`
Expected: PASS, including existing core tests and new desktop tests.

- [ ] **Step 5: Build and smoke test on Windows**

Run: `powershell -ExecutionPolicy Bypass -File scripts/build_desktop.ps1`
Expected: `dist/耳模型工程分析/耳模型工程分析.exe` exists and starts; create a small project, complete import/validation, run a small fixture, and open one result mesh.

- [ ] **Step 6: Commit**

```powershell
git add desktop_app/__main__.py scripts/build_desktop.ps1 README.md docs/桌面工程软件使用说明.md tests/test_desktop_cli_parity.py
git commit -m "feat: package desktop engineering app"
```

## Plan Self-Review

- **Spec coverage:** Tasks 1–4 cover the Windows app foundation, isolated project/attempt storage, full pipeline control, JSONL events, pause/cancel and controlled process ownership. Tasks 5 and 7 cover artifact fidelity, QC explanations, current formats, result workbench, 3D layers, and Region/QC highlights. Task 8 covers expert reruns and failed-run recovery with a new isolated attempt. Task 9 covers CLI parity, Chinese guidance, packaging, and Windows smoke validation.
- **No placeholders:** The plan contains explicit paths, names, signatures, command lines, expected outcomes, and test examples; no deferred implementation markers are used.
- **Type consistency:** `AttemptRecord`, `ProjectRecord`, `RunOptions`, `ArtifactIndex`, `ArtifactRef`, `SampleDetails`, `RecoveryOption`, and `RunController` are introduced before dependent tasks and retain the same names throughout.
