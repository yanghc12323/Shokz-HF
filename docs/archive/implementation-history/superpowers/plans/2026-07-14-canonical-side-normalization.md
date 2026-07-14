# Canonical Side Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task.

**Goal:** Canonicalize R ears to L before remesh and remove the absorbed standalone module.

**Architecture:** Add a small canonicalization module, invoke it from the formal pipeline before remesh, preserve source tags/audit fields, and keep GPA as the sole PCA alignment.

**Tech Stack:** Python, NumPy, pandas, trimesh, pytest.

### Task 1: Geometry Tests and Module
- [x] Write failing tests for L identity, R reflection, reversed winding, and landmark preservation in `tests/test_canonicalization.py`.
- [x] Implement `canonicalize_sample()` in `ear_param/canonicalization.py`.
- [x] Run `python -m pytest tests/test_canonicalization.py -q`.

### Task 2: Pipeline Integration
- [x] Add canonical paths/options and preprocessing to `ear_param/pipeline.py` and CLI flags to `scripts/run_full_pipeline.py`.
- [x] Run focused pipeline tests.

### Task 3: Documentation and Cleanup
- [x] Update README and W3 route with canonical-L rules and commands.
- [x] Remove `modules/ear-coordinate-transform` after all absorbed behavior is covered.
- [x] Run full pytest regression and verify no references to the removed module remain.
