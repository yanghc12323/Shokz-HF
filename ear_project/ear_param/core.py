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
5. 插值重建采样点三维坐标 (面片感知的 point-in-triangle 插值)
6. 单区域处理 (编排以上各步骤)
7. QC 评估

技术依据: 《人头给你了-3D 耳模型跨模型参数化与特征值计算技术执行文档-v0.0》
    第 3 章 — 三维三角区域投影至二维平面, 降采样

v2.0 升级说明 (2026-07-06):
  - 步骤 5 插值方式从 LinearNDInterpolator 升级为面片感知的 point-in-triangle 插值:
    * 利用原始 mesh 三角面片在 (λb, λc) 参数空间的投影三角形,
      对每个目标网格点做包含性测试, 在找到的面片内用重心坐标直接插值 3D 位置。
    * 兜底策略改为参数域最近邻 (非 3D 最近邻), 避免跨解剖结构匹配。
  - 好处: 保留了原始 mesh 的拓扑结构, 消除了重建 Delaunay 导致的拓扑失真问题。

坐标约定:
  - 源点坐标系: 原始 mesh 顶点三维坐标 (x, y, z)
  - 参数坐标系: 三角形平面上的重心坐标 (lambda_a, lambda_b, lambda_c)
  - 约束: lambda_a + lambda_b + lambda_c = 1, 每个 lambda ∈ [0, 1]
