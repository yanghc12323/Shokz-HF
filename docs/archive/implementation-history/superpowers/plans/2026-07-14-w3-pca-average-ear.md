# W3 PCA Average Ear Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a validated PCA dataset and mean whole-ear mesh from aligned `weld_repaired` outputs.

**Architecture:** `ear_param/pca_average.py` owns manifest creation, topology validation, SVD, and artifact writers. `scripts/build_average_ear.py` remains a thin CLI wrapper. Tests use small temporary CSV fixtures to verify contracts independently of real subject files.

**Tech Stack:** Python 3, NumPy, pandas, trimesh, pytest.

## Global Constraints

- Input must be the `weld_repaired` layer and satisfy existing Weld and alignment gates.
- Preserve physical size; do not scale or align again in PCA.
- Use sorted `global_vertex_id` order and shared fixed faces.
- Make minimal scoped edits; do not change W2/Weld/alignment behavior.
- Update Chinese project documentation with every delivered feature.

---

### Task 1: PCA Input Contracts

**Files:**
- Create: `tests/test_pca_average.py`
- Create: `ear_param/pca_average.py`

**Interfaces:**
- Produces `load_pca_inputs(aligned_dir: Path, weld_dir: Path) -> PcaInput`.
- `PcaInput` contains `sample_tags`, `points`, `vertex_ids`, `faces`, and `manifest`.

- [ ] **Step 1: Write failing tests**

```python
def test_load_pca_inputs_sorts_vertex_ids_and_records_exclusions(tmp_path):
    inputs = load_pca_inputs(aligned_dir, weld_dir)
    assert inputs.sample_tags == ("S001_L", "S002_L")
    assert inputs.vertex_ids.tolist() == [0, 1, 2, 3]
    assert inputs.manifest.loc[inputs.manifest.sample_tag == "S003_L", "included"].item() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pca_average.py -v`

Expected: FAIL because `ear_param.pca_average` does not exist.

- [ ] **Step 3: Implement minimal input loader and validators**

```python
def load_pca_inputs(aligned_dir: Path, weld_dir: Path) -> PcaInput:
    manifest = build_pca_input_manifest(aligned_dir, weld_dir)
    included = manifest.loc[manifest["included"]].copy()
    if len(included) < 2:
        raise ValueError("At least two eligible aligned whole-ear samples are required.")
    return _load_included_meshes(included, aligned_dir)
```

Implement finite-coordinate, vertex-id, and face-topology validation before a
sample enters the returned matrix.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_pca_average.py -v`

Expected: PASS.

### Task 2: PCA Computation and Mean Ear

**Files:**
- Modify: `tests/test_pca_average.py`
- Modify: `ear_param/pca_average.py`

**Interfaces:**
- Produces `fit_pca(inputs: PcaInput, variance_threshold: float) -> PcaResult`.
- `PcaResult` exposes mean points, components, scores, explained variance, and `n_components_75`.

- [ ] **Step 1: Write failing tests**

```python
def test_fit_pca_selects_smallest_component_count_reaching_threshold(pca_inputs):
    result = fit_pca(pca_inputs, variance_threshold=0.75)
    assert result.n_components_75 == 1
    assert result.mean_points.shape == (4, 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pca_average.py::test_fit_pca_selects_smallest_component_count_reaching_threshold -v`

Expected: FAIL because `fit_pca` does not exist.

- [ ] **Step 3: Implement centered SVD**

```python
centered = matrix - matrix.mean(axis=0, keepdims=True)
_, singular_values, right_vectors = np.linalg.svd(centered, full_matrices=False)
explained_variance = singular_values**2 / (len(matrix) - 1)
```

Reject zero total variance and choose the first cumulative ratio at or above the
threshold.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_pca_average.py -v`

Expected: PASS.

### Task 3: Artifact Writer and CLI

**Files:**
- Create: `scripts/build_average_ear.py`
- Modify: `tests/test_pca_average.py`
- Modify: `ear_param/pca_average.py`

**Interfaces:**
- Produces `write_pca_outputs(inputs: PcaInput, result: PcaResult, out_dir: Path, variance_threshold: float) -> None`.
- CLI arguments: `--aligned_dir`, `--weld_dir`, `--out_dir`, `--variance_threshold`.

- [ ] **Step 1: Write failing artifact and CLI tests**

```python
def test_write_pca_outputs_creates_mean_mesh_and_statistics(tmp_path, pca_inputs):
    result = fit_pca(pca_inputs, 0.75)
    write_pca_outputs(pca_inputs, result, tmp_path, 0.75)
    assert (tmp_path / "mean_whole_ear.ply").is_file()
    assert (tmp_path / "explained_variance.csv").is_file()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pca_average.py::test_write_pca_outputs_creates_mean_mesh_and_statistics -v`

Expected: FAIL because `write_pca_outputs` does not exist.

- [ ] **Step 3: Write CSV, NPY, PLY, and PC mode artifacts; add thin CLI**

Export mean coordinates with global vertex IDs, source faces, PCA matrices,
sample scores, and +/- 2 standard-deviation PLY meshes for retained components.

- [ ] **Step 4: Run PCA tests**

Run: `python -m pytest tests/test_pca_average.py -v`

Expected: PASS.

### Task 4: Real-Data Integration and Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/W3 PCA 与平均耳技术路线.md`

- [ ] **Step 1: Rebuild current `weld_repaired` outputs**

Run: `python scripts/build_whole_ear.py --input_dir output/parameterized_points_r24/salvaged --regions config/region_table.csv --mesh_dir data/clean_mesh --enable_edge_repair --out_dir output/whole_ear_r24/weld_repaired`

- [ ] **Step 2: Rerun rigid alignment**

Run: `python scripts/align_whole_ear.py --whole_ear_dir output/whole_ear_r24/weld_repaired --landmarks_dir data/landmarks --out_dir output/whole_ear_r24/aligned_weld_repaired`

- [ ] **Step 3: Run PCA against real current inputs**

Run: `python scripts/build_average_ear.py --aligned_dir output/whole_ear_r24/aligned_weld_repaired --weld_dir output/whole_ear_r24/weld_repaired --out_dir output/w3_pca_r24`

- [ ] **Step 4: Document inputs, gates, commands, outputs, and actual run summary**

Update the W3 technical route and README links without reverting the user's Chinese document renames.

- [ ] **Step 5: Run full regression suite**

Run: `python -m pytest -q`

Expected: all existing tests plus the new PCA tests pass.
