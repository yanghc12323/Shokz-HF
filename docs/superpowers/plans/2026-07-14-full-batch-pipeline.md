# Full Batch Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one reproducible command that discovers paired samples, runs the approved W2-to-W3 workflow, continues after sample failures, and writes a clear batch summary.

**Architecture:** `ear_param/pipeline.py` owns discovery, state records, stage orchestration, and run artifacts. Existing stage scripts expose small callable wrappers but remain independent CLIs. `scripts/run_full_pipeline.py` parses paths/options, prints real-time progress, and prints the final table.

**Tech Stack:** Python 3, pandas, pathlib, existing `ear_param` modules, pytest.

## Global Constraints

- Discover only paired `data/clean_mesh/<sample_tag>.ply` and `data/landmarks/<sample_tag>_landmarks.csv` files.
- A failed or erroneous sample never interrupts other samples.
- Preserve `raw`, `repaired`, `salvaged`, `weld_repaired`, `aligned_weld_repaired`, and W3 output contracts.
- Run PCA only after at least two alignment-PASS samples; never relax QC gates.
- Do not change remesh, repair, Weld, alignment, or PCA mathematical behavior.
- Update README and W3 documentation with the official command and batch artifacts.

---

### Task 1: Sample Discovery and Batch Summary Types

**Files:**
- Create: `tests/test_pipeline.py`
- Create: `ear_param/pipeline.py`

**Interfaces:**
- Produces `discover_samples(mesh_dir: Path, landmarks_dir: Path) -> pd.DataFrame`.
- Produces `PipelineRecord` with stages `discovery`, `remesh`, `salvage`, `remesh_qc`, `weld`, `alignment`, `pca_included`, and `reason`.

- [ ] **Step 1: Write failing discovery tests**

```python
def test_discover_samples_records_ready_and_missing_pairs(tmp_path):
    discovered = discover_samples(mesh_dir, landmarks_dir)
    assert discovered.set_index("sample_tag").loc["T001_L", "discovery"] == "READY"
    assert discovered.set_index("sample_tag").loc["T002_L", "discovery"] == "MISSING_LANDMARKS"
    assert discovered.set_index("sample_tag").loc["T003_L", "discovery"] == "MISSING_MESH"
```

- [ ] **Step 2: Run the test red**

Run: `python -m pytest tests/test_pipeline.py::test_discover_samples_records_ready_and_missing_pairs -v --basetemp .test_artifacts/pipeline_red`

Expected: FAIL because `ear_param.pipeline` does not exist.

- [ ] **Step 3: Implement the minimal discovery and record helpers**

```python
def discover_samples(mesh_dir: Path, landmarks_dir: Path) -> pd.DataFrame:
    mesh_tags = {path.stem for path in mesh_dir.glob("*.ply")}
    landmark_tags = {path.name.removesuffix("_landmarks.csv") for path in landmarks_dir.glob("*_landmarks.csv")}
    return _make_discovery_table(mesh_tags, landmark_tags)
```

- [ ] **Step 4: Run focused tests green**

Run: `python -m pytest tests/test_pipeline.py -v --basetemp .test_artifacts/pipeline_discovery`

Expected: PASS.

### Task 2: Callable Stage Wrappers

**Files:**
- Modify: `scripts/parameterize_ear_remesh.py`
- Modify: `scripts/visualize_remesh_qc.py`
- Modify: `scripts/build_whole_ear.py`
- Modify: `scripts/align_whole_ear.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Produces `run_remesh_sample(...) -> pd.DataFrame` and `run_remesh_qc(...) -> pd.DataFrame`.
- Produces `run_whole_ear_batch(...) -> pd.DataFrame` and `run_alignment_batch(...) -> pd.DataFrame`.
- Existing `main()` functions call these wrappers using parsed arguments.

- [ ] **Step 1: Write failing orchestration tests with injected stage functions**

```python
def test_pipeline_continues_after_one_sample_remesh_error(tmp_path):
    result = run_pipeline(config, remesh_runner=failing_one_runner)
    assert result.records.set_index("sample_tag").loc["T001_L", "remesh"] == "ERROR"
    assert result.records.set_index("sample_tag").loc["T002_L", "remesh"] == "PASS"
```

- [ ] **Step 2: Run tests red**

Run: `python -m pytest tests/test_pipeline.py::test_pipeline_continues_after_one_sample_remesh_error -v --basetemp .test_artifacts/pipeline_stage_red`

Expected: FAIL because `run_pipeline` does not exist.

- [ ] **Step 3: Extract wrappers without changing stage calculation logic**

Move current `main()` bodies into parameterized functions and have each CLI pass
its parsed values to the new wrapper. Preserve filenames and printed stage-level
summaries.

- [ ] **Step 4: Run focused wrapper and legacy stage tests**

Run: `python -m pytest tests/test_pipeline.py tests/test_parameterize_ear_remesh.py tests/test_whole_ear.py tests/test_alignment.py -q --basetemp .test_artifacts/pipeline_wrappers`

Expected: PASS.

### Task 3: Batch Orchestration, Artifacts, and CLI

**Files:**
- Modify: `ear_param/pipeline.py`
- Create: `scripts/run_full_pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Produces `run_pipeline(config: PipelineConfig, *, stage_functions: StageFunctions | None = None) -> PipelineResult`.
- Produces `write_pipeline_outputs(result: PipelineResult, run_dir: Path) -> None`.

- [ ] **Step 1: Write failing summary and PCA skip tests**

```python
def test_pipeline_writes_summary_and_skips_pca_under_two_aligned_samples(tmp_path):
    result = run_pipeline(config, stage_functions=one_aligned_sample_functions)
    write_pipeline_outputs(result, run_dir)
    assert result.pca_status == "SKIPPED_INSUFFICIENT_SAMPLES"
    assert (run_dir / "pipeline_batch_summary.csv").is_file()
```

- [ ] **Step 2: Run tests red**

Run: `python -m pytest tests/test_pipeline.py::test_pipeline_writes_summary_and_skips_pca_under_two_aligned_samples -v --basetemp .test_artifacts/pipeline_summary_red`

Expected: FAIL because orchestration/artifact writers do not exist.

- [ ] **Step 3: Implement stage transitions and artifact writers**

Run remesh/QC per READY sample, then run Weld/align/PCA only with previous-stage
PASS tags. Capture exceptions as `ERROR`, append a concise reason, write records,
counts, and a plain text log. Print progress through an injected reporter.

- [ ] **Step 4: Add the CLI and run focused tests**

Run: `python -m pytest tests/test_pipeline.py -q --basetemp .test_artifacts/pipeline_green`

Expected: PASS.

### Task 4: Real-Data Verification and Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/W3 PCA 与平均耳技术路线.md`

- [ ] **Step 1: Run the formal command on current paired data**

Run: `python scripts/run_full_pipeline.py`

Expected: real-time per-stage lines, final table, and artifacts under
`output/pipeline_runs/<run_id>/`.

- [ ] **Step 2: Verify produced summary agrees with stage summaries**

Check paired discovery counts, Weld/PCA-ready counts, alignment PASS counts,
PCA inclusion list, and the PCA result against individual CSV evidence.

- [ ] **Step 3: Update documentation**

Add the official command, run artifact paths, failure-continuation rule, and
latest real run count without changing scientific QC thresholds.

- [ ] **Step 4: Run full regression**

Run: `python -m pytest -q --basetemp .test_artifacts/full_pipeline`

Expected: all legacy and new tests pass.
