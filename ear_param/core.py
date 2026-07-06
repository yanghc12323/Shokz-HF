#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.py — 核心算法模块
=======================

本模块实现了 3D 耳模型参数化的核心数学计算:

1. 三角形退化检测
2. 三角形区域源点提取 (裁剪)
3. 重心坐标投影 (最小二乘法)
4. 固定分辨率重心坐标网格生成
5. 插值重建采样点三维坐标
6. 单区域处理 (编排以上各步骤)
7. QC 评估

技术依据: 《人头给你了-3D 耳模型跨模型参数化与特征值计算技术执行文档-v0.0》
    第 3 章 — 三维三角区域投影至二维平面, 降采样

坐标约定:
  - 源点坐标系: 原始 mesh 顶点三维坐标 (x, y, z)
  - 参数坐标系: 三角形平面上的重心坐标 (lambda_a, lambda_b, lambda_c)
  - 约束: lambda_a + lambda_b + lambda_c = 1, 每个 lambda ∈ [0, 1]
"""

import logging
from typing import Any

import numpy as np
import pandas as pd
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import cKDTree

from .config import (
    PROJECTION_TOL,
    FALLBACK_WARNING_THRESHOLD,
    FALLBACK_FAIL_THRESHOLD,
    MIN_SOURCE_POINTS,
    DENSE_SAMPLE_COUNT,
)


# ============================================================================
# 二维展开 (UV Unwrapping) — Atlas 坐标映射
# ============================================================================

# Atlas 布局: 5 个区域排列在 3 列 × 2 行的网格中
# +-----------+-----------+-----------+
# |   T001    |   T002    |   T003    |
# | 耳甲腔上区 | 耳甲腔下区 | 耳甲腔前区 |
# |  col=0    |  col=1    |  col=2    |
# |  row=0    |  row=0    |  row=0    |
# +-----------+-----------+-----------+
# |   T004    |   T005    | (空)      |
# |  耳屏区   | 对耳屏区   |           |
# |  col=0    |  col=1    |           |
# |  row=1    |  row=1    |           |
# +-----------+-----------+-----------+

_ATLAS_COLS: int = 3

_ATLAS_REGION_LAYOUT: dict[str, tuple[int, int]] = {
    # region_id → (col, row)
    "T001": (0, 0),
    "T002": (1, 0),
    "T003": (2, 0),
    "T004": (0, 1),
    "T005": (1, 1),
}


def _to_atlas_uv(
    bary_grid: np.ndarray,
    region_id: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    将重心坐标网格转换为双层 UV 坐标 (local + atlas).

    Local UV:
      u_local = λ_b,  v_local = λ_c
      每个区域独立映射到单位三角形: (0,0)–(1,0)–(0,1).
      用途: 跨样本同区域对应点的归一化位置对齐.

    Atlas UV:
      u_atlas = col + λ_b,  v_atlas = row + λ_c
      其中 (col, row) 由 _ATLAS_REGION_LAYOUT 查找.
      所有区域共存于一张 3×2 网格的 2D 图上.
      用途: 全局可视化, 一眼辨认采样点的解剖位置.

    Parameters
    ----------
    bary_grid : np.ndarray, shape (K, 3)
        重心坐标网格, 每行 [λ_a, λ_b, λ_c].
    region_id : str
        区域编号, 如 'T001'.

    Returns
    -------
    u_local : np.ndarray, shape (K,)
    v_local : np.ndarray, shape (K,)
    u_atlas : np.ndarray, shape (K,)
    v_atlas : np.ndarray, shape (K,)
    """
    lambda_b = bary_grid[:, 1]
    lambda_c = bary_grid[:, 2]

    # Local UV — 直接等于重心坐标分量
    u_local = lambda_b.copy()
    v_local = lambda_c.copy()

    # Atlas UV — 加上区域所在网格单元偏移
    col, row = _ATLAS_REGION_LAYOUT.get(region_id, (0, 0))
    u_atlas = col + lambda_b
    v_atlas = row + lambda_c

    return u_local, v_local, u_atlas, v_atlas


# ============================================================================
# 三角形退化检测
# ============================================================================

def _is_triangle_degenerate(
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    eps: float = 1e-6,
) -> bool:
    """
    检测三角形是否退化 (三点共线或面积近乎为零).

    Parameters
    ----------
    a, b, c : np.ndarray, shape (3,)
        三角形的三个顶点坐标.
    eps : float
        面积阈值, 小于此值视为退化.

    Returns
    -------
    bool
        True 表示退化 (面积 < eps).
    """
    ab = b - a
    ac = c - a
    area_vec = np.cross(ab, ac)
    area = float(np.linalg.norm(area_vec))
    return area < eps


# ============================================================================
# 源点裁剪 (三角形区域内的 mesh 顶点提取)
# ============================================================================

def _clip_points_to_triangle(
    points: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    tolerance: float = PROJECTION_TOL,
) -> np.ndarray:
    """
    计算所有点相对于三角形 (A,B,C) 的重心坐标,
    筛选在三角形投影区域内的点.

    使用最小二乘法将 3D 点投影到三角形平面, 计算重心坐标 (λ_a, λ_b, λ_c).
    约束: λ_a + λ_b + λ_c = 1, 且每个 λ_i ∈ [-tolerance, 1 + tolerance].

    Parameters
    ----------
    points : np.ndarray, shape (N, 3)
        待投影的三维点集.
    a, b, c : np.ndarray, shape (3,)
        三角形顶点坐标.
    tolerance : float
        允许重心坐标超出 [0, 1] 的容差.

    Returns
    -------
    np.ndarray, shape (M, 3)
        在三角形容忍范围内的点的原始三维坐标.
    """
    if points.ndim == 2 and points.shape[0] == 0:
        return np.empty((0, 3), dtype=float)
    # 使用辅助函数求所有点的重心坐标
    lambdas = _barycentric_batch(points, a, b, c)
    # 筛选
    mask = (
        (lambdas[:, 0] >= -tolerance) & (lambdas[:, 0] <= 1 + tolerance)
        & (lambdas[:, 1] >= -tolerance) & (lambdas[:, 1] <= 1 + tolerance)
        & (lambdas[:, 2] >= -tolerance) & (lambdas[:, 2] <= 1 + tolerance)
    )
    return points[mask]


# ============================================================================
# 重心坐标批量计算 (二维参数化核心)
# ============================================================================

def _barycentric_batch(
    points: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
) -> np.ndarray:
    """
    批量计算一组三维点在某三角形上的重心坐标 (λ_a, λ_b, λ_c).

    方法:
      1. 建立三角形局部坐标系 (局部原点 = A)
      2. 最小二乘法将每个 3D 点投影到三角形平面
      3. 由投影点在局部坐标系中的 (u, v) 坐标反算 λ

    Parameters
    ----------
    points : np.ndarray, shape (N, 3)
        待投影的三维点集.
    a, b, c : np.ndarray, shape (3,)
        三角形顶点坐标.

    Returns
    -------
    np.ndarray, shape (N, 3)
        每行是 [λ_a, λ_b, λ_c], 满足 λ_a + λ_b + λ_c = 1.
    """
    # 局部基向量
    u_vec = b - a
    v_vec = c - a

    # 建立 2x2 线性系统: G * [u_coord, v_coord]^T = rhs
    G = np.array([
        [np.dot(u_vec, u_vec), np.dot(u_vec, v_vec)],
        [np.dot(u_vec, v_vec), np.dot(v_vec, v_vec)],
    ], dtype=float)

    det = G[0, 0] * G[1, 1] - G[0, 1] * G[1, 0]
    if abs(det) < 1e-12:
        # 退化三角形 -> 所有点投影到三角形质心
        return np.full((points.shape[0], 3), [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0])

    G_inv = np.linalg.inv(G)

    # 相对位移
    delta = points - a  # (N, 3)
    rhs = np.column_stack([
        np.dot(delta, u_vec),
        np.dot(delta, v_vec),
    ])  # (N, 2)

    uv = rhs @ G_inv.T  # (N, 2): [u_coord, v_coord]

    lambda_b = uv[:, 0]
    lambda_c = uv[:, 1]
    lambda_a = 1.0 - lambda_b - lambda_c

    result = np.column_stack([lambda_a, lambda_b, lambda_c])
    return result


def barycentric_3d(
    point: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
) -> np.ndarray:
    """
    计算单个三维点在三角形上的重心坐标.

    对外公开接口, 内部调用 _barycentric_batch.

    Parameters
    ----------
    point : np.ndarray, shape (3,)
        待投影点坐标.
    a, b, c : np.ndarray, shape (3,)
        三角形顶点坐标.

    Returns
    -------
    np.ndarray, shape (3,)
        重心坐标 [λ_a, λ_b, λ_c].
    """
    return _barycentric_batch(point.reshape(1, 3), a, b, c)[0]


