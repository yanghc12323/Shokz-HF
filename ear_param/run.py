#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py — 流程编排模块
======================

本模块负责将各子模块串联成完整的工作流.
提供两个入口:

1. run_simulation()
   模拟模式: 自动生成数据 → 批量参数化 → QC 报告
   对应命令行: python scripts/parameterize_ear.py (无参数)

2. run_single_sample()
   单样本模式: 加载指定 mesh + landmarks → 参数化 → 输出
   对应命令行: python scripts/parameterize_ear.py --sample_id ... (带参数)

技术依据:
  《人头给你了-3D 耳模型跨模型参数化与特征值计算技术执行文档-v0.0》
    第 3 章 - 参数化流水线
"""

import sys
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import trimesh

from .config import (
    SIMULATED_SAMPLES,
    SIMULATED_SIDE,
    DIR_CLEAN_MESH,
    DIR_LANDMARKS,
    DIR_OUTPUT_POINTS,
    DIR_OUTPUT_QC,
    DIR_OUTPUT_LOGS,
    DIR_OUTPUT_FIGURES,
    PATH_REGION_TABLE,
)
from .io_utils import (
    setup_logging,
    read_csv_robust,
    load_mesh,
    load_landmarks,
)
from .core import process_region
from .synthetic import generate_all_simulated_data
from .visualization import visualize_sample, visualize_qc_summary


# ============================================================================
# 内部辅助 - 确保输出目录存在
# ============================================================================

def _ensure_dirs(
    project_root: Path,
) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
    """创建并返回所有输出目录."""
    clean_mesh_dir = project_root / DIR_CLEAN_MESH
    landmarks_dir = project_root / DIR_LANDMARKS
    output_points_dir = project_root / DIR_OUTPUT_POINTS
    output_qc_dir = project_root / DIR_OUTPUT_QC
    output_figures_dir = project_root / DIR_OUTPUT_FIGURES
    log_dir = project_root / DIR_OUTPUT_LOGS

    for d in [clean_mesh_dir, landmarks_dir, output_points_dir, output_qc_dir,
              output_figures_dir, log_dir]:
        d.mkdir(parents=True, exist_ok=True)

    return clean_mesh_dir, landmarks_dir, output_points_dir, output_qc_dir, \
        output_figures_dir, log_dir


# ============================================================================
# 模拟模式 - 一键运行
# ============================================================================

def run_simulation(
    project_root: Path | None = None,
) -> None:
    """
    模拟模式: 一键生成数据并完成全部参数化.

    流程:
      1. 生成三个模拟样本的 mesh 和 landmarks
      2. 加载区域定义表
      3. 对每个样本依次参数化
      4. 输出采样点 CSV 和 QC 报告
      5. 打印最终摘要

    Parameters
    ----------
    project_root : Path | None
        项目根目录. 为 None 时自动检测.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    (
        clean_mesh_dir, landmarks_dir,
        output_points_dir, output_qc_dir, output_figures_dir, log_dir,
    ) = _ensure_dirs(project_root)

    # 设置主日志
    main_logger = setup_logging("SIMULATION", "ALL", log_dir)
    main_logger.info("=" * 60)
    main_logger.info("开始一键模拟流程")
    main_logger.info(f"项目根目录: {project_root}")
    main_logger.info("=" * 60)

    # Step 1: 生成模拟数据
    generate_all_simulated_data(clean_mesh_dir, landmarks_dir, main_logger)

    # Step 2: 检查区域表
    regions_csv = project_root / PATH_REGION_TABLE
    if not regions_csv.exists():
        main_logger.error(f"区域表不存在: {regions_csv}")
        sys.exit(1)
    regions = read_csv_robust(regions_csv, main_logger)
    main_logger.info(f"区域表: {len(regions)} 个区域")
    for _, r in regions.iterrows():
        n_expected = (int(r["resolution"]) + 1) * (int(r["resolution"]) + 2) // 2
        main_logger.info(
            f"  {r['region_id']}: {r['region_name']}, "
            f"resolution={r['resolution']}, 预期点数={n_expected}, "
            f"PCA={'是' if r.get('use_for_pca', False) else '否'}"
        )

    # Step 3: 批量参数化
    _batch_parameterize(
        sample_ids=SIMULATED_SAMPLES,
        side=SIMULATED_SIDE,
        clean_mesh_dir=clean_mesh_dir,
        landmarks_dir=landmarks_dir,
        regions=regions,
        output_points_dir=output_points_dir,
        output_qc_dir=output_qc_dir,
        output_figures_dir=output_figures_dir,
        log_dir=log_dir,
        main_logger=main_logger,
    )


