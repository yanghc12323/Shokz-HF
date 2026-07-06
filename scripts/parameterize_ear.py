#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parameterize_ear.py — 主入口脚本
==================================

3D 耳模型跨模型参数化与特征值计算流水线入口.

使用方式:
  # 模拟模式 (无参数, 自动生成数据并运行)
  python scripts/parameterize_ear.py

  # 真实数据模式 (单样本)
  python scripts/parameterize_ear.py \
    --sample_id S001 --side R \
    --mesh data/clean_mesh/S001_R.ply \
    --landmarks data/landmarks/S001_R_landmarks.csv \
    --regions config/region_table.csv \
    --out_points output/parameterized_points/S001_R_points.csv \
    --out_qc output/qc/S001_R_qc.csv

技术依据:
  《人头给你了-3D 耳模型跨模型参数化与特征值计算技术执行文档-v0.0》
"""

import sys
from pathlib import Path

# 确保项目根在 sys.path 中, 使 ear_param 包可导入
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ear_param.run import run_simulation, run_single_sample


def main() -> None:
    """解析命令行参数并执行对应模式."""
    import argparse

    parser = argparse.ArgumentParser(
        description="3D 耳模型跨模型参数化流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 模拟模式
  python scripts/parameterize_ear.py

  # 真实数据模式
  python scripts/parameterize_ear.py --sample_id S001 --side R \\
      --mesh data/clean_mesh/S001_R.ply \\
      --landmarks data/landmarks/S001_R_landmarks.csv \\
      --regions config/region_table.csv \\
      --out_points output/parameterized_points/S001_R_points.csv \\
      --out_qc output/qc/S001_R_qc.csv
        """,
    )

    parser.add_argument(
        "--sample_id", type=str, default=None,
        help="样本编号 (如 S001). 不提供则进入模拟模式."
    )
    parser.add_argument(
        "--side", type=str, default="R",
        help="左右侧: R 或 L (默认 R)."
    )
    parser.add_argument(
        "--mesh", type=str, default=None,
        help="Mesh 文件路径 (.ply/.obj/.stl)."
    )
    parser.add_argument(
        "--landmarks", type=str, default=None,
        help="特征点 CSV 文件路径."
    )
    parser.add_argument(
        "--regions", type=str, default="config/region_table.csv",
        help="区域定义表路径 (默认 config/region_table.csv)."
    )
    parser.add_argument(
        "--out_points", type=str, default=None,
        help="采样点输出路径."
    )
    parser.add_argument(
        "--out_qc", type=str, default=None,
        help="QC 报告输出路径."
    )

    args = parser.parse_args()

    # 模式判断: 是否提供了 sample_id?
    if args.sample_id is not None:
        # 真实数据模式
        if args.mesh is None:
            parser.error("--sample_id 模式下必须提供 --mesh")
        if args.landmarks is None:
            parser.error("--sample_id 模式下必须提供 --landmarks")
        if args.out_points is None:
            parser.error("--sample_id 模式下必须提供 --out_points")
        if args.out_qc is None:
            parser.error("--sample_id 模式下必须提供 --out_qc")

        run_single_sample(
            sample_id=args.sample_id,
            side=args.side,
            mesh_path=Path(args.mesh),
            landmarks_path=Path(args.landmarks),
            regions_csv=Path(args.regions),
            out_points=Path(args.out_points),
            out_qc=Path(args.out_qc),
            log_dir=_PROJECT_ROOT / "output" / "logs",
        )

    else:
        # 模拟模式
        run_simulation(project_root=_PROJECT_ROOT)


if __name__ == "__main__":
    main()