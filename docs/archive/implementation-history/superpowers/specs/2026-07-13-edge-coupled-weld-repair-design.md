# Shared-Edge Coupled Weld Repair Design

## Goal

Add a conservative whole-ear post-salvage repair layer that can promote only
small, well-supported weld WARNING cases to PCA-ready PASS. The layer must
preserve the existing W2 remesh outputs and must not automatically promote
whole-ear FAIL cases caused by upstream raw FAIL regions.

## Scope and Non-Goals

The input remains `output/parameterized_points_r24/salvaged`. Existing
`raw`, `repaired`, `salvaged`, and current weld outputs are retained without
modification.

The new layer repairs a shared-edge point only when the two region copies are
both repaired rather than raw mapped. It does not alter the region interior,
change the region table, change the W2 remesh method, relax QC thresholds, or
try to resolve degenerate faces.

## Output Layers

The current output directory remains the immutable baseline:

```text
output/whole_ear_r24/salvaged/
```

The new output directory is:

```text
output/whole_ear_r24/weld_repaired/
```

The new directory contains one copied global template plus, for each sample:

```text
<sample>_whole_ear_points.csv
<sample>_whole_ear_faces.csv
<sample>_whole_ear_welded.ply
<sample>_weld_qc_edges.csv
<sample>_weld_qc_vertices.csv
<sample>_weld_qc_summary.csv
<sample>_weld_qc.png
<sample>_edge_repair_qc.csv
```

`edge_repair_qc.csv` records every candidate point, including rejected points,
with its original conflict distance, eligibility decision, rejection reason,
anchor identities, repair method, displacement, and post-repair distance.

## Eligibility and Rejection Rules

An edge repair may be applied only when all conditions below are true:

1. The raw whole-ear edge status is WARNING: maximum conflict is greater than
   `0.25 mm` and no greater than `1.00 mm`.
2. Both regions adjacent to the shared edge have W2 `raw_status` of PASS or
   WARNING. Either raw FAIL rejects the edge.
3. Both regions have zero `degenerate_faces`.
4. The conflicting points form one contiguous run no longer than two template
   samples.
5. Every point in that run has two finite, non-mapped repaired candidates.
6. Each run has a trusted anchor before and after it. A trusted anchor is a
   raw mapped point or a `landmark_vertex` point at the edge endpoint.
7. The resulting point is finite and can be projected to the sample's original
   input mesh.
8. Recalculated maximum edge conflict is no greater than `0.25 mm`.

Any rejected attempt remains unchanged and retains its baseline raw weld
status. A raw FAIL adjacent region is a permanent rejection for the automatic
repair layer, even if interpolation would numerically reduce the conflict.

## Repair Method

For one eligible contiguous run, use the adjacent anchor coordinates to form
one canonical edge curve. For each missing edge index, interpolate according
to its position between the anchors. Project the result to the original sample
mesh using nearest-surface projection. Assign the same projected coordinate to
both local region copies and label both copies `edge_coupled_interpolation`.

The new coordinate is never a blind average of the two conflicting repaired
coordinates. The output is controlled by the shared edge ordering, the two
trusted anchors, and the physical sample mesh.

## QC Meaning

The new QC keeps the baseline `raw_weld_status` separate from the final
`status`:

- `raw_weld_status`: result before edge-coupled repair.
- `edge_repair_attempted`: at least one candidate edge was evaluated.
- `edge_repair_applied`: at least one candidate run passed every guardrail.
- `edge_repair_count`: number of repaired shared template points.
- `status`: final weld status after accepted repair attempts.
- `pca_ready`: true only when the final status is PASS and all existing
  structural checks remain valid.

The QC image shows the welded whole-ear surface, shared boundaries, and
separate markers for successful and rejected repair candidates. It labels
both raw and final status so repair never conceals the original evidence.

## Expected Current-Sample Behavior

T094_L and T097_L are candidates because each has a local WARNING conflict
near one landmark endpoint, no degenerate faces, and an adjacent raw-mapped
anchor. They can be promoted only if mesh projection and final QC pass.

T049_L must remain FAIL because edge L13-L17 is adjacent to T003, whose raw
region status is FAIL and whose raw unmapped count is 90. The repair QC will
record the rejection reason `adjacent_raw_fail`.

The existing PASS samples must be copied unchanged into the new output layer.

## Downstream Contract

Rigid alignment and W3 PCA will use only:

```text
output/whole_ear_r24/weld_repaired/<sample>_whole_ear_points.csv
output/whole_ear_r24/weld_repaired/<sample>_whole_ear_faces.csv
output/whole_ear_r24/weld_repaired/<sample>_weld_qc_summary.csv
```

The alignment script must continue to select samples only when `status=PASS`
and `pca_ready=true`. It must not include raw WARNING or raw FAIL evidence in
the PCA input merely because a repaired PLY exists.
