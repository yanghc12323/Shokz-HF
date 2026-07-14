# Shared-Edge Coupled Weld Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conservative post-salvage shared-edge repair layer that can promote local whole-ear weld WARNING cases to PCA-ready PASS while preserving raw evidence and rejecting raw-FAIL-adjacent cases.

**Architecture:** Keep `output/whole_ear_r24/salvaged` immutable as the baseline. Extend `ear_param/whole_ear.py` with a pure edge-coupled repair function: it evaluates raw edge QC, detects short runs of two repaired candidates, reconstructs each point from trusted anchors, projects it to the original mesh, and returns updated local point coordinates plus audit records. The existing assembly function then recomputes final whole-ear topology and QC from those updated points. The CLI writes the final layer to `output/whole_ear_r24/weld_repaired`.

**Tech Stack:** Python, NumPy, pandas, trimesh, matplotlib, pytest.

## Global Constraints

- Do not change or overwrite W2 `raw`, `repaired`, or `salvaged` files.
- Do not change or overwrite `output/whole_ear_r24/salvaged` baseline outputs.
- Repair only a baseline weld WARNING edge whose maximum conflict is in `(0.25, 1.00] mm`.
- Reject an edge if either adjacent W2 region has `raw_status=FAIL`, any adjacent region has `degenerate_faces > 0`, a run is longer than two points, a run lacks trusted anchors on both sides, or mesh projection fails.
- A trusted anchor is a raw mapped point (`quality_rank == 0`) or an endpoint `landmark_vertex` (`quality_rank == -1`).
- Successful repair must reduce the recomputed edge conflict to `<= 0.25 mm`; otherwise restore original coordinates and reject the attempt.
- Use nearest-surface projection on the sample's original mesh. Try `trimesh.proximity.closest_point`; fall back to `closest_point_naive` only if the acceleration dependency is absent.
- T049_L must remain FAIL because L13-L17 is adjacent to raw-FAIL T003. T094_L and T097_L are the intended first repair candidates.
- Preserve existing QC thresholds, point order, face order, and alignment behavior.

---

### Task 1: Model and test repair eligibility

**Files:**
- Modify: `tests/test_whole_ear.py`
- Modify: `ear_param/whole_ear.py`

**Interfaces:**
- Produces `repair_shared_edge_conflicts(template, points, region_qc, mesh, baseline, warning_mm, fail_mm, max_run_length=2) -> EdgeRepairResult`.
- `EdgeRepairResult.points` is a copy of the input local points with accepted edge points changed.
- `EdgeRepairResult.qc` has one row per candidate conflict point with `edge_id`, `edge_index`, `eligible`, `applied`, `rejection_reason`, `left_anchor_index`, `right_anchor_index`, `pre_distance_mm`, `post_distance_mm`, `projection_distance_mm`, and `repair_method`.

- [ ] **Step 1: Write the failing promotion test**

```python
def test_edge_repair_promotes_one_warning_point_between_landmark_and_mapped_anchor():
    template, points, faces, region_qc, mesh = _warning_edge_fixture(raw_statuses=("WARNING", "WARNING"))
    baseline = assemble_whole_ear(template, points, faces, region_qc)

    repair = repair_shared_edge_conflicts(template, points, region_qc, mesh, baseline)
    final = assemble_whole_ear(template, repair.points, faces, region_qc)

    assert baseline.summary.loc[0, "status"] == "WARNING"
    assert repair.qc["applied"].sum() == 1
    assert final.summary.loc[0, "status"] == "PASS"
    assert final.summary.loc[0, "pca_ready"]
```

- [ ] **Step 2: Run the promotion test to verify RED**

Run: `python -m pytest tests/test_whole_ear.py::test_edge_repair_promotes_one_warning_point_between_landmark_and_mapped_anchor -q`

Expected: FAIL because `repair_shared_edge_conflicts` does not exist.

- [ ] **Step 3: Write rejection tests before implementation**

```python
def test_edge_repair_rejects_raw_fail_adjacent_region():
    template, points, faces, region_qc, mesh = _warning_edge_fixture(raw_statuses=("FAIL", "WARNING"))
    baseline = assemble_whole_ear(template, points, faces, region_qc)

    repair = repair_shared_edge_conflicts(template, points, region_qc, mesh, baseline)

    assert not repair.qc["applied"].any()
    assert "adjacent_raw_fail" in set(repair.qc["rejection_reason"])
    pd.testing.assert_frame_equal(repair.points, points)


def test_edge_repair_rejects_run_longer_than_limit():
    template, points, faces, region_qc, mesh = _three_point_warning_fixture()
    baseline = assemble_whole_ear(template, points, faces, region_qc)

    repair = repair_shared_edge_conflicts(template, points, region_qc, mesh, baseline)

    assert not repair.qc["applied"].any()
    assert "conflict_run_too_long" in set(repair.qc["rejection_reason"])
```