# ============================================================================
# 真实数据模式 - 单样本参数化
# ============================================================================

def run_single_sample(
    sample_id: str,
    side: str,
    mesh_path: Path,
    landmarks_path: Path,
    regions_csv: Path,
    out_points: Path,
    out_qc: Path,
    log_dir: Path,
) -> None:
    """
    单样本参数化 (真实数据模式).

    加载指定 mesh 和 landmarks, 按区域表执行参数化, 输出结果.

    Parameters
    ----------
    sample_id : str
        样本编号 (如 'S001').
    side : str
        左右侧 ('R' 或 'L').
    mesh_path : Path
        Mesh 文件路径 (.ply/.obj/.stl).
    landmarks_path : Path
        特征点 CSV 文件路径.
    regions_csv : Path
        区域定义表路径.
    out_points : Path
        采样点输出路径.
    out_qc : Path
        QC 报告输出路径.
    log_dir : Path
        日志输出目录.
    """
    # 日志
    sample_logger = setup_logging(sample_id, side, log_dir)
    sample_logger.info("=" * 60)
    sample_logger.info(f"参数化: {sample_id}_{side}")
    sample_logger.info(f"  Mesh:      {mesh_path}")
    sample_logger.info(f"  Landmarks: {landmarks_path}")
    sample_logger.info(f"  Regions:   {regions_csv}")
    sample_logger.info("=" * 60)

    # 加载数据
    mesh = load_mesh(mesh_path, sample_logger)
    lms = load_landmarks(landmarks_path, sample_logger)

    # 加载区域表
    if not regions_csv.exists():
        sample_logger.error(f"区域表不存在: {regions_csv}")
        sys.exit(1)
    regions = read_csv_robust(regions_csv, sample_logger)

    # 检查 landmarks 完整性
    required_landmarks: set[str] = set()
    for _, row in regions.iterrows():
        required_landmarks.add(str(row["lm_a"]))
        required_landmarks.add(str(row["lm_b"]))
        required_landmarks.add(str(row["lm_c"]))
    missing_lms = required_landmarks - set(lms.index)
    if missing_lms:
        sample_logger.error(f"特征点缺失: {missing_lms}")
        raise ValueError(f"特征点缺失: {missing_lms}")

    # 参数化
    all_points, qc_list, region_details = _parameterize_sample(
        sample_id=sample_id,
        side=side,
        mesh=mesh,
        lms=lms,
        regions=regions,
        logger=sample_logger,
    )

    # 保存
    df_all = pd.concat(all_points, ignore_index=True)
    df_all.to_csv(out_points, index=False)
    pd.DataFrame(qc_list).to_csv(out_qc, index=False)

    # 摘要
    qc_df = pd.DataFrame(qc_list)
    pass_c = int((qc_df["status"] == "PASS").sum())
    warn_c = int((qc_df["status"] == "WARNING").sum())
    fail_c = int((qc_df["status"] == "FAIL").sum())

    sample_logger.info("")
    sample_logger.info(f"完成: 总点数={len(df_all)}, QC: PASS={pass_c} WARNING={warn_c} FAIL={fail_c}")
    sample_logger.info(f"输出: {out_points}")
    sample_logger.info(f"QC:    {out_qc}")


# ============================================================================
# 编排流程 - 批量参数化
# ============================================================================

