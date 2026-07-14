# Canonical L-Side Normalization Design

## Goal

Allow left and right ears to enter one W2/W3 pipeline by converting every
input to a canonical left-ear coordinate convention before remesh. Existing
left-ear results must remain unchanged.

## Behavior

- `L` samples are copied unchanged into the canonical-input layer.
- `R` samples are reflected across a configurable axis, default `x`; triangle
  winding is reversed after reflection and all landmark coordinates are
  reflected by the same operation.
- Original `data/clean_mesh` and `data/landmarks` files are never modified.
- The canonical layer writes PLY, landmark CSV, and JSON audit data containing
  source side, canonical side `L`, mirror axis, and whether reflection occurred.
- Pipeline remesh/QC uses canonical files, while output sample tags retain the
  original suffix such as `T120_R` for traceability.
- A batch with an unknown side is recorded as `INVALID_SIDE` and skipped.

## Integration

`ear_param/canonicalization.py` owns coordinate reflection and artifact writing.
`ear_param/pipeline.py` canonicalizes paired inputs before remesh, records
`source_side`, `canonical_side`, `mirrored`, and `mirror_axis` in the batch
summary, and passes canonical directories to remesh, QC, and alignment.

The existing GPA alignment remains the only PCA coordinate alignment. The
absorbed fixed-reference, GUI, OBJ/STL export, and settings code are excluded.

## Validation

Tests prove that L coordinates/faces are unchanged, R coordinates are reflected
with reversed face order, landmark IDs are retained, malformed side tags are
rejected, and pipeline records contain canonicalization audit fields. Existing
PCA and alignment tests must remain green.