- [ ] **Step 4: Run the rejection tests to verify RED**

Run: `python -m pytest tests/test_whole_ear.py::test_edge_repair_rejects_raw_fail_adjacent_region tests/test_whole_ear.py::test_edge_repair_rejects_run_longer_than_limit -q`

Expected: FAIL because `repair_shared_edge_conflicts` does not exist.

- [ ] **Step 5: Implement data types and candidate classification**

Add the following focused public result type and function in `ear_param/whole_ear.py`:

```python
@dataclass(frozen=True)
class EdgeRepairResult:
    points: pd.DataFrame
    qc: pd.DataFrame


def repair_shared_edge_conflicts(
    template: GlobalTemplate,
    points: pd.DataFrame,
    region_qc: pd.DataFrame,
    mesh: trimesh.Trimesh,
    baseline: WholeEarResult,
    *,
    warning_mm: float = 0.25,
    fail_mm: float = 1.0,
    max_run_length: int = 2,
) -> EdgeRepairResult:
    return EdgeRepairResult(points=updated_points, qc=repair_qc)
```

For each baseline WARNING edge, merge `template.edge_members` with local point
coordinates and calculate per-index candidate distance and quality ranks. Build
contiguous runs only from indices whose two finite candidates have
`quality_rank > 0` and a conflict distance greater than `warning_mm`. Reject
according to every global constraint and create an audit row for every
candidate point.

- [ ] **Step 6: Run Task 1 tests to verify GREEN**

Run: `python -m pytest tests/test_whole_ear.py -q`

Expected: PASS.

### Task 2: Reconstruct, project, and audit accepted runs

**Files:**
- Modify: `tests/test_whole_ear.py`
- Modify: `ear_param/whole_ear.py`

**Interfaces:**
- Consumes `EdgeRepairResult` eligibility data from Task 1.
- Produces coordinates marked with `repair_method="edge_coupled_interpolation"` and `raw_is_unmapped=True` for both local copies of each accepted edge point.

- [ ] **Step 1: Write a failing projection/provenance test**

```python
def test_edge_repair_projects_interpolated_point_and_updates_both_region_copies():
    template, points, faces, region_qc, mesh = _warning_edge_fixture(raw_statuses=("WARNING", "WARNING"))
    baseline = assemble_whole_ear(template, points, faces, region_qc)

    repair = repair_shared_edge_conflicts(template, points, region_qc, mesh, baseline)
    changed = repair.points.query("repair_method == 'edge_coupled_interpolation'")

    assert len(changed) == 2
    np.testing.assert_allclose(changed[["x", "y", "z"]].iloc[0], changed[["x", "y", "z"]].iloc[1])
    assert changed["z"].abs().max() == pytest.approx(0.0)
    assert repair.qc.loc[repair.qc["applied"], "projection_distance_mm"].notna().all()
```

- [ ] **Step 2: Run the test to verify RED**

Run: `python -m pytest tests/test_whole_ear.py::test_edge_repair_projects_interpolated_point_and_updates_both_region_copies -q`

Expected: FAIL because accepted runs are not reconstructed or projected.

- [ ] **Step 3: Implement anchor interpolation and mesh projection**

For each accepted run, find the nearest trusted index before and after the
run. For run index `k`, compute:

```python
fraction = (k - left_index) / (right_index - left_index)
interpolated = (1.0 - fraction) * left_xyz + fraction * right_xyz
projected, distance, _ = trimesh.proximity.closest_point(mesh, interpolated[None, :])
```

If accelerated projection raises an optional-dependency error, use
`trimesh.proximity.closest_point_naive`. Update both region copies at each
edge index to `projected[0]`, set `repair_method` to
`edge_coupled_interpolation`, and retain `raw_is_unmapped=True`. Record the
projection distance, both anchors, and pre/post candidate distances.

- [ ] **Step 4: Reassemble and enforce final conflict threshold**

After all candidate updates, call `assemble_whole_ear` with the trial points.
For each edge whose final conflict remains above `warning_mm`, restore every
point changed for that edge, mark `post_repair_conflict_above_warning`, and
reassemble once more. This prevents a partial repair from silently improving
only part of an unsafe edge.

- [ ] **Step 5: Run Task 2 tests to verify GREEN**

Run: `python -m pytest tests/test_whole_ear.py -q`

Expected: PASS.

### Task 3: Add batch CLI output and repair-aware QC

**Files:**
- Modify: `scripts/build_whole_ear.py`
- Modify: `tests/test_whole_ear.py`

**Interfaces:**
- Add CLI arguments `--mesh_dir`, `--enable_edge_repair`, and `--edge_repair_max_run_length`.
- `--mesh_dir` defaults to `data/clean_mesh`; the expected mesh filename is `<sample_tag>.ply`.
- With `--enable_edge_repair`, write only to a user-selected `--out_dir`, normally `output/whole_ear_r24/weld_repaired`.

