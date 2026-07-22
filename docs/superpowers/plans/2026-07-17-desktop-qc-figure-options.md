# Desktop QC Figure Options Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add selectable Region QC PNG generation modes without changing QC gates, and make the desktop build/review UI reliable on Windows.

**Architecture:** Keep QC status computation in the existing visual-QC subprocess. A mode controls only calls that render PNGs. The desktop transports a typed option through the existing CLI command builder.

**Tech Stack:** Python 3.14, PySide6, argparse, PyInstaller, pytest.

## Global Constraints

- Target is offline Windows 10/11 desktop software.
- Existing CLI defaults and QC CSV/gating semantics remain unchanged.
- Desktop default is `repaired-fail`; CLI default is `all`.

---

### Task 1: QC mode CLI and pipeline transport

**Files:**
- Modify: `desktop_app/models.py`, `desktop_app/run_controller.py`, `scripts/run_full_pipeline.py`, `ear_param/pipeline.py`
- Test: `tests/test_desktop_cli_parity.py`, `tests/test_pipeline.py`

- [ ] Add a failing test asserting desktop mode becomes `--qc-figure-mode repaired-fail` and CLI config exposes the same value.
- [ ] Add `qc_figure_mode: str = "all"` to `RunOptions` and `PipelineConfig`; add validated argparse choices.
- [ ] Pass the option through `RunController` and the subprocess QC command.
- [ ] Run the focused parity and pipeline tests.

### Task 2: Conditional PNG rendering

**Files:**
- Modify: `scripts/visualize_remesh_qc.py`
- Test: `tests/test_visualize_remesh_qc.py`

- [ ] Add failing tests that `none` writes QC CSV without PNG and `repaired-fail` writes only repaired FAIL PNG.
- [ ] Add `--figure-mode` choices and guard figure-writing calls while preserving all summary records.
- [ ] Run visualization tests.

### Task 3: Desktop control and visual clarity

**Files:**
- Modify: `desktop_app/ui/project_wizard.py`, `desktop_app/ui/main_window.py`, `scripts/build_desktop.ps1`
- Test: `tests/test_desktop_ui_flow.py`, `tests/test_build_desktop_script.py`

- [ ] Add failing tests for the Chinese QC selector, default value, result-workbench styling and ASCII PyInstaller name.
- [ ] Add the selector and transport its value into `RunOptions`; add result workbench styles; use ASCII PyInstaller `--name`.
- [ ] Run all affected desktop tests and the CLI parity test.