def _batch_parameterize(
    sample_ids: list[str],
    side: str,
    clean_mesh_dir: Path,
    landmarks_dir: Path,
    regions: pd.DataFrame,
    output_points_dir: Path,
    output_qc_dir: Path,
    output_figures_dir: Path,
    log_dir: Path,
    main_logger: logging.Logger,
) -> None:
    """
    批量参数化多个样本.

    Parameters
    ----------
    sample_ids : list[str]
        样本编号列表.
    side : str
        左右侧.
    clean_mesh_dir : Path
        Mesh 文件目录.
    landmarks_dir : Path
        特征点文件目录.
    regions : pd.DataFrame
        区域定义表.
    output_points_dir : Path
        采样点输出目录.
    output_qc_dir : Path
        QC 输出目录.
    output_figures_dir : Path
        可视化图片输出目录.
    log_dir : Path
        日志目录.
    main_logger : logging.Logger
        主日志记录器.
    """
    main_logger.info("\n" + "=" * 60)
    main_logger.info("开始批量参数化...")
    main_logger.info("=" * 60)

    all_qc_summaries: list[dict] = []
    all_region_details: dict[str, dict[str, list]] = {}  # {sample_id: {region_name: [detail1, ...]}}

    for sample_id in sample_ids:
        mesh_path = clean_mesh_dir / f"{sample_id}_{side}.ply"
        landmarks_path = landmarks_dir / f"{sample_id}_{side}_landmarks.csv"
        out_points = output_points_dir / f"{sample_id}_{side}_points.csv"
        out_qc = output_qc_dir / f"{sample_id}_{side}_qc.csv"

        if not mesh_path.exists():
            main_logger.error(f"Mesh 文件不存在: {mesh_path}, 跳过 {sample_id}")
            continue
        if not landmarks_path.exists():
            main_logger.error(f"Landmarks 文件不存在: {landmarks_path}, 跳过 {sample_id}")
            continue

        # 样本级日志
        sample_logger = setup_logging(sample_id, side, log_dir)

        try:
            main_logger.info(f"\n--- 处理 {sample_id}_{side} ---")
            mesh = load_mesh(str(mesh_path), sample_logger)
            lms = load_landmarks(str(landmarks_path), sample_logger)

            # 检查 landmarks 完整性
            required_landmarks = set()
            for _, row in regions.iterrows():
                required_landmarks.add(str(row["lm_a"]))
                required_landmarks.add(str(row["lm_b"]))
                required_landmarks.add(str(row["lm_c"]))
            missing_lms = required_landmarks - set(lms.index)
            if missing_lms:
                raise ValueError(f"特征点缺失: {missing_lms}")

            # 参数化
            all_points, qc_list, region_details = _parameterize_sample(
                sample_id=sample_id,
                side=side,
                mesh=mesh,
                lms=lms,
                regions=regions,
                logger=sample_logger,
            )

            # 保存
            df_all = pd.concat(all_points, ignore_index=True)
            df_all.to_csv(out_points, index=False)
            pd.DataFrame(qc_list).to_csv(out_qc, index=False)

            # 保存可视化中间数据供后续使用
            all_region_details[sample_id] = region_details

            # 可视化
            _ = _generate_visualizations(
                sample_id=sample_id,
                side=side,
                mesh=mesh,
                lms=lms,
                qc_list=qc_list,
                region_details=region_details,
                output_figures_dir=output_figures_dir,
                logger=sample_logger,
            )

            # QC 摘要
            qc_df = pd.DataFrame(qc_list)
            pass_c = int((qc_df["status"] == "PASS").sum())
            warn_c = int((qc_df["status"] == "WARNING").sum())
            fail_c = int((qc_df["status"] == "FAIL").sum())

            sample_logger.info(
                f"  [{sample_id}] 完成: 总点数={len(df_all)}, "
                f"QC: PASS={pass_c} WARNING={warn_c} FAIL={fail_c}"
            )

            all_qc_summaries.append({
                "sample_id": sample_id,
                "side": side,
                "total_points": len(df_all),
                "regions": len(qc_list),
                "pass": pass_c,
                "warning": warn_c,
                "fail": fail_c,
            })

        except Exception as e:
            main_logger.error(f"{sample_id}_{side} 处理失败: {e}", exc_info=True)
            all_qc_summaries.append({
                "sample_id": sample_id,
                "side": side,
                "total_points": 0,
                "regions": 0,
                "pass": 0,
                "warning": 0,
                "fail": 5,
            })

    # 最终摘要
    _print_final_summary(all_qc_summaries, output_points_dir, output_qc_dir,
                         output_figures_dir, log_dir, main_logger)


# ============================================================================
# 编排流程 - 单样本参数化核心 (模拟/真实共用)
# ============================================================================