- [ ] **Step 1: Write the failing CLI integration test**

```python
def test_build_whole_ear_cli_exports_edge_repair_qc_in_separate_layer():
    # Write a planar mesh, warning fixture points/faces/QC, and a region table.
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_whole_ear.py",
            "--input_dir", str(input_dir),
            "--regions", str(regions_path),
            "--mesh_dir", str(mesh_dir),
            "--enable_edge_repair",
            "--out_dir", str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert (output_dir / "S1_L_edge_repair_qc.csv").exists()
    summary = pd.read_csv(output_dir / "S1_L_weld_qc_summary.csv")
    assert summary.loc[0, "raw_weld_status"] == "WARNING"
    assert bool(summary.loc[0, "edge_repair_applied"])
    assert summary.loc[0, "status"] == "PASS"
```

- [ ] **Step 2: Run the CLI test to verify RED**

Run: `python -m pytest tests/test_whole_ear.py::test_build_whole_ear_cli_exports_edge_repair_qc_in_separate_layer -q`

Expected: FAIL because the CLI has no edge-repair mode or repair QC export.

- [ ] **Step 3: Implement separate-layer export**

Load `<sample_tag>.ply` only when `--enable_edge_repair` is passed. Assemble a
baseline result, call `repair_shared_edge_conflicts`, then assemble final
points. Augment final summary with:

```text
raw_weld_status
raw_weld_pca_ready
edge_repair_attempted
edge_repair_applied
edge_repair_count
edge_repair_rejected_count
```

Export `edge_repair_qc.csv` for all samples, including empty valid tables for
baseline PASS samples. Keep current output filenames for final repaired PLY,
points, faces, and weld QC.

- [ ] **Step 4: Extend the QC PNG**

Draw successful edge-coupled points in cyan and rejected candidates in
magenta. Use the final edge status for boundary color. Put both
`raw_weld_status` and final `status` in the figure title so the PNG is not
misread as raw evidence.

- [ ] **Step 5: Run Task 3 tests to verify GREEN**

Run: `python -m pytest tests/test_whole_ear.py -q`

Expected: PASS.

### Task 4: Run real data and update downstream alignment

**Files:**
- Modify: `scripts/align_whole_ear.py`
- Modify: `tests/test_alignment.py`
- Modify: `README.md`
- Modify: `docs/whole_ear_weld_and_alignment.md`
- Modify: `docs/w3_pca_average_ear_technical_route.md`
- Modify: `docs/remesh_usage_w2.md`
- Modify: `docs/qc_visualization_and_region_strategy.md`

**Interfaces:**
- The alignment CLI retains its `--whole_ear_dir` argument and must accept `output/whole_ear_r24/weld_repaired` without code-path changes.
- The alignment QC records source layer from the input weld summary for traceability.

- [ ] **Step 1: Write the failing alignment provenance test**

```python
def test_alignment_summary_records_weld_input_layer():
    # Reuse the two-sample alignment fixture and add input_layer=weld_repaired.
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/align_whole_ear.py",
            "--whole_ear_dir", str(whole_dir),
            "--landmarks_dir", str(landmarks_dir),
            "--out_dir", str(out_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    summary = pd.read_csv(out_dir / "alignment_qc_summary.csv")
    assert set(summary["input_layer"]) == {"weld_repaired"}
```

- [ ] **Step 2: Run the test to verify RED**

Run: `python -m pytest tests/test_alignment.py::test_alignment_summary_records_weld_input_layer -q`

Expected: FAIL because alignment summary does not export `input_layer`.

- [ ] **Step 3: Implement provenance and run repaired batch**

Read `input_layer` from each weld summary, require that all selected samples
use one value, and write it to every alignment QC row. Then run:

```powershell
python scripts/build_whole_ear.py --input_dir output/parameterized_points_r24/salvaged --regions config/region_table.csv --mesh_dir data/clean_mesh --enable_edge_repair --out_dir output/whole_ear_r24/weld_repaired
python scripts/align_whole_ear.py --whole_ear_dir output/whole_ear_r24/weld_repaired --landmarks_dir data/landmarks --out_dir output/whole_ear_r24/aligned_weld_repaired
```

Inspect the final summaries, T094/T097/T049 repair-QC CSVs, PLYs, and PNGs.
Do not replace the existing baseline alignment directory.

- [ ] **Step 4: Update user and AI-facing documentation**

Document the baseline and repaired output directories, all eligibility rules,
rejection reasons, repair-QC columns, commands, actual T094/T097/T049 results,
and the rule that W3 reads only PASS samples from the repaired layer. Keep the
baseline results documented as a comparison record.

- [ ] **Step 5: Run full verification**

Run:

```powershell
python -m pytest -q
python -m py_compile ear_param/whole_ear.py scripts/build_whole_ear.py scripts/align_whole_ear.py
git diff --check
```

Expected: zero test failures, valid Python syntax, and no whitespace errors.
