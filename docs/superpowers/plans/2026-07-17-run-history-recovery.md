# Run History Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a safe UI path from a historical failed attempt to a validated single-stage recovery.

**Architecture:** A read-only history service constructs attempt records from persisted desktop state and manifest files. A history panel passes a selected attempt to the existing expert recovery panel, which starts a child attempt and navigates to monitoring.

**Tech Stack:** Python 3.14, PySide6, JSON, pytest.

## Global Constraints

- Historical parent artifacts are never overwritten.
- Only `RecoveryService.plan()` may decide which recovery buttons are enabled.
- Recovery scripts do not expose pause/cancel safe checkpoints.

---

### Task 1: Discover persisted attempts

**Files:** `desktop_app/run_history_service.py`, `tests/test_desktop_run_history_service.py`

- [ ] Write tests for sorted attempt discovery, manifest error extraction and malformed-state skipping.
- [ ] Implement `RunHistoryService.list_attempts(project)` returning read-only history entries.
- [ ] Run the service tests.

### Task 2: Expose history and expert handoff

**Files:** `desktop_app/ui/run_history.py`, `desktop_app/ui/expert_mode.py`, `desktop_app/ui/main_window.py`, `tests/test_desktop_run_history.py`

- [ ] Write tests for selecting a recoverable row and reaching expert mode.
- [ ] Implement the history table and handoff signal; refresh after terminal runs.
- [ ] Run UI tests.

### Task 3: Prevent invalid recovery controls

**Files:** `desktop_app/run_controller.py`, `desktop_app/ui/run_monitor.py`, `tests/test_desktop_run_controller.py`

- [ ] Write a test that recovery attempts do not expose pause/cancel.
- [ ] Add controller capability state and disable unsupported monitor actions.
- [ ] Run focused controller/UI tests.
