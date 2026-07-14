# W3 PCA Average Ear Design

## Goal

Build the W3 analysis module that converts topology-consistent, rigidly aligned
whole-ear meshes into a reproducible PCA dataset, PCA statistics, and a mean-ear
mesh. The module must consume only the repaired whole-ear layer that is approved
for downstream analysis.

## Input Contract

The command accepts:

- `aligned_dir`: an output directory produced by `scripts/align_whole_ear.py`.
- `weld_dir`: the corresponding `weld_repaired` directory produced by
  `scripts/build_whole_ear.py --enable_edge_repair`.

An included sample must satisfy all of the following:

1. Its row in `alignment_qc_summary.csv` has `status=PASS`.
2. The row has `input_layer=weld_repaired`.
3. Its `<sample_tag>_weld_qc_summary.csv` has `pca_ready=True` and
   `input_layer=weld_repaired`.
4. Its aligned points are finite and have one unique, ordered set of
   `global_vertex_id` values shared by every included sample.
5. Its aligned faces have the same global topology as every included sample.

Samples that fail a gate are recorded in an input manifest with an exclusion
reason. At least two samples must remain after gating.

## PCA Model

For each included sample, sort points by `global_vertex_id`, form an `(V, 3)`
array, and flatten it to a vector of length `3V`. Stack vectors into an `(N, 3V)`
matrix. No scaling or another alignment step is performed: the existing rigid
alignment preserves physical size, which W3 must retain.

Use centered NumPy SVD. The mean vector is the average of the input rows;
explained variance is `singular_value**2 / (N - 1)`. Retain the smallest number
of nonzero components whose cumulative explained-variance ratio is at least the
requested threshold (default `0.75`).

## Outputs

The output directory contains:

- `pca_input_manifest.csv`: sample-level inclusion and exclusion decisions.
- `pca_summary.csv`: run-level counts, vertex/face counts, threshold, and
  selected component count.
- `mean_whole_ear_points.csv`, `mean_whole_ear_faces.csv`, and
  `mean_whole_ear.ply`: the average ear in aligned coordinates.
- `components.npy`: principal axes in flattened `x,y,z` vertex order.
- `scores.csv`: each included sample's PCA scores.
- `explained_variance.csv`: variance, ratio, cumulative ratio, and whether a
  component belongs to the >=75% retained set.
- `pc_modes/PC##_plus_2sd.ply` and `pc_modes/PC##_minus_2sd.ply`: the first
  retained principal modes for visual inspection.

## Scope Boundaries

- Do not alter W2 remeshing, repair, welding, or rigid-alignment algorithms.
- Do not implement the later all-in-one batch orchestrator in this change.
- Do not use any mesh that is not explicitly in the `weld_repaired` layer.
- Preserve current user data and uncommitted document renames.

## Validation

Automated tests cover ordering, provenance gates, finite-coordinate checks,
topology consistency, PCA retention, and command-line artifacts. Integration
validation reruns current real data through weld-repaired, rigid alignment, and
the new PCA command before reporting final sample counts.