"""

import logging
from typing import Any

import numpy as np
import pandas as pd

from .config import (
    PROJECTION_TOL,
    FALLBACK_WARNING_THRESHOLD,
    FALLBACK_FAIL_THRESHOLD,
    MIN_SOURCE_POINTS,
    DENSE_SAMPLE_COUNT,
)


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
) -> tuple[np.ndarray, np.ndarray]:
    """
    计算所有点相对于三角形 (A,B,C) 的重心坐标,
    筛选在三角形投影区域内的点, 同时返回筛选掩码供面片构建使用.

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
    clipped_points : np.ndarray, shape (M, 3)
        在三角形容忍范围内的点的原始三维坐标.
    mask : np.ndarray, shape (N,), dtype=bool
        筛选掩码, True 表示该点在容忍范围内.
    """
    if points.ndim == 2 and points.shape[0] == 0:
        return np.empty((0, 3), dtype=float), np.zeros(0, dtype=bool)
    # 使用辅助函数求所有点的重心坐标
    lambdas = _barycentric_batch(points, a, b, c)
    # 筛选
    mask = (
        (lambdas[:, 0] >= -tolerance) & (lambdas[:, 0] <= 1 + tolerance)
        & (lambdas[:, 1] >= -tolerance) & (lambdas[:, 1] <= 1 + tolerance)
        & (lambdas[:, 2] >= -tolerance) & (lambdas[:, 2] <= 1 + tolerance)
    )
    return points[mask], mask


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
# 2D 三角形的点包含测试
# ============================================================================

def _point_in_triangle_2d(
    point: np.ndarray,
    triangle: np.ndarray,
    eps: float = -1e-12,
) -> np.ndarray | None:
    """
    测试一个二维点是否在二维三角形内部, 若在内部则返回重心坐标.

    使用标准重心坐标法: 解线性方程组求 (α, β, γ), 满足:
      α + β + γ = 1
      α·v0 + β·v1 + γ·v2 = point
    其中 v0, v1, v2 是三角形的三个顶点 (均为二维向量).

    Parameters
    ----------
    point : np.ndarray, shape (2,)
        待测试点坐标.
    triangle : np.ndarray, shape (3, 2)
        三角形的三个顶点 (按行排列).
    eps : float
        数值容差, 默认 -1e-12 允许极其微小的越界 (浮点舍入).

    Returns
    -------
    np.ndarray | None
        若点在三角形内, 返回 (α, β, γ) 重心坐标; 否则返回 None.
    """
    v0 = triangle[2] - triangle[0]  # C - A
    v1 = triangle[1] - triangle[0]  # B - A
    v2 = point - triangle[0]        # P - A

    d00 = float(np.dot(v0, v0))
    d01 = float(np.dot(v0, v1))
    d11 = float(np.dot(v1, v1))
    d20 = float(np.dot(v2, v0))
    d21 = float(np.dot(v2, v1))

    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-15:
        return None  # 退化三角形 (三点共线)

    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    u = 1.0 - v - w

    # 允许微小的负值 (浮点舍入误差)
    if u >= eps and v >= eps and w >= eps:
        return np.array([u, v, w], dtype=float)
    return None


# ============================================================================
# 源面片构建 (从裁剪顶点重建原始 mesh 拓扑)
# ============================================================================

def _build_source_faces(
    sampled_vertices: np.ndarray,
    sampled_lambdas: np.ndarray,
    clip_mask: np.ndarray,
    global_indices: np.ndarray,
    full_faces: np.ndarray,
    logger: logging.Logger,
) -> tuple[np.ndarray, np.ndarray]:
    """
    从裁剪后的顶点集合中, 重建原始 mesh 中包含的面片信息.

    遍历原始 mesh 的所有三角面片, 若面片的三个顶点均被裁剪保留
    (即投影重心坐标都在容忍范围内), 则将该面片纳入"源面片"集合.

    每个源面片存储两组信息:
    - 面片的三个顶点在三维空间中的坐标 (用于 3D 插值)
    - 面片的三个顶点在 (λb, λc) 参数空间中的坐标 (用于 2D 包含性测试)

    Parameters
    ----------
    sampled_vertices : np.ndarray, shape (N_sample, 3)
        参与裁剪计算的采样顶点 3D 坐标.
    sampled_lambdas : np.ndarray, shape (N_sample, 3)
        采样顶点对应的重心坐标 (λ_a, λ_b, λ_c).
    clip_mask : np.ndarray, shape (N_sample,), dtype=bool
        裁剪掩码, True 表示该采样顶点在三角形容忍范围内.
    global_indices : np.ndarray, shape (N_sample,), dtype=int
        采样顶点在 full_mesh.vertices 中的原始索引.
    full_faces : np.ndarray, shape (F, 3), dtype=int
        原始 mesh 的全部面片 (顶点索引).
    logger : logging.Logger
        日志记录器.

    Returns
    -------
    face_triangles_3d : np.ndarray, shape (N_faces, 3, 3)
        每个源面片的三个顶点在三维空间中的坐标.
    face_triangles_2d : np.ndarray, shape (N_faces, 3, 2)
        每个源面片的三个顶点在 (λb, λc) 参数空间中的坐标.
    """
    # 建立全局顶点索引 → 采样顶点的裁剪后局部索引的映射
    # 只有 clip_mask=True 的顶点才出现在映射中
    clipped_local_indices = np.where(clip_mask)[0]
    global_to_clipped_local: dict[int, int] = {}
    for local_idx in clipped_local_indices:
        g_idx = int(global_indices[local_idx])
        global_to_clipped_local[g_idx] = local_idx

    if len(global_to_clipped_local) == 0:
        logger.debug("    源面片构建: 无裁剪顶点, 返回空面片列表")
        empty_3d = np.empty((0, 3, 3), dtype=float)
        empty_2d = np.empty((0, 3, 2), dtype=float)
        return empty_3d, empty_2d

    face_triangles_3d_list: list[np.ndarray] = []
    face_triangles_2d_list: list[np.ndarray] = []

    for face in full_faces:
        v0, v1, v2 = int(face[0]), int(face[1]), int(face[2])
        # 三个顶点都必须被裁剪保留
        if (v0 in global_to_clipped_local
                and v1 in global_to_clipped_local
                and v2 in global_to_clipped_local):
            li0 = global_to_clipped_local[v0]
            li1 = global_to_clipped_local[v1]
            li2 = global_to_clipped_local[v2]

            # 三维坐标
            tri_3d = np.array([
                sampled_vertices[li0],
                sampled_vertices[li1],
                sampled_vertices[li2],
            ], dtype=float)
            # (λb, λc) 参数坐标
            tri_2d = np.array([
                sampled_lambdas[li0, 1:3],
                sampled_lambdas[li1, 1:3],
                sampled_lambdas[li2, 1:3],
            ], dtype=float)

            face_triangles_3d_list.append(tri_3d)
            face_triangles_2d_list.append(tri_2d)

    n_faces = len(face_triangles_3d_list)
    if n_faces == 0:
        logger.warning(
            "    源面片构建: 原始 mesh 中没有完整的面片落在三角形区域内。"
            "插值将全部使用参数域最近邻兜底。"
        )
        empty_3d = np.empty((0, 3, 3), dtype=float)
        empty_2d = np.empty((0, 3, 2), dtype=float)
        return empty_3d, empty_2d

    logger.debug(
        f"    源面片构建: 从 {len(full_faces)} 个 mesh 面片中 "
        f"提取了 {n_faces} 个完整落在区域内的面片"
    )

    return np.array(face_triangles_3d_list), np.array(face_triangles_2d_list)


# ============================================================================
# 插值重建 (v2.0 — 面片感知的 point-in-triangle 插值)
# ============================================================================

def _interpolate_sample_points(
    source_points: np.ndarray,
    source_lambdas: np.ndarray,
    source_faces_3d: np.ndarray,
    source_faces_2d: np.ndarray,
    target_grid: np.ndarray,
    logger: logging.Logger,
) -> tuple[np.ndarray, np.ndarray]:
    """
    利用源点及原始 mesh 面片拓扑, 插值重建目标网格在三维空间中的坐标.

    v2.0 升级: 不再使用 LinearNDInterpolator, 改为面片感知的插值策略:
      1. 首选: 在原始 mesh 面片投影到 (λb, λc) 空间形成的三角形中,
         做 point-in-triangle 包含性测试。若目标点落在某个面片内,
         用该面片三个顶点的 3D 坐标做重心坐标线性插值。
         → 完整保留了原始 mesh 的拓扑结构, 不会跨结构映射。
      2. 兜底: 若目标点未落入任何源面片 (如三角形边缘区域面片覆盖不足),
         在参数空间 (λb, λc) 中找最近源点, 使用其 3D 坐标。
         → 兜底使用参数空间距离, 不会跳到 3D 最近邻 (避免跨解剖结构)。

    Parameters
    ----------
    source_points : np.ndarray, shape (M, 3)
        三角形区域内的源点三维坐标 (x, y, z).
    source_lambdas : np.ndarray, shape (M, 3)
        源点对应的重心坐标 (λ_a, λ_b, λ_c).
    source_faces_3d : np.ndarray, shape (F, 3, 3)
        源面片的三个顶点在三维空间中的坐标.
    source_faces_2d : np.ndarray, shape (F, 3, 2)
        源面片的三个顶点在 (λb, λc) 参数空间中的坐标.
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
    n_faces = source_faces_2d.shape[0]
    target_2d = target_grid[:, 1:3]  # (K, 2) — (λb, λc) 参数坐标

    reconstructed = np.full((n_target, 3), np.nan, dtype=float)
    fallback_mask = np.zeros(n_target, dtype=bool)

    # 若没有源面片, 全部使用参数域最近邻兜底
    if n_faces == 0:
        logger.warning("    无可用源面片, 全部使用参数域最近邻兜底")
        fallback_mask[:] = True
        for t in range(n_target):
            pt_2d = target_2d[t]
            dists = np.linalg.norm(source_lambdas[:, 1:3] - pt_2d, axis=1)
            nearest = int(np.argmin(dists))
            reconstructed[t] = source_points[nearest]
        return reconstructed, fallback_mask

    # 预计算每个源面片的包围盒 (用于快速剔除)
    face_bbox_min = source_faces_2d.min(axis=1)  # (F, 2)
    face_bbox_max = source_faces_2d.max(axis=1)  # (F, 2)

    n_fallback = 0
    for t in range(n_target):
        pt_2d = target_2d[t]  # (2,)
        found = False

        # 遍历所有源面片 (TODO: 当面片数较大时, 可使用空间索引加速)
        for f in range(n_faces):
            # 快速包围盒剔除
            if (pt_2d[0] < face_bbox_min[f, 0] or pt_2d[0] > face_bbox_max[f, 0]
                    or pt_2d[1] < face_bbox_min[f, 1] or pt_2d[1] > face_bbox_max[f, 1]):
                continue

            # 精确 point-in-triangle 测试
            bc = _point_in_triangle_2d(pt_2d, source_faces_2d[f])
            if bc is not None:
                # bc = (α, β, γ) — 面片内三个顶点的插值权重
                tri_3d = source_faces_3d[f]
                reconstructed[t] = (
                    bc[0] * tri_3d[0]
                    + bc[1] * tri_3d[1]
                    + bc[2] * tri_3d[2]
                )
                found = True
                break

        if not found:
            fallback_mask[t] = True
            n_fallback += 1

    # 兜底: 参数空间最近邻
    if n_fallback > 0:
        logger.debug(
            f"    point-in-triangle: {n_target - n_fallback}/{n_target} 成功, "
            f"{n_fallback} 个点使用参数域最近邻兜底"
        )
        fallback_indices = np.where(fallback_mask)[0]
        for idx in fallback_indices:
            pt_2d = target_2d[idx]
            # 在参数空间 (λb, λc) 中找最近源点, 而非 3D 最近邻
            dists = np.linalg.norm(source_lambdas[:, 1:3] - pt_2d, axis=1)
            nearest = int(np.argmin(dists))
            reconstructed[idx] = source_points[nearest]

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
    处理单个三角区域: 裁剪 → 投影 → 面片构建 → 网格采样 → 插值重建 → QC.

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

    # 3. 顶点采样与裁剪: 提取三角形投影区域内的 mesh 顶点
    full_vertices = full_mesh.vertices
    full_faces = full_mesh.faces
    n_verts = full_vertices.shape[0]

    # 对大量顶点采样以提高效率
    if n_verts > DENSE_SAMPLE_COUNT:
        rng = np.random.default_rng(42)
        global_indices = rng.choice(n_verts, DENSE_SAMPLE_COUNT, replace=False)
        sampled_vertices = full_vertices[global_indices]
    else:
        global_indices = np.arange(n_verts, dtype=int)
        sampled_vertices = full_vertices

    # 计算所有采样顶点的重心坐标 & 裁剪
    sampled_lambdas = _barycentric_batch(sampled_vertices, a, b, c)
    clipped, clip_mask = _clip_points_to_triangle(
        sampled_vertices, a, b, c, tolerance=PROJECTION_TOL
    )
    # clipped 已经是被裁剪后的顶点, clip_mask 标记采样顶点中哪些被保留
    n_source = clipped.shape[0]

    logger.debug(f"    源点数: {n_source} (从 {n_verts} 个顶点中裁剪)")

    # 获取被裁剪保留的源点的重心坐标 (仅保留 clip_mask=True 的行)
    source_lambdas = sampled_lambdas[clip_mask]  # (M, 3)

    # 4. 构建源面片: 从原始 mesh 拓扑中提取完整落在区域内的面片
    source_faces_3d, source_faces_2d = _build_source_faces(
        sampled_vertices=sampled_vertices,
        sampled_lambdas=sampled_lambdas,
        clip_mask=clip_mask,
        global_indices=global_indices,
        full_faces=full_faces,
        logger=logger,
    )
    n_source_faces = source_faces_3d.shape[0]
    logger.debug(f"    源面片数: {n_source_faces}")

    # 5. 生成目标采样网格
    resolution = int(region["resolution"])
    target_grid = make_barycentric_grid(resolution)  # (K, 3)
    n_target = target_grid.shape[0]

    logger.debug(f"    目标采样网格: resolution={resolution}, 点数={n_target}")

    # 6. 插值重建
    if n_source < MIN_SOURCE_POINTS:
        logger.warning(f"    源点不足 ({n_source} < {MIN_SOURCE_POINTS}), 全部使用三角形内部均匀插值")
        # 直接从三角形顶点线性插值 (退化方案)
        reconstructed = np.column_stack([
            target_grid[:, 0] * a[0] + target_grid[:, 1] * b[0] + target_grid[:, 2] * c[0],
            target_grid[:, 0] * a[1] + target_grid[:, 1] * b[1] + target_grid[:, 2] * c[1],
            target_grid[:, 0] * a[2] + target_grid[:, 1] * b[2] + target_grid[:, 2] * c[2],
        ])
        fallback_mask = np.ones(n_target, dtype=bool)
        interpolator_name = "LinearVertex (源点不足)"
    else:
        reconstructed, fallback_mask = _interpolate_sample_points(
            source_points=clipped,
            source_lambdas=source_lambdas,
            source_faces_3d=source_faces_3d,
            source_faces_2d=source_faces_2d,
            target_grid=target_grid,
            logger=logger,
        )
        interpolator_name = "PointInTriangle (面片感知)"

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
        f"    -> 源点={n_source}, 源面片={n_source_faces}, 采样点={n_target}, "
        f"兜底={n_fallback}({fallback_ratio:.1%}), "
        f"状态={status}"
    )

    # 8. 组装输出 DataFrame
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
        "u": np.nan,          # 等实现二维展开后再填充
        "v": np.nan,
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
        "source_face_count": n_source_faces,
        "sample_point_count": n_target,
        "expected_point_count": n_target,
        "fallback_ratio": round(fallback_ratio, 4),
        "interpolator": interpolator_name,
        "status": status,
    }

    return df_region, qc_record