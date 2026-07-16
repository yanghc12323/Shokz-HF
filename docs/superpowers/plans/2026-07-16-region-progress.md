# Region-Level Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show real-time sample × region QC and repair status with progress bars in the desktop run monitor.

**Architecture:** `parameterize_ear_remesh.py` writes additional JSONL events only when `--event-log` is supplied. The pipeline forwards the desktop event path to that script without changing calculations or CSV schemas. `RunMonitor` maps those events into a region table and progress bars.

**Tech Stack:** Python, pandas, PySide6, pytest, pytest-qt.

## Global Constraints

- Windows desktop UI remains Chinese-only.
- Existing CLI results and existing CSV/PLY/OBJ/STL/PNG/manifest/log outputs must remain identical.
- No EXE build in this change.

### Task 1: Emit region events without changing remesh results

**Files:** `scripts/parameterize_ear_remesh.py`, `ear_param/pipeline.py`, `tests/test_parameterize_ear_remesh.py`, `tests/test_pipeline.py`.

- [ ] Add optional `--event-log`; construct `JsonlEventWriter` only when supplied.
- [ ] Emit `region_started` before each region and `region_finished` after either success or exception. Include `sample_tag`, `region_id`, `region_name`, `raw_status`, `repaired_status`, `salvaged_status`, `final_status`, `reason`, `completed_regions`, and `total_regions`.
- [ ] Forward `config.event_log` through `build_subprocess_stages().remesh_sample`.
- [ ] Verify events contain raw/repaired/salvaged results while legacy invocation creates unchanged outputs.

### Task 2: Present region progress in the desktop monitor

**Files:** `desktop_app/ui/run_monitor.py`, `desktop_app/ui/main_window.py`, `tests/test_desktop_ui_flow.py`.

- [ ] Add a total `QProgressBar`, current-sample `QProgressBar`, and a `QTableWidget` with columns: 样本, Region, 原始 QC, 修复后 QC, Salvaged QC, 最终状态, 原因.
- [ ] On `region_started`, add/update the row as 处理中. On `region_finished`, update statuses/reason and both progress bars.
- [ ] Use PASS/WARNING/FAIL labels without altering pipeline decisions.
- [ ] Verify a `region_finished` event updates the row and progress values.

### Task 3: Regression and documentation

**Files:** `docs/桌面工程软件使用说明.md`, affected tests.

- [ ] Document region-level progress fields and their meaning.
- [ ] Run `python -m pytest -q -p no:cacheprovider --basetemp <temp-dir>` with `QT_QPA_PLATFORM=offscreen`.
