#!/usr/bin/env python3
"""Build W3 PCA outputs and a mean whole-ear mesh from aligned repaired ears."""

from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ear_param.pca_average import fit_pca, load_pca_inputs, write_pca_outputs


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Fit PCA and export an average ear from aligned weld-repaired meshes."
    )
    parser.add_argument(
        "--aligned_dir", default="output/whole_ear_r24/aligned_weld_repaired"
    )
    parser.add_argument("--weld_dir", default="output/whole_ear_r24/weld_repaired")
    parser.add_argument("--out_dir", default="output/w3_pca_r24")
    parser.add_argument("--variance_threshold", type=float, default=0.75)
    args = parser.parse_args()

    inputs = load_pca_inputs(Path(args.aligned_dir), Path(args.weld_dir))
    result = fit_pca(inputs, variance_threshold=args.variance_threshold)
    write_pca_outputs(
        inputs,
        result,
        Path(args.out_dir),
        variance_threshold=args.variance_threshold,
    )
    cumulative = result.cumulative_explained_variance_ratio[result.n_components_75 - 1]
    excluded = int((~inputs.manifest["included"]).sum())
    print("[W3 PCA] Included samples:", " ".join(inputs.sample_tags))
    print(f"[W3 PCA] Excluded samples: {excluded}")
    print(
        "[W3 PCA] Retained "
        f"{result.n_components_75} components for {args.variance_threshold:.0%} threshold "
        f"(cumulative {cumulative:.2%})."
    )
    print(f"[W3 PCA] Output: {Path(args.out_dir)}")


if __name__ == "__main__":
    main()
