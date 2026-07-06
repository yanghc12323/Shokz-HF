#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
visualization.py — 可视化模块
================================

将流水线中间结果转化为可检查的图片，帮助验证参数化质量。

图片功能：
  1. 三维耳 mesh + 三角形区域 + 特征点标注（3D 视角）
  2. 参数空间散点图 (λ_b, λ_c) + 三角形边界
  3. 参数空间采样网格 (45 个固定采样点)
  4. 源面片在参数空间的覆盖情况
  5. 恢复的 3D 采样点云

仅依赖 matplotlib，无需额外安装。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # 非交互后端，适合服务器/批处理

import matplotlib.pyplot as plt
import matplotlib.tri as mtri
import numpy as np
import pandas as pd
import trimesh


# ============================================================================
# 全局样式
# ============================================================================

STYLE_DEFAULTS = {
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "savefig.bbox": "tight",
    "font.size": 8,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
}

plt.rcParams.update(STYLE_DEFAULTS)

# 颜色方案：每个区域一个颜色
REGION_COLORS = {
    "耳甲腔上区": "#e41a1c",
    "耳甲腔下区": "#377eb8",
    "耳甲腔前区": "#4daf4a",
    "耳屏区": "#ff7f00",
    "对耳屏区": "#984ea3",
}
DEFAULT_COLOR = "#999999"


def _get_color(region_name: str) -> str:
    """获取区域对应的颜色."""
    return REGION_COLORS.get(region_name, DEFAULT_COLOR)


# ============================================================================
# 辅助绘图函数
# ============================================================================

def _make_triangle_patch(pts_2d: np.ndarray, **kwargs) -> plt.Polygon:
    """创建三角形 Polygon patch."""
    return plt.Polygon(pts_2d, **kwargs)


def _barycentric_to_xy(lambda_b: np.ndarray, lambda_c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """重心坐标 (λ_b, λ_c) 映射到 XY 平面（等边三角形展开）."""
    # 使用等边三角形展开: x = λ_b + 0.5*λ_c, y = √3/2 * λ_c
    x = lambda_b + 0.5 * lambda_c
    y = (np.sqrt(3) / 2) * lambda_c
    return x, y


def _get_equilateral_triangle_vertices() -> np.ndarray:
    """返回等边三角形三个顶点在 XY 平面的坐标 [(A), (B), (C)]."""
    return np.array([
        [0.0, 0.0],           # A: (λ_b=0, λ_c=0)
        [1.0, 0.0],           # B: (λ_b=1, λ_c=0)
        [0.5, np.sqrt(3)/2],  # C: (λ_b=0, λ_c=1)
    ])


# ============================================================================
# 3D 网格绘制（matplotlib 3D）
# ============================================================================

def _draw_3d_mesh(
    ax: plt.Axes,
    mesh: trimesh.Trimesh,
    color: str = "#bbbbbb",
    alpha: float = 0.3,
    edge_color: str = "#cccccc",
    linewidth: float = 0.1,
) -> None:
    """在 3D Axes 上绘制 mesh 三角面片."""
    vertices = mesh.vertices
    faces = mesh.faces
    tri = mtri.Triangulation(
        vertices[:, 0], vertices[:, 1],
        triangles=faces,
    )
    ax.plot_trisurf(
        tri, vertices[:, 2],
        color=color, alpha=alpha,
        edgecolor=edge_color, linewidth=linewidth,
        shade=True,
    )


def _draw_3d_triangle(
    ax: plt.Axes,
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    color: str = "red",
    alpha: float = 0.3,
    label: str = "",
) -> None:
    """在 3D Axes 上绘制三角形区域."""
    verts = np.array([a, b, c, a])
    ax.plot(verts[:, 0], verts[:, 1], verts[:, 2],
            color=color, linewidth=1.5, label=label)
    # 半透明填充面
    tri_poly = mtri.Triangulation(
        verts[:3, 0], verts[:3, 1],
        triangles=[[0, 1, 2]],
    )
    ax.plot_trisurf(
        tri_poly, verts[:3, 2],
        color=color, alpha=alpha, shade=False,
    )


def _draw_3d_points(
    ax: plt.Axes,
    points: np.ndarray,
    color: str = "blue",
    size: float = 3.0,
    label: str = "",
) -> None:
    """在 3D Axes 上绘制散点."""
    ax.scatter(
        points[:, 0], points[:, 1], points[:, 2],
        c=color, s=size, label=label, alpha=0.9,
    )


# ============================================================================
# 可视化入口
# ============================================================================

def visualize_sample(
    sample_id: str,
    side: str,
    mesh: trimesh.Trimesh,
    lms: pd.DataFrame,
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
        特征点表 (以 landmark_id 为索引).
    region_details : dict[str, dict]
        各区域中间数据.

        每个 region_name 对应的字典应包含:
          - 'a_3d', 'b_3d', 'c_3d': 三角形顶点三维坐标
          - 'source_lambdas': 源点重心坐标 (N, 3) 数组, (λ_a, λ_b, λ_c)
          - 'target_grid_bc': 目标网格重心坐标 (M, 3) 数组
          - 'face_triangles_2d': 源面片在 (λ_b, λ_c) 空间的投影列表
          - 'sample_points_3d': 重建的 3D 采样点 (M, 3) 数组
          - 'region_name': 区域名称

    output_figures_dir : Path
        图片输出目录.
    logger : logging.Logger
        日志记录器.

    Returns
    -------
    saved_paths : list[Path]
        生成的所有图片文件路径列表.
    """
    output_figures_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []

    if not region_details:
        logger.warning("  可视化: region_details 为空，跳过.")
        return saved_paths

    # ----------------------------------------------------------------
    # 图 1: 3D 概览 — ear mesh + 所有三角形区域 + 特征点
    # ----------------------------------------------------------------
    try:
        fig = plt.figure(figsize=(10, 8))
        ax = fig.add_subplot(111, projection="3d")

        # 绘制 mesh
        _draw_3d_mesh(ax, mesh, alpha=0.15)

        # 收集 legend 代理句柄
        from matplotlib.lines import Line2D
        legend_handles: list = []

        # 绘制所有三角形区域
        for region_name, detail in region_details.items():
            a = detail.get("a_3d")
            b = detail.get("b_3d")
            c = detail.get("c_3d")
            if a is not None and b is not None and c is not None:
                clr = _get_color(region_name)
                _draw_3d_triangle(ax, a, b, c, color=clr, alpha=0.25)
                legend_handles.append(
                    Line2D([0], [0], color=clr, lw=2, label=region_name)
                )

        # 绘制特征点
        for lm_id, row in lms.iterrows():
            ax.scatter(row["x"], row["y"], row["z"],
                       c="black", s=15, marker="o")
            ax.text(row["x"], row["y"], row["z"],
                    f" {lm_id}", fontsize=6, color="black")

        ax.set_xlabel("X (mm)")
        ax.set_ylabel("Y (mm)")
        ax.set_zlabel("Z (mm)")
        ax.set_title(f"3D Ear Overview — {sample_id}_{side}")
        if legend_handles:
            ax.legend(handles=legend_handles, loc="upper right", fontsize=6, ncol=2)

        # 调整视角
        ax.view_init(elev=25, azim=-60)

        path_3d = output_figures_dir / f"{sample_id}_{side}_3d_overview.png"
        fig.savefig(path_3d, dpi=150)
        plt.close(fig)
        saved_paths.append(path_3d)
    except Exception as e:
        logger.warning(f"  可视化: 3D 概览图生成失败: {e}")

    # ----------------------------------------------------------------
    # 图 2-6: 每个区域的参数空间可视化
    # ----------------------------------------------------------------
    for region_name, detail in region_details.items():
        try:
            paths = _visualize_region(
                sample_id=sample_id,
                side=side,
                region_name=region_name,
                detail=detail,
                output_figures_dir=output_figures_dir,
            )
            saved_paths.extend(paths)
        except Exception as e:
            logger.warning(f"  可视化: 区域 {region_name} 图片生成失败: {e}")

    return saved_paths


def _visualize_region(
    sample_id: str,
    side: str,
    region_name: str,
    detail: dict,
    output_figures_dir: Path,
) -> list[Path]:
    """绘制单个区域的参数空间可视化（2 个子图并排）."""
    saved: list[Path] = []

    source_lambdas: Optional[np.ndarray] = detail.get("source_lambdas")
    target_grid_bc: Optional[np.ndarray] = detail.get("target_grid_bc")
    face_triangles_2d: Optional[list] = detail.get("face_triangles_2d")
    a_3d: Optional[np.ndarray] = detail.get("a_3d")
    b_3d: Optional[np.ndarray] = detail.get("b_3d")
    c_3d: Optional[np.ndarray] = detail.get("c_3d")
    sample_points_3d: Optional[np.ndarray] = detail.get("sample_points_3d")

    # 安全检查
    if source_lambdas is None or target_grid_bc is None:
        return saved

    clr = _get_color(region_name)
    safe_name = region_name.replace("/", "_").replace(" ", "_")

    # ------------------------------------------------------------
    # 子图：参数空间（源点、边界三角形、目标网格点）
    # ------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle(f"{sample_id}_{side} — {region_name} 参数空间")

    ax1 = axes[0]
    ax1.set_aspect("equal")

    # 等边三角形边界
    tri_verts = _get_equilateral_triangle_vertices()
    triangle_patch = _make_triangle_patch(
        tri_verts, fill=False, edgecolor="black", linewidth=1.5, linestyle="--",
    )
    ax1.add_patch(triangle_patch)

    # 源点
    src_x, src_y = _barycentric_to_xy(
        source_lambdas[:, 1], source_lambdas[:, 2],
    )
    ax1.scatter(src_x, src_y, c=clr, s=2, alpha=0.5, label="源点 (mesh vertices)")

    # 包含目标点的源面片（参数空间投影）
    if face_triangles_2d:
        for tri_2d in face_triangles_2d:
            tri_2d_xy = np.column_stack(
                _barycentric_to_xy(tri_2d[:, 1], tri_2d[:, 2]),
            )
            ax1.fill(tri_2d_xy[:, 0], tri_2d_xy[:, 1],
                     facecolor="lightgreen", edgecolor="green",
                     alpha=0.15, linewidth=0.3)

    # 目标网格点
    tgt_x, tgt_y = _barycentric_to_xy(
        target_grid_bc[:, 1], target_grid_bc[:, 2],
    )
    ax1.scatter(tgt_x, tgt_y, c="red", s=12, marker="x",
                label=f"目标网格 (n={len(target_grid_bc)})", zorder=5)

    # 三角形顶点标签
    labels = ["A", "B", "C"]
    for i, (v, lbl) in enumerate(zip(tri_verts, labels)):
        # 使用 landmark 名称
        lm_name = detail.get(f"lm_{lbl.lower()}", lbl)
        ax1.annotate(
            lm_name, v,
            textcoords="offset points", xytext=(-10, -10),
            fontsize=7, color="blue",
        )

    ax1.set_xlabel("x = λ_b + 0.5·λ_c")
    ax1.set_ylabel("y = √3/2 · λ_c")
    ax1.set_title("参数空间 (源点 + 目标网格)")
    ax1.legend(fontsize=6, loc="upper right")
    ax1.set_xlim(-0.1, 1.1)
    ax1.set_ylim(-0.05, 1.0)

    # ------------------------------------------------------------
    # 子图：恢复的 3D 采样点散点图（triplot 近似）
    # ------------------------------------------------------------
    ax2 = axes[1]

    if sample_points_3d is not None and a_3d is not None:
        # 用三角形顶点做 triplot 背景
        tri_3d = np.array([a_3d, b_3d, c_3d])
        # 绘制三角形
        for i in range(3):
            j = (i + 1) % 3
            ax2.plot(
                [tri_3d[i, 0], tri_3d[j, 0]],
                [tri_3d[i, 1], tri_3d[j, 1]],
                c="gray", linewidth=0.8, linestyle="--",
            )

        ax2.scatter(
            sample_points_3d[:, 0], sample_points_3d[:, 1],
            c=clr, s=8, alpha=0.8, edgecolors="black", linewidths=0.3,
            label=f"采样点 (n={len(sample_points_3d)})",
        )

        # 三角形顶点
        ax2.scatter(
            tri_3d[:, 0], tri_3d[:, 1],
            c="black", s=30, marker="^", zorder=10,
        )
        for lbl, v in zip(labels, tri_3d):
            lm = detail.get(f"lm_{lbl.lower()}", lbl)
            ax2.annotate(lm, v[:2], fontsize=7, color="black",
                         textcoords="offset points", xytext=(5, 5))

    ax2.set_xlabel("X (mm)")
    ax2.set_ylabel("Y (mm)")
    ax2.set_title("恢复的 3D 采样点 (XY 投影)")
    ax2.set_aspect("equal")
    ax2.legend(fontsize=6, loc="upper right")

    plt.tight_layout()
    path_region = output_figures_dir / f"{sample_id}_{side}_region_{safe_name}.png"
    fig.savefig(path_region, dpi=150)
    plt.close(fig)
    saved.append(path_region)

    return saved


def visualize_qc_summary(
    qc_file: Path,
    output_figures_dir: Path,
    logger: logging.Logger,
) -> Optional[Path]:
    """
    读取 QC 报告 CSV, 绘制各样本/各区域的 fallback_ratio 热力图.

    Parameters
    ----------
    qc_file : Path
        QC 报告 CSV 文件路径 (应包含 sample_id, region_name, fallback_ratio 等列).
    output_figures_dir : Path
        输出目录.
    logger : logging.Logger
        日志记录器.

    Returns
    -------
    saved_path : Path or None
        生成的图片路径.
    """
    output_figures_dir.mkdir(parents=True, exist_ok=True)

    try:
        qc_df = pd.read_csv(qc_file)
    except Exception as e:
        logger.warning(f"QC 热力图: 无法读取 {qc_file}: {e}")
        return None

    required_cols = {"sample_id", "region_name", "fallback_ratio"}
    missing = required_cols - set(qc_df.columns)
    if missing:
        logger.warning(f"QC 热力图: CSV 缺少必需列 {missing}, 跳过.")
        return None

    # 透视表
    pivot = qc_df.pivot_table(
        index="region_name", columns="sample_id",
        values="fallback_ratio", aggfunc="mean",
    )

    fig, ax = plt.subplots(figsize=(max(6, pivot.shape[1] * 1.2),
                                    max(4, pivot.shape[0] * 0.6)))
    im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn_r", vmin=0, vmax=0.3)

    # 标注数值
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            val = pivot.values[i, j]
            if not np.isnan(val):
                text_color = "white" if val > 0.15 else "black"
                ax.text(j, i, f"{val:.1%}", ha="center", va="center",
                        fontsize=7, color=text_color)

    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=45, ha="right", fontsize=7)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index, fontsize=7)
    ax.set_title("QC 热力图: Fallback Ratio by Region × Sample")

    cbar = plt.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("Fallback Ratio", fontsize=7)

    plt.tight_layout()
    path_qc = output_figures_dir / "qc_heatmap.png"
    fig.savefig(path_qc, dpi=150)
    plt.close(fig)

    logger.info(f"QC 热力图已保存: {path_qc}")
    return path_qc