# Whole-Ear Weld and Rigid Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the W2 `salvaged` region outputs into one fixed-topology whole-ear representation, perform boundary weld QC, and rigidly align qualified ears for later PCA.

**Architecture:** Build one coordinate-independent global template from `region_table.csv`, merge shared landmark corners and shared template-edge samples by identity, then assemble each sample using deterministic coordinate selection and explicit weld QC. Apply rigid Kabsch/Generalized Procrustes only to whole-ear samples that pass the weld gate; topology and face order remain unchanged.

**Tech Stack:** Python, NumPy, pandas, trimesh, matplotlib, pytest.

## Global Constraints

- The formal input layer is `output/parameterized_points_r24/salvaged`.
- Do not change W2 remesh, repair, salvage, or existing output semantics.
- Preserve real ear size: alignment uses rotation and translation only, with `det(R)=+1`.
- Current data are left ears; do not mirror them.
- Reuse existing dependencies and keep all new behavior in focused modules and scripts.
- Every production behavior is introduced by a failing test first.

---

### Task 1: Global template topology

**Files:**
- Create: `ear_param/whole_ear.py`
- Create: `tests/test_whole_ear.py`

**Interfaces:**
- `build_global_template(regions: pd.DataFrame) -> GlobalTemplate`
- `GlobalTemplate.manifest: pd.DataFrame`
- `GlobalTemplate.local_to_global: dict[tuple[str, int], int]`

- [x] Write tests proving that shared landmark corners merge, shared edges merge in canonical landmark order even when local direction is reversed, and mismatched resolution/non-manifold edges raise `ValueError`.
- [x] Run `python -m pytest tests/test_whole_ear.py -q` and verify failure because the module/API does not exist.
- [x] Implement union-find based topology construction from barycentric subdivision indices.
- [x] Run the focused tests and verify they pass.

### Task 2: Whole-ear coordinate assembly and weld QC

**Files:**
- Modify: `ear_param/whole_ear.py`
- Modify: `tests/test_whole_ear.py`

**Interfaces:**
- `assemble_whole_ear(template, points_df, faces_df, qc_df, warning_mm, fail_mm) -> WholeEarResult`
- `WholeEarResult.points`, `faces`, `edge_qc`, `vertex_qc`, `summary`

- [x] Write failing tests for salvaged PASS gating, finite-coordinate checks, deterministic source priority (`mapped`, `landmark_vertex`, `smooth_near_vertex`, `smooth_internal`), and PASS/WARNING/FAIL distance thresholds.
- [x] Implement candidate selection without averaging and remap all local faces to global vertex IDs.
- [x] Add structural checks for missing regions, duplicate/degenerate faces, and stable global point order.
- [x] Run focused tests and verify they pass.

### Task 3: Whole-ear CLI and visual QC

**Files:**
- Create: `scripts/build_whole_ear.py`
- Modify: `tests/test_whole_ear.py`

**Interfaces:**
- Reads `*_remesh_points.csv`, `*_remesh_faces.csv`, and `*_remesh_qc.csv` from one salvaged directory.
- Writes global manifest, per-sample points/faces/PLY, edge/vertex/summary CSVs, and a 3D weld QC PNG.

- [x] Write a failing integration test using synthetic CSV inputs.
- [x] Implement sample discovery, CSV/PLY export, QC visualization, and terminal summary.
- [x] Verify the focused integration test.

### Task 4: Rigid Kabsch and Generalized Procrustes

**Files:**
- Create: `ear_param/alignment.py`
- Create: `tests/test_alignment.py`

**Interfaces:**
- `rigid_kabsch(source: np.ndarray, target: np.ndarray) -> RigidTransform`
- `generalized_procrustes(landmark_sets: dict[str, np.ndarray], ...) -> ProcrustesResult`
- `apply_rigid_transform(points, transform) -> np.ndarray`

- [x] Write failing tests using known rotations/translations, reflection-prone data, missing/rank-deficient landmarks, and multiple transformed samples.
- [x] Implement SVD Kabsch with explicit reflection correction and iterative rigid-only GPA.
- [x] Verify `det(R)=+1`, convergence, and pairwise distance preservation.

### Task 5: Alignment CLI and QC

**Files:**
- Create: `scripts/align_whole_ear.py`
- Modify: `tests/test_alignment.py`

**Interfaces:**
- Reads `PCA_READY` whole-ear outputs and `L7,L13,L15,L26` from landmark CSVs.
- Writes final mean landmarks, transforms, aligned points/faces/PLY, residual summary, and overlay PNG.

- [x] Write a failing synthetic batch integration test.
- [x] Implement qualified sample loading, GPA, transform export, mesh export, QC, and terminal summary.
- [x] Verify aligned face arrays are byte-for-byte identical across samples.

### Task 6: Real-data validation and documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/remesh_usage_w2.md`
- Modify: `docs/w3_pca_average_ear_technical_route.md`
- Create: `docs/whole_ear_weld_and_alignment.md`

- [x] Run the whole-ear CLI on all current salvaged samples.
- [x] Inspect weld summaries, output PLYs, and QC images; run alignment only on `PCA_READY` samples.
- [x] Document commands, schemas, thresholds, status meanings, actual sample results, and the handoff contract for PCA.
- [x] Run `python -m pytest -q` and confirm zero failures.
- [x] Review `git diff` to ensure unrelated W2/user changes were not overwritten.
