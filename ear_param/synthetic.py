#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
synthetic.py — 模拟数据生成模块
================================

生成用于算法验证的模拟三组耳 mesh 和特征点 (landmarks).

数学基础:
  - 耳朵参数曲面: F(u, v) → (x, y, z),   (u, v) ∈ [0, 1]²
  - 解剖特征叠加:
     * 耳甲腔凹陷 (conchal depression)
     * 耳屏突起 (tragus protrusion)
     * 三角窝凹陷 (triangular fossa depression)
     * 耳垂 (lobule)
  - 特征点: 在参数空间中预定义 (u, v) 坐标, 通过曲面插值得到三维位置
  - 样本间变异: 随机噪声 + 随机种子控制

输出:
  - 原始 mesh: data/clean_mesh/S00X_R.ply
  - Landmarks:   data/landmarks/S00X_R_landmarks.csv

技术依据:
  《人头给你了-3D 耳模型跨模型参数化与特征值计算技术执行文档-v0.0》
    附录 A — 参数曲面与模拟数据详细说明
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import trimesh

from .config import (
    LANDMARK_IDS,
    SIMULATED_SAMPLES,
    SIMULATED_SEEDS,
    SIMULATED_NOISE_LEVELS,
    DEFAULT_EAR_WIDTH,
    DEFAULT_EAR_HEIGHT,
    DEFAULT_EAR_DEPTH,
    DEFAULT_EAR_NOISE_SCALE,
)


# ============================================================================
# 参数曲面定义
# ============================================================================

def _parametric_ear_surface(
    uv: np.ndarray,
    seed: int = 42,
    noise_scale: float = DEFAULT_EAR_NOISE_SCALE,
) -> np.ndarray:
    """
    耳朵参数曲面: 将 (u, v) 映射到三维坐标 (x, y, z).

    包含以下解剖结构:
    - 基础形状: 椭圆近似
    - 耳甲腔凹陷: 中央凹陷区域
    - 耳屏突起: 前部小突起
    - 三角窝凹陷: 上部凹陷
    - 耳垂: 下部圆润突起

    Parameters
    ----------
    uv : np.ndarray, shape (N, 2)
        参数坐标, 每行 [u, v], u ∈ [0, 1], v ∈ [0, 1].
    seed : int
        随机种子, 控制参数曲面的细微变化, 不同 seed 产生不同耳形.
    noise_scale : float
        噪声幅度 (mm).

    Returns
    -------
    np.ndarray, shape (N, 3)
        三维坐标点集.
    """
    rng = np.random.default_rng(seed)
    u = uv[:, 0]
    v = uv[:, 1]

    w = DEFAULT_EAR_WIDTH
    h = DEFAULT_EAR_HEIGHT
    d = DEFAULT_EAR_DEPTH

    # --- 基础形状 (椭圆近似) ---
    # 耳朵在 xy 平面上呈椭圆, z 方向控制深度
    x = (u - 0.5) * w
    y = (v - 0.35) * h        # 中心偏下
    z_base = (
        0.1 * w * np.sin(2 * np.pi * u) * np.sin(np.pi * v)
        + d * (1 - np.abs(u - 0.5) * 2)
    )

    # --- 耳甲腔凹陷 (中央区域) ---
    # 位置: u ∈ [0.3, 0.7], v ∈ [0.4, 0.7]
    conchal_mask = (u > 0.3) & (u < 0.7) & (v > 0.4) & (v < 0.7)
    conchal_depth = np.where(
        conchal_mask,
        -d * 0.8 * np.exp(
            -((u - 0.5) ** 2) / 0.02 - ((v - 0.55) ** 2) / 0.03
        ),
        0.0,
    )

    # --- 耳屏突起 (trau̯, 前部小突起) ---
    # 位置: u ∈ [0.15, 0.35], v ∈ [0.5, 0.7]
    tragal_mask = (u > 0.15) & (u < 0.35) & (v > 0.5) & (v < 0.7)
    tragal_bump = np.where(
        tragal_mask,
        d * 0.6 * np.exp(
            -((u - 0.25) ** 2) / 0.005 - ((v - 0.6) ** 2) / 0.01
        ),
        0.0,
    )

    # --- 三角窝凹陷 (上部) ---
    # 位置: u ∈ [0.3, 0.65], v ∈ [0.7, 0.9]
    fossa_mask = (u > 0.3) & (u < 0.65) & (v > 0.7) & (v < 0.9)
    fossa_depression = np.where(
        fossa_mask,
        -d * 0.5 * np.exp(
            -((u - 0.45) ** 2) / 0.03 - ((v - 0.8) ** 2) / 0.01
        ),
        0.0,
    )

    # --- 耳垂 (下部圆润突起) ---
    # 位置: v < 0.15
    lobule_mask = v < 0.15
    lobule_bump = np.where(
        lobule_mask,
        d * 0.4 * np.exp(-(v ** 2) / 0.01),
        0.0,
    )

    # --- 随机噪声 (样本间个体差异) ---
    noise_x = noise_scale * rng.normal(0, 1, size=len(u))
    noise_y = noise_scale * rng.normal(0, 1, size=len(u))
    noise_z = noise_scale * rng.normal(0, 1, size=len(u))

    # --- 合成 ---
    z = z_base + conchal_depth + tragal_bump + fossa_depression + lobule_bump
    z += noise_z

    x += noise_x
    y += noise_y

    return np.column_stack([x, y, z])


# ============================================================================
# Ear Mesh 生成
# ============================================================================