def _parameterize_sample(
    sample_id: str,
    side: str,
    mesh: trimesh.Trimesh,
    lms: pd.DataFrame,
    regions: pd.DataFrame,
    logger: logging.Logger,
) -> tuple[list[pd.DataFrame], list[dict], dict[str, dict]]:
    """
    对单个样本的所有区域执行参数化.

    Parameters
    ----------
    sample_id : str
        样本编号.
    side : str
        左右侧.
    mesh : trimesh.Trimesh
        耳 mesh.
    lms : pd.DataFrame
        特征点表 (以 landmark_id 为索引).
    regions : pd.DataFrame
        区域定义表.
    logger : logging.Logger
        日志记录器.

    Returns
    -------
    all_points : list[pd.DataFrame]
        各区域的采样点 DataFrame 列表.
    qc_list : list[dict]
        各区域的 QC 记录列表, 包含 'sample_id' 字段.
    region_details : dict[str, dict]
        各区域的中间数据, 键为 region_name, 供可视化使用.
    """
    all_points: list[pd.DataFrame] = []
    qc_list: list[dict] = []
    region_details: dict[str, dict] = {}
    global_id = 0

    for _, row in regions.iterrows():
        region = row.to_dict()
        try:
            df_region, qc, detail = process_region(
                sample_id=sample_id,
                side=side,
                full_mesh=mesh,
                lms=lms,
                region=region,
                global_start_id=global_id,
                logger=logger,
            )
            # 注入 sample_id
            qc["sample_id"] = sample_id
            all_points.append(df_region)
            qc_list.append(qc)
            region_details[str(region.get("region_name", ""))] = detail
            global_id += len(df_region)
        except Exception as e:
            logger.error(f"区域 {region.get('region_id', '?')} 处理失败: {e}")
            qc_list.append({
                "sample_id": sample_id,
                "region_id": str(region.get("region_id", "?")),
                "region_name": str(region.get("region_name", "")),
                "used_patch_file": False,
                "source_point_count": 0,
                "sample_point_count": 0,
                "expected_point_count": (
                    (int(region.get("resolution", 0)) + 1)
                    * (int(region.get("resolution", 0)) + 2) // 2
                ),
                "fallback_ratio": 1.0,
                "interpolator": "N/A",
                "status": "FAIL",
            })
            continue

    return all_points, qc_list, region_details


# ============================================================================
# 可视化生成封装
# ============================================================================

def _generate_visualizations(
    sample_id: str,
    side: str,
    mesh: trimesh.Trimesh,
    lms: pd.DataFrame,
    qc_list: list[dict],
    region_details: dict[str, dict],
    output_figures_dir: Path,
    logger: logging.Logger,
) -> list[Path]:
    """
    为单个样本生成全部可视化图片.

    Parameters
    ----------
    sample_id : str
        样本编号.
    side : str
        左右侧.
    mesh : trimesh.Trimesh
        耳 mesh.
    lms : pd.DataFrame
        特征点表.
    qc_list : list[dict]
        QC 记录列表.
    region_details : dict[str, dict]
        各区域中间数据, 键为 region_name.
    output_figures_dir : Path
        图片输出目录.
    logger : logging.Logger
        日志记录器.

    Returns
    -------
    saved_paths : list[Path]
        生成的所有图片文件路径列表.
    """
    saved_paths: list[Path] = []

    try:
        saved_paths.extend(visualize_sample(
            sample_id=sample_id,
            side=side,
            mesh=mesh,
            lms=lms,
            region_details=region_details,
            output_figures_dir=output_figures_dir,
            logger=logger,
        ))
        logger.info(f"  可视化: 样本图片已生成 ({len(saved_paths)} 张)")
    except Exception as e:
        logger.error(f"  可视化: 样本图片生成失败: {e}")

    return saved_paths


# ============================================================================
# 最终摘要
# ============================================================================

def _print_final_summary(
    all_qc_summaries: list[dict],
    output_points_dir: Path,
    output_qc_dir: Path,
    output_figures_dir: Path,
    log_dir: Path,
    logger: logging.Logger,
) -> None:
    """打印批量参数化的最终摘要."""
    logger.info("\n" + "=" * 60)
    logger.info("批量参数化完成 - 最终摘要")
    logger.info("=" * 60)

    summary_df = pd.DataFrame(all_qc_summaries)
    for _, s in summary_df.iterrows():
        status_icon = "OK" if s["fail"] == 0 else "FAIL"
        logger.info(
            f"  {status_icon} {s['sample_id']}_{s['side']}: "
            f"总点={s['total_points']}, "
            f"PASS={s['pass']}, WARN={s['warning']}, FAIL={s['fail']}"
        )

    logger.info(f"\n输出目录:")
    logger.info(f"  点云:   {output_points_dir}")
    logger.info(f"  QC:     {output_qc_dir}")
    logger.info(f"  图片:   {output_figures_dir}")
    logger.info(f"  日志:   {log_dir}")
    logger.info("=" * 60)
