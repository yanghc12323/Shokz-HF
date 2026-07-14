# Legacy KDTree Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the obsolete KDTree parameterisation route while preserving the remesh workflow's fixed barycentric-grid primitive and updating project documentation.

**Architecture:** The only active dependency on the legacy route is `make_barycentric_grid`, currently imported by `ear_param/remesh.py` from `ear_param/core.py`. Move that small deterministic helper into `remesh.py`, then remove the old command path, its implementation modules, its test-only fixtures/tests, and documentation that describes the retired route. Preserve `ear_param/io_utils.py`, current remesh/W2/Weld/W3 modules, current outputs, and historical progress reports.

**Tech Stack:** Python 3.14, NumPy, pytest, ripgrep, Git.

## Global Constraints

- Delete only the user-approved KDTree legacy route; do not remove current remesh, weld, alignment, data, or output files.
- Keep the barycentric point ordering and validation behavior unchanged.
- Do not overwrite unrelated uncommitted work in the shared worktree.
- Update README and active documentation in the same change.

---

### Task 1: Decouple the active remesh helper

**Files:**
- Modify: `ear_param/remesh.py`
- Modify: `tests/test_remesh.py`
- Delete later: `ear_param/core.py`

**Interfaces:**
- Produces: `ear_param.remesh.make_barycentric_grid(resolution: int) -> np.ndarray`
- Preserves: rows `[lambda_a, lambda_b, lambda_c]` in `i`-outer, `j`-inner order and point count `(resolution + 1) * (resolution + 2) // 2`.

- [ ] **Step 1: Add a focused remesh-owned regression test**

```python
def test_make_barycentric_grid_has_stable_resolution_and_order():
    from ear_param.remesh import make_barycentric_grid

    grid = make_barycentric_grid(2)
    np.testing.assert_allclose(
        grid,
        [[1.0, 0.0, 0.0], [0.5, 0.0, 0.5], [0.0, 0.0, 1.0],
         [0.5, 0.5, 0.0], [0.0, 0.5, 0.5], [0.0, 1.0, 0.0]],
    )
```

- [ ] **Step 2: Move the implementation into `remesh.py`**

```python
def make_barycentric_grid(resolution: int) -> np.ndarray:
    if resolution < 1:
        raise ValueError(f"resolution must be >= 1, got: {resolution}")
    n_points = (resolution + 1) * (resolution + 2) // 2
    grid = np.empty((n_points, 3), dtype=float)
    # Fill in i-outer, j-inner order.
```

- [ ] **Step 3: Remove `from .core import make_barycentric_grid` and run the focused test**

Run: `python -m pytest tests/test_remesh.py -q`

Expected: PASS with no import from `ear_param.core`.

### Task 2: Remove the retired code path

**Files:**
- Delete: `ear_param/core.py`
- Delete: `ear_param/config.py`
- Delete: `ear_param/run.py`
- Delete: `ear_param/synthetic.py`
- Delete: `ear_param/visualization.py`
- Delete: `scripts/parameterize_ear.py`
- Delete: `scripts/validate_data.py`
- Delete: `tests/test_core.py`
- Delete: `tests/conftest.py`

**Interfaces:**
- Removes only the obsolete KDTree interpolation CLI and tests.
- Keeps `ear_param/io_utils.py` because current remesh and QC scripts import it.

- [ ] **Step 1: Confirm no remaining active imports of the deletion set**

Run: `rg -n "ear_param\.(core|config|run|synthetic|visualization)|from \\.(core|config|run|synthetic|visualization)" ear_param scripts tests`

Expected: no matches after Task 1, except none.

- [ ] **Step 2: Delete the approved files with `apply_patch`**

Use file-level delete patches only for the paths above. Do not delete `io_utils.py`, current W2/Weld modules, or outputs.

- [ ] **Step 3: Verify the active package imports and tests collect**

Run: `python -m pytest --collect-only -q`

Expected: current remesh, QC, whole-ear, and alignment tests collect without legacy fixtures.

### Task 3: Remove obsolete documentation and rewrite the project entry point

**Files:**
- Delete: `docs/legacy_readme_pre_remesh.md`
- Delete: `docs/non_remesh_code_assessment.md`
- Modify: `README.md`
- Modify: `docs/remesh_usage_w2.md`
- Modify: `docs/w3_pca_average_ear_technical_route.md`

**Interfaces:**
- README lists only the remesh/W2/Weld/Alignment path.
- Active W2/W3 documentation does not refer users to deleted legacy code or retained legacy-cleanup assessment.

- [ ] **Step 1: Remove the two obsolete legacy documents**

Use delete patches. Retain historical reports such as `docs/w2_mentor_progress_report.md` and `Daily_Report_2026-07-03.md`.

- [ ] **Step 2: Replace README's legacy section with a concise scope statement**

```markdown
## 12. Project Scope

The repository retains only the patch-based remesh, W2 QC, whole-ear weld,
and rigid-alignment pipeline. The earlier KDTree parameterisation route has
been removed and must not be used as a fallback or PCA input.
```

- [ ] **Step 3: Remove stale links and wording from active W2/W3 documents**

Run: `rg -n "legacy_readme_pre_remesh|non_remesh_code_assessment|scripts/parameterize_ear\.py|ear_param/(core|config|run|synthetic|visualization)\.py" README.md docs/remesh_usage_w2.md docs/qc_visualization_and_region_strategy.md docs/w3_pca_average_ear_technical_route.md docs/whole_ear_weld_and_alignment.md`

Expected: no active-doc references to deleted legacy artifacts.

### Task 4: Full verification

**Files:**
- Verify: active Python modules, tests, README, active docs.

- [ ] **Step 1: Run full regression tests**

Run: `python -m pytest -q`

Expected: all remaining tests pass; the known local `.pytest_cache` warning may remain.

- [ ] **Step 2: Compile active modules**

Run: `python -m py_compile ear_param/remesh.py ear_param/qc_visualization.py ear_param/whole_ear.py ear_param/alignment.py scripts/parameterize_ear_remesh.py scripts/visualize_remesh_qc.py scripts/build_whole_ear.py scripts/align_whole_ear.py`

Expected: exit code 0.

- [ ] **Step 3: Verify retired imports, scripts, tests, and docs are absent**

Run: `rg --files ear_param scripts tests docs | rg "(^|\\)(core\.py|config\.py|run\.py|synthetic\.py|visualization\.py|parameterize_ear\.py|validate_data\.py|test_core\.py|conftest\.py|legacy_readme_pre_remesh\.md|non_remesh_code_assessment\.md)$"`

Expected: no matches.

- [ ] **Step 4: Run `git diff --check` and inspect `git status --short`**

Expected: no whitespace errors; unrelated user data/output changes remain untouched.