def generate_ear_mesh(
    seed: int = 42,
    noise_scale: float = DEFAULT_EAR_NOISE_SCALE,
    grid_size: int = 80,
) -> trimesh.Trimesh:
    """
    生成一副完整的模拟耳 mesh.

    在 (u, v) 参数空间均匀采样, 通过 _parametric_ear_surface 映射到三维,
    再用 Delaunay 三角剖分构建 mesh.

    Parameters
    ----------
    seed : int
        随机种子.
    noise_scale : float
        噪声幅度 (mm).
    grid_size : int
        (u, v) 参数空间的网格分辨率.

    Returns
    -------
    trimesh.Trimesh
        模拟耳 mesh.
    """
    rng = np.random.default_rng(seed)

    # 在参数空间均匀采样
    u_vals = np.linspace(0, 1, grid_size)
    v_vals = np.linspace(0, 1, grid_size)
    U, V = np.meshgrid(u_vals, v_vals)
    uv_points = np.column_stack([U.ravel(), V.ravel()])

    # 映射到三维
    vertices = _parametric_ear_surface(uv_points, seed=seed, noise_scale=noise_scale)

    # 用 Delaunay 三角剖分在 uv 空间生成 faces
    from scipy.spatial import Delaunay
    tri_uv = Delaunay(uv_points)
    faces = tri_uv.simplices

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)

    return mesh


# ============================================================================
# 特征点模拟
# ============================================================================

# 在参数空间 (u, v) 中预定义 13 个特征点位置
_LANDMARK_UV_POSITIONS: dict[str, tuple[float, float]] = {
    # landmark_id: (u, v) in [0, 1]²
    "L02": (0.48, 0.02),    # 耳垂最低点
    "L07": (0.90, 0.62),    # 耳根上后点
    "L10": (0.30, 0.30),    # 耳甲腔中心
    "L13": (0.08, 0.75),    # 耳轮前上点
    "L15": (0.95, 0.50),    # 耳根后点
    "L19": (0.10, 0.95),    # 耳屏前上点
    "L20": (0.85, 0.95),    # 对耳屏点
    "L21": (0.40, 0.95),    # 耳屏间切迹
    "L26": (0.50, 0.98),    # 耳垂最前点
    "L28": (0.40, 0.60),    # 耳道入口上点
    "L29": (0.40, 0.75),    # 耳道入口中点
    "L30": (0.40, 0.55),    # 耳道入口下点
    "L31": (0.60, 0.25),    # 耳甲腔后下点
}


def generate_landmarks(
    seed: int = 42,
    noise_scale: float = DEFAULT_EAR_NOISE_SCALE,
) -> pd.DataFrame:
    """
    生成模拟特征点.

    在参数空间中预定义 (u, v) 位置 → 通过曲面函数映射到三维.
    每个样本通过 seed 产生个体差异.

    Parameters
    ----------
    seed : int
        随机种子.
    noise_scale : float
        噪声幅度 (mm).

    Returns
    -------
    pd.DataFrame
        特征点表, 以 landmark_id 为索引, 包含 x, y, z 列.
    """
    rng = np.random.default_rng(seed + 1)  # +1 区别于 mesh 的噪声种子

    records = []
    for lm_id in LANDMARK_IDS:
        u, v = _LANDMARK_UV_POSITIONS[lm_id]
        uv_arr = np.array([[u, v]])
        xyz = _parametric_ear_surface(uv_arr, seed=seed, noise_scale=noise_scale * 0.5)
        # 再加一点 landmarks 特有的标注误差
        xyz += noise_scale * 0.3 * rng.normal(0, 1, size=3)
        records.append({
            "landmark_id": lm_id,
            "x": round(float(xyz[0, 0]), 4),
            "y": round(float(xyz[0, 1]), 4),
            "z": round(float(xyz[0, 2]), 4),
            "confidence": 1.0,
            "annotator": "simulated",
            "comment": "",
        })

    df = pd.DataFrame(records)
    df = df.set_index("landmark_id")
    return df


# ============================================================================
# 批量生成
# ============================================================================

def generate_all_simulated_data(
    clean_mesh_dir: Path,
    landmarks_dir: Path,
    logger: logging.Logger,
) -> None:
    """
    批量生成所有模拟样本的 mesh 和 landmarks.

    为 config.SIMULATED_SAMPLES 中的每个样本生成:
      - {sample_id}_R.ply  (mesh)
      - {sample_id}_R_landmarks.csv  (特征点)

    Parameters
    ----------
    clean_mesh_dir : Path
        Mesh 输出目录.
    landmarks_dir : Path
        特征点输出目录.
    logger : logging.Logger
        日志记录器.
    """
    clean_mesh_dir.mkdir(parents=True, exist_ok=True)
    landmarks_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("生成模拟数据")
    logger.info("=" * 60)

    for idx, sample_id in enumerate(SIMULATED_SAMPLES):
        seed = SIMULATED_SEEDS[idx]
        noise = SIMULATED_NOISE_LEVELS[idx]
        logger.info(f"\n--- {sample_id}: seed={seed}, noise={noise} ---")

        # 生成 mesh
        mesh = generate_ear_mesh(seed=seed, noise_scale=noise)
        mesh_path = clean_mesh_dir / f"{sample_id}_R.ply"
        mesh.export(str(mesh_path))
        logger.info(f"  Mesh: {mesh_path} ({mesh.vertices.shape[0]} 顶点, {len(mesh.faces)} 面)")

        # 生成 landmarks
        lms_df = generate_landmarks(seed=seed, noise_scale=noise)

        # 保存 landmarks (转换为原始格式: landmark_id 作为列, 不是索引)
        lms_out = lms_df.reset_index()
        lms_path = landmarks_dir / f"{sample_id}_R_landmarks.csv"
        lms_out.to_csv(str(lms_path), index=False)
        logger.info(f"  Landmarks: {lms_path} ({len(lms_df)} 个特征点)")

    logger.info("\n模拟数据生成完成.\n")