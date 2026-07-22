# Parallel Remesh Timing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record auditable pipeline timings and run independent sample Remesh/QC tasks in bounded parallelism from the desktop application's automatic worker setting.

**Architecture:** Keep Weld, alignment and PCA serial. The pipeline will resolve `0` workers to a bounded automatic count, run each sample's Remesh followed by its QC in a worker thread, and commit records on the coordinator thread. Each child Remesh script receives a private JSONL event file; the coordinator relays its completed region events to the shared desktop event log, preventing concurrent writes to one JSONL file.

**Tech Stack:** Python 3, `concurrent.futures.ThreadPoolExecutor`, pandas, PySide6, existing CLI/JSONL event protocol.

## Global Constraints

- Desktop default is automatic parallelism; direct CLI without a new option remains sequential.
- Numerical algorithms, QC gates, output paths and sample-summary row order must not change.
- `0` means automatic; UI only exposes 0, 1, 2 and 4 workers.
- Each timing record contains stage, optional sample tag, elapsed seconds and status, and is written as `pipeline_timing_summary.csv`.
- No EXE build is performed by the agent.

---

### Task 1: CLI and desktop worker-count contract

**Files:**
- Modify: `desktop_app/models.py`, `desktop_app/run_controller.py`, `desktop_app/ui/project_wizard.py`, `scripts/run_full_pipeline.py`, `ear_param/pipeline.py`, `ear_param/run_manifest.py`
- Test: `tests/test_desktop_cli_parity.py`, `tests/test_desktop_ui_flow.py`, `tests/test_pipeline.py`

- [x] Add failing tests for automatic desktop selection, CLI transport, and `0` resolving to a bounded worker count.
- [x] Add `parallel_workers: int = 0` to `RunOptions`; send `--parallel-workers` from `RunController`.
- [x] Add an auto/1/2/4 worker selector to the parameter page and validate the selected numeric value.
- [x] Add CLI option `--parallel-workers`, defaulting to `1` for direct CLI compatibility, and store both requested/effective values in `PipelineConfig` and manifest parameters.
- [x] Verify focused tests pass.

### Task 2: Bounded parallel Remesh/QC and safe event relay

**Files:**
- Modify: `ear_param/pipeline.py`
- Test: `tests/test_pipeline.py`

- [x] Add failing tests proving two independent samples are submitted through the bounded worker path, rows retain deterministic sample order, and each child event file is relayed through the coordinator reporter.
- [x] Add `_effective_parallel_workers(requested)` that resolves automatic `0` to `min(4, max(1, cpu_count - 1))`.
- [x] Replace only the per-sample Remesh loop with a bounded executor; the coordinator keeps shared-output QC serial and commits records without worker-side DataFrame mutation.
- [x] Pass a unique child event JSONL path to each Remesh subprocess and replay completed child records via `config.event_reporter` on the coordinator thread.
- [x] Verify focused tests pass.

### Task 3: Timing outputs and result provenance

**Files:**
- Modify: `ear_param/pipeline.py`, `ear_param/run_manifest.py`, `desktop_app/artifact_indexer.py`
- Test: `tests/test_pipeline.py`, `tests/test_run_manifest.py`, `tests/test_desktop_artifact_indexer.py`

- [x] Add failing tests for `pipeline_timing_summary.csv` with sample Remesh/QC and global-stage entries and for manifest timing summary fields.
- [x] Append immutable timing records to `PipelineResult`; write the CSV beside existing pipeline summaries and add total elapsed seconds to the manifest result. Effective workers are recorded in manifest parameters.
- [x] Index the timing CSV as auditable evidence when present.
- [x] Verify focused tests pass.

### Task 4: Regression verification and documentation

**Files:**
- Modify: `docs/桌面工程软件使用说明.md`
- Test: desktop tests, pipeline timing/parallel tests, syntax compilation

- [x] Document the automatic worker policy, available manual choices, output timing CSV and pause/cancel boundary behavior.
- [x] Run the desktop suite and affected pipeline/manifest tests.
- [x] Run `python -m compileall -q desktop_app ear_param scripts/run_full_pipeline.py` and `git diff --check`.
