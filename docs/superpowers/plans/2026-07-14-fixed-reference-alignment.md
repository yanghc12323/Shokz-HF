# Fixed Reference Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional fixed-reference rigid-alignment and PCA path without changing GPA-PCA defaults.

**Architecture:** The landmark Kabsch implementation remains centralized in `ear_param.alignment`. The alignment CLI selects GPA or an explicit reference target, while the formal pipeline runs the second path only when a reference sample is provided. Both paths write independent directories.

**Tech Stack:** Python, NumPy, pandas, trimesh, matplotlib, pytest.

## Global Constraints

- Preserve existing GPA outputs and default batch behavior.
- Use only rigid rotation and translation after canonical-L normalization.
- Keep the two PCA input/output layers separate.

---

### Task 1: Fixed-reference Landmark Core

**Files:**
- Modify: `ear_param/alignment.py`
- Test: `tests/test_alignment.py`

- [x] Write a failing test that aligns a rotated/translated sample to a named reference landmark set and asserts proper rotation, zero residual, and unchanged pairwise distances.
- [x] Implement `fixed_reference_alignment(landmark_sets, reference_sample)` returning reference landmarks, per-sample transforms, and aligned landmarks.
- [x] Run `python -m pytest tests/test_alignment.py -q` and confirm the new core test passes.

### Task 2: Alignment CLI Mode

**Files:**
- Modify: `scripts/align_whole_ear.py`
- Test: `tests/test_alignment.py`

- [x] Write a failing CLI integration test for `--alignment_mode fixed_reference --reference_sample S1_L`, asserting separate reference-landmark output, reference metadata, and aligned PLY files.
- [x] Add the alignment-mode option, require a supplied reference sample for fixed-reference mode, and write method/reference audit fields without altering GPA filenames.
- [x] Run `python -m pytest tests/test_alignment.py -q` and confirm all alignment tests pass.

### Task 3: Formal Batch and PCA Branch

**Files:**
- Modify: `ear_param/pipeline.py`
- Modify: `scripts/run_full_pipeline.py`
- Test: `tests/test_pipeline.py`

- [x] Write a failing pipeline test showing that an explicit reference sample invokes a separate reference alignment/PCA branch and records its status without changing GPA inclusion.
- [x] Add optional reference-stage functions, isolated directories, status columns, and CLI `--reference-sample` handling.
- [x] Run `python -m pytest tests/test_pipeline.py -q` and confirm the branch test passes.

### Task 4: Documentation and Regression

**Files:**
- Modify: `README.md`
- Modify: `docs/W3 PCA 与平均耳技术路线.md`

- [x] Document purpose, commands, output directories, and the rule that the two PCA branches never mix inputs.
- [x] Run `python -m pytest -q --basetemp .test_artifacts\\fixed_reference_full`.
- [x] Run `git diff --check` and update the README test count to the verified total.