# ============================================================================
# 固定分辨率重心坐标网格生成
# ============================================================================

def make_barycentric_grid(
    resolution: int,
) -> np.ndarray:
    """
    生成固定分辨率的重心坐标等间距网格.

    对于三角形参数域, 在 [0, 1] 区间等间距采样, 步长 = 1/resolution.
    总点数 = (resolution + 1) * (resolution + 2) / 2.

    数学原理:
      设 i, j 为整数, i + j <= resolution:
        λ_a = 1 - i/resolution - j/resolution
        λ_b = i/resolution
        λ_c = j/resolution

    当 resolution = 8 时, 共 (9*10)/2 = 45 个采样点.

    Parameters
    ----------
    resolution : int
        采样分辨率. 必须 >= 1.

    Returns
    -------
    np.ndarray, shape ((resolution+1)(resolution+2)/2, 3)
        重心坐标网格, 每行 [λ_a, λ_b, λ_c], 行优先排列 (j 变化快于 i).
    """
    if resolution < 1:
        raise ValueError(f"分辨率必须 >= 1, 收到: {resolution}")

    # 预分配内存
    n_points = (resolution + 1) * (resolution + 2) // 2
    grid = np.empty((n_points, 3), dtype=float)

    idx = 0
    inv_r = 1.0 / resolution
    for i in range(resolution + 1):
        max_j = resolution - i
        for j in range(max_j + 1):
            lambda_b = i * inv_r
            lambda_c = j * inv_r
            lambda_a = 1.0 - lambda_b - lambda_c
            grid[idx] = [lambda_a, lambda_b, lambda_c]
            idx += 1

    return grid


# ============================================================================
# 插值重建
# ============================================================================

def _interpolate_sample_points(
    source_points: np.ndarray,
    source_lambdas: np.ndarray,
    target_grid: np.ndarray,
    logger: logging.Logger,
) -> tuple[np.ndarray, np.ndarray]:
    """
    利用源点坐标和重心坐标, 插值重建目标网格在原始三维空间中的坐标.

    方法:
      1. 首选: LinearNDInterpolator (在重心坐标参数空间插值)
      2. 兜底: cKDTree 最近邻搜索 (针对线性插值失败的落点)

    Parameters
    ----------
    source_points : np.ndarray, shape (M, 3)
        三角形区域内的源点三维坐标 (x, y, z).
    source_lambdas : np.ndarray, shape (M, 3)
        源点对应的重心坐标 (λ_a, λ_b, λ_c).
    target_grid : np.ndarray, shape (K, 3)
        目标采样网格的重心坐标.
    logger : logging.Logger
        日志记录器.

    Returns
    -------
    reconstructed : np.ndarray, shape (K, 3)
        重建后的三维坐标 (x, y, z).
    fallback_mask : np.ndarray, shape (K,), dtype=bool
        哪些点使用了最近邻兜底.
    """
    n_target = target_grid.shape[0]

    # Step 1: LinearNDInterpolator 在 (λ_b, λ_c) 参数空间插值
    # 使用 λ_b, λ_c 作为参数 (λ_a 由约束确定, 冗余)
    interp = LinearNDInterpolator(
        source_lambdas[:, 1:3],   # (λ_b, λ_c) 参数坐标
        source_points,             # 三维空间坐标值
    )
    reconstructed = interp(target_grid[:, 1], target_grid[:, 2])

    fallback_mask = np.any(np.isnan(reconstructed), axis=1)
    n_nan = int(fallback_mask.sum())

    if n_nan > 0 and n_nan < n_target:
        # Step 2: cKDTree 兜底
        logger.debug(
            f"    LinearNDInterpolator 出现 {n_nan} 个 NaN 采样点, "
            f"使用 cKDTree 最近邻兜底."
        )
        tree = cKDTree(source_points)
        nan_indices = np.where(fallback_mask)[0]
        for idx in nan_indices:
            # 用目标网格点的重心坐标在参数空间中找最近的源点
            target_lambda = target_grid[idx, 1:]  # (λ_b, λ_c)
            dists = np.linalg.norm(source_lambdas[:, 1:] - target_lambda, axis=1)
            nearest = int(np.argmin(dists))
            reconstructed[idx] = source_points[nearest]
            fallback_mask[idx] = True
    elif n_nan == n_target:
        logger.debug(
            f"    LinearNDInterpolator 全部 {n_nan} 个点失败, "
            f"全部使用最近邻兜底."
        )
        tree = cKDTree(source_points)
        for idx in range(n_target):
            target_lambda = target_grid[idx, 1:]
            dists = np.linalg.norm(source_lambdas[:, 1:] - target_lambda, axis=1)
            nearest = int(np.argmin(dists))
            reconstructed[idx] = source_points[nearest]
            fallback_mask[idx] = True

    return reconstructed, fallback_mask


# ============================================================================
# 单区域处理
# ============================================================================

def process_region(
    sample_id: str,
    side: str,
    full_mesh: Any,            # trimesh.Trimesh
    lms: pd.DataFrame,
    region: dict[str, str],
    global_start_id: int,
    logger: logging.Logger,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    处理单个三角区域: 裁剪 → 投影 → 网格采样 → 插值重建 → QC.

    完整流程对应技术文档第 3 章全部步骤.

    Parameters
    ----------
    sample_id : str
        样本编号.
    side : str
        左右侧 'R' 或 'L'.
    full_mesh : trimesh.Trimesh
        完整耳 mesh.
    lms : pd.DataFrame
        特征点表 (以 landmark_id 为索引).
    region : dict
        区域定义, 包含以下键:
        - region_id:    区域编号 (如 'T001')
        - region_name:  区域名称 (如 '耳甲腔上区')
        - lm_a, lm_b, lm_c: 三角形三个顶点的 landmark ID
        - resolution:   采样分辨率 (int)
    global_start_id : int
        该区域输出点的全局起始 ID.
    logger : logging.Logger
        日志记录器.

    Returns
    -------
    df_region : pd.DataFrame
        该区域的参数化结果表, 包含所有采样点.
    qc_record : dict
        该区域的 QC 记录.
    region_detail : dict
        中间数据, 供可视化使用, 包含:
          - 'source_lambdas':  源点重心坐标 (M, 3)
          - 'source_points_3d': 裁剪后的源点三维坐标 (M, 3)
          - 'target_grid':     目标采样网格重心坐标 (K, 3)
          - 'reconstructed':   重建的三维坐标 (K, 3)
          - 'fallback_mask':   兜底标记 (K,)
          - 'region_name':     区域名称
    """
    logger.info(f"  [{sample_id}_{side}] 处理区域 {region['region_id']}: {region['region_name']}")

    # 1. 获取三角形顶点
    a = lms.loc[region["lm_a"], ["x", "y", "z"]].to_numpy(dtype=float)
    b = lms.loc[region["lm_b"], ["x", "y", "z"]].to_numpy(dtype=float)
    c = lms.loc[region["lm_c"], ["x", "y", "z"]].to_numpy(dtype=float)

    logger.debug(
        f"    三角形顶点: A({region['lm_a']})={a}, B({region['lm_b']})={b}, C({region['lm_c']})={c}"
    )

    # 2. 退化检测
    if _is_triangle_degenerate(a, b, c):
        raise ValueError(f"三角形退化 (三点共线): {region['lm_a']}-{region['lm_b']}-{region['lm_c']}")

    # 3. 裁剪: 提取三角形投影区域内的 mesh 顶点
    full_vertices = full_mesh.vertices

    # 对大量顶点采样以提高效率 (实际 mesh 顶点数过大时采样)
    n_verts = full_vertices.shape[0]
    if n_verts > DENSE_SAMPLE_COUNT:
        _indices = np.random.default_rng(42).choice(n_verts, DENSE_SAMPLE_COUNT, replace=False)
        sampled_vertices = full_vertices[_indices]
    else:
        sampled_vertices = full_vertices

    clipped = _clip_points_to_triangle(sampled_vertices, a, b, c, tolerance=PROJECTION_TOL)
    n_source = clipped.shape[0]

    logger.debug(f"    源点数: {n_source} (从 {n_verts} 个顶点中裁剪)")

    # 4. 计算源点重心坐标
    source_lambdas = _barycentric_batch(clipped, a, b, c)  # (M, 3)

    # 5. 生成目标采样网格
    resolution = int(region["resolution"])
    target_grid = make_barycentric_grid(resolution)  # (K, 3)
    n_target = target_grid.shape[0]

    logger.debug(f"    目标采样网格: resolution={resolution}, 点数={n_target}")

    # 6. 插值重建
    if n_source < MIN_SOURCE_POINTS:
        logger.warning(f"    源点不足 ({n_source} < {MIN_SOURCE_POINTS}), 全部使用三角形内部均匀插值")
        # 直接从三角形顶点线性插值
        reconstructed = np.column_stack([
            target_grid[:, 0] * a[0] + target_grid[:, 1] * b[0] + target_grid[:, 2] * c[0],
            target_grid[:, 0] * a[1] + target_grid[:, 1] * b[1] + target_grid[:, 2] * c[1],
            target_grid[:, 0] * a[2] + target_grid[:, 1] * b[2] + target_grid[:, 2] * c[2],
        ])
        fallback_mask = np.ones(n_target, dtype=bool)
    else:
        reconstructed, fallback_mask = _interpolate_sample_points(
            clipped, source_lambdas, target_grid, logger
        )

    n_fallback = int(fallback_mask.sum())
    fallback_ratio = n_fallback / n_target if n_target > 0 else 0.0

    # 7. QC 评估
    if fallback_ratio <= FALLBACK_WARNING_THRESHOLD:
        status = "PASS"
    elif fallback_ratio <= FALLBACK_FAIL_THRESHOLD:
        status = "WARNING"
    else:
        status = "FAIL"

    logger.info(
        f"    -> 源点={n_source}, 采样点={n_target}, "
        f"兜底={n_fallback}({fallback_ratio:.1%}), "
        f"状态={status}"
    )

    # 8. 二维展开: 计算 UV 坐标
    u_local, v_local, u_atlas, v_atlas = _to_atlas_uv(
        bary_grid=target_grid,
        region_id=region["region_id"],
    )

    logger.debug(
        f"    UV: local_u ∈ [{u_local.min():.3f}, {u_local.max():.3f}], "
        f"local_v ∈ [{v_local.min():.3f}, {v_local.max():.3f}], "
        f"atlas_u ∈ [{u_atlas.min():.3f}, {u_atlas.max():.3f}], "
        f"atlas_v ∈ [{v_atlas.min():.3f}, {v_atlas.max():.3f}]"
    )

    # 9. 组装输出 DataFrame
    point_ids_global = global_start_id + np.arange(n_target)
    point_ids_region = np.arange(n_target)

    df_region = pd.DataFrame({
        "sample_id": sample_id,
        "side": side,
        "region_id": region["region_id"],
        "region_name": region["region_name"],
        "point_id_global": point_ids_global,
        "point_id_region": point_ids_region,
        "x": reconstructed[:, 0],
        "y": reconstructed[:, 1],
        "z": reconstructed[:, 2],
        "u": u_atlas,          # 全局 atlas 坐标 (可视化用)
        "v": v_atlas,
        "u_local": u_local,    # 区域内归一化坐标 (统计分析用)
        "v_local": v_local,
        "lambda_a": target_grid[:, 0],
        "lambda_b": target_grid[:, 1],
        "lambda_c": target_grid[:, 2],
        "lm_a": region["lm_a"],
        "lm_b": region["lm_b"],
        "lm_c": region["lm_c"],
    })

    qc_record = {
        "region_id": str(region["region_id"]),
        "region_name": str(region["region_name"]),
        "used_patch_file": False,
        "source_point_count": n_source,
        "sample_point_count": n_target,
        "expected_point_count": n_target,
        "fallback_ratio": round(fallback_ratio, 4),
        "interpolator": "LinearNDInterpolator",
        "status": status,
    }

    # 10. 构造可视化中间数据
    # 注: target_grid_bc / sample_points_3d / a_3d 等键名供 visualization.py 使用
    region_detail = {
        "region_name": str(region["region_name"]),
        "a_3d": a,
        "b_3d": b,
        "c_3d": c,
        "lm_a": str(region["lm_a"]),
        "lm_b": str(region["lm_b"]),
        "lm_c": str(region["lm_c"]),
        "source_lambdas": source_lambdas,
        "source_points_3d": clipped,
        "target_grid": target_grid,
        "target_grid_bc": target_grid,
        "reconstructed": reconstructed,
        "sample_points_3d": reconstructed,
        "fallback_mask": fallback_mask,
    }

    return df_region, qc_record, region_detail
