#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parameterize_ear.py
===================
3D耳模型跨模型参数化 —— 三角区域投影 + 统一重采样

功能概述:
  1. 生成模拟耳 mesh 数据 (3个样本, .ply格式)
  2. 生成模拟特征点 (landmarks, .csv格式)
  3. 读取 region_table.csv 区域定义
  4. 对每个样本的每个区域:
     - 提取 A/B/C 三个特征点
     - 从 mesh 中筛选该区域源点 (重心坐标 + 容差 mask)
     - 源点投影至二维参数平面 (重心坐标的 lambda_B, lambda_C 作为 u,v)
     - 在标准三角形上生成固定采样点 (make_barycentric_grid)
     - 使用 LinearNDInterpolator 插值回三维
     - 兜底: cKDTree 最近邻
  5. 输出统一点云 CSV + QC 报告 CSV
  6. 日志同时输出到控制台和文件

技术依据: 论文 Chapter 5, 文档 人头给你了-3D 耳模型跨模型参数化与特征值计算技术执行文档-v0.0

依赖: numpy, pandas, scipy, trimesh
运行: python scripts/parameterize_ear.py
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import trimesh
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import cKDTree


# ============================================================================
# 0. 全局配置与常量
# ============================================================================

# 特征点定义: 论文 31 个特征点中本项目使用的子集
# (x, y, z) 将在模拟数据生成时动态填充
LANDMARK_IDS = [
    "L02", "L07", "L10", "L13", "L15",
    "L19", "L20", "L21", "L26", "L28",
    "L29", "L30", "L31",
]

# 模拟样本列表
SIMULATED_SAMPLES = ["S001", "S002", "S003"]
SIMULATED_SIDE = "R"  # 统一用右耳

# 投影容差: 重心坐标允许超出 [0,1] 的容差范围
PROJECTION_TOL = 0.15

# 插值兜底阈值
FALLBACK_WARNING_THRESHOLD = 0.05   # 5%
FALLBACK_FAIL_THRESHOLD = 0.20      # 20%

# 源点最小数量
MIN_SOURCE_POINTS = 5  # 极小区域（如耳道入口区）可能源点较少

# 网格面采样密度 (从 patch/full mesh 采样源点时用)
DENSE_SAMPLE_COUNT = 5000


# ============================================================================
# 1. 日志配置
# ============================================================================

def setup_logging(sample_id: str, side: str, log_dir: Path) -> logging.Logger:
    """
    配置日志: 同时输出到控制台和文件.

    Parameters
    ----------
    sample_id : str
        样本编号, 如 'S001'.
    side : str
        左右侧, 'R' 或 'L'.
    log_dir : Path
        日志输出目录.

    Returns
    -------
    logging.Logger
        配置好的 logger 实例.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{sample_id}_{side}_parameterize_{timestamp}.log"

    logger = logging.getLogger(f"parameterize_{sample_id}_{side}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()  # 防止重复添加

    # 格式
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件 handler (DEBUG)
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 控制台 handler (INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    logger.info("=" * 60)
    logger.info(f"参数化开始: sample_id={sample_id}, side={side}")
    logger.info(f"日志文件: {log_file}")
    logger.info("=" * 60)

    return logger


# ============================================================================
# 2. 模拟数据生成
# ============================================================================

def generate_ear_surface(
    seed: int = 42,
    n_u: int = 60,
    n_v: int = 50,
    ear_width: float = 35.0,
    ear_height: float = 60.0,
    ear_depth: float = 15.0,
    noise_scale: float = 0.3,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """
    生成类耳朵曲面参数化 mesh.

    使用参数曲面:
      x(u,v) = ear_width  * (u - 0.5) * f(v)
      y(u,v) = ear_height * (v - 0.35)
      z(u,v) = ear_depth  * g(u,v)  -- 模拟耳甲腔凹陷和耳屏突起

    其中 f(v) 控制耳宽沿高度变化, g(u,v) 控制深度变化.

    Parameters
    ----------
    seed : int
        随机种子, 不同样本使用不同种子以保证个体差异.
    n_u : int
        u 方向采样点数 (左右方向).
    n_v : int
        v 方向采样点数 (上下方向).
    ear_width : float
        耳宽 (mm).
    ear_height : float
        耳高 (mm).
    ear_depth : float
        耳深 (mm).
    noise_scale : float
        个体差异噪声标准差 (mm).

    Returns
    -------
    vertices : np.ndarray, shape (N, 3)
        网格顶点坐标.
    faces : np.ndarray, shape (M, 3)
        三角面片索引.
    uv_grid : np.ndarray, shape (n_u, n_v, 2)
        (u, v) 参数网格, 用于定位特征点.
    landmark_coords : dict
        {landmark_id: (x, y, z)} 特征点坐标字典.
    """
    rng = np.random.default_rng(seed)

    u_vals = np.linspace(0.0, 1.0, n_u)
    v_vals = np.linspace(0.0, 1.0, n_v)
    U, V = np.meshgrid(u_vals, v_vals, indexing="ij")  # (n_u, n_v)

    # f(v): 耳宽沿高度变化 -- 中部略宽, 上下稍窄
    f_v = 1.0 - 0.15 * np.sin(np.pi * V) - 0.05 * np.cos(2 * np.pi * V)

    # g(u,v): 深度变化 -- 模拟耳甲腔凹陷
    #   在耳中部 (u≈0.4, v≈0.45) 有最深凹陷
    u_center, v_center = 0.40, 0.45
    sigma_u, sigma_v = 0.18, 0.15
    gaussian_dep = np.exp(
        -((U - u_center) ** 2) / (2 * sigma_u**2)
        - ((V - v_center) ** 2) / (2 * sigma_v**2)
    )
    depth_mod = 1.0 - 0.7 * gaussian_dep  # 凹陷: 减少 z

    # 耳屏区域小突起 (u≈0.25, v≈0.55)
    u_tragus, v_tragus = 0.22, 0.55
    sigma_tu, sigma_tv = 0.06, 0.08
    tragus_bump = np.exp(
        -((U - u_tragus) ** 2) / (2 * sigma_tu**2)
        - ((V - v_tragus) ** 2) / (2 * sigma_tv**2)
    )
    depth_mod = depth_mod + 0.25 * tragus_bump  # 突起

    # 对耳屏区域小突起 (u≈0.60, v≈0.53)
    u_anti, v_anti = 0.62, 0.53
    sigma_au, sigma_av = 0.07, 0.09
    anti_bump = np.exp(
        -((U - u_anti) ** 2) / (2 * sigma_au**2)
        - ((V - v_anti) ** 2) / (2 * sigma_av**2)
    )
    depth_mod = depth_mod + 0.20 * anti_bump

    # 三角窝区域凹陷 (u≈0.55, v≈0.30)
    u_fossa, v_fossa = 0.55, 0.28
    sigma_fu, sigma_fv = 0.10, 0.08
    fossa_dep = np.exp(
        -((U - u_fossa) ** 2) / (2 * sigma_fu**2)
        - ((V - v_fossa) ** 2) / (2 * sigma_fv**2)
    )
    depth_mod = depth_mod - 0.30 * fossa_dep

    # 耳垂区域 -- 下半部 z 逐渐减小
    lower_mask = np.clip((V - 0.75) / 0.25, 0.0, 1.0)
    depth_mod = depth_mod - 0.15 * lower_mask

    # 添加个体随机扰动
    noise = rng.normal(0, noise_scale, U.shape)

    # 计算坐标
    X = ear_width * (U - 0.5) * f_v
    Y = ear_height * (V - 0.35)
    Z = ear_depth * depth_mod + 0.5 * noise

    # 展平为顶点数组
    vertices = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])

    # 构建三角面片
    faces = []
    for i in range(n_u - 1):
        for j in range(n_v - 1):
            idx = i * n_v + j
            # 两个三角形
            faces.append([idx, idx + 1, idx + n_v])
            faces.append([idx + 1, idx + n_v + 1, idx + n_v])
    faces = np.array(faces, dtype=int)

    # ---- 特征点定位 ----
    # 定义特征点在 (u, v) 参数空间中的位置, 然后从曲面采样
    # 这些 u,v 坐标根据解剖位置精心设定
    landmark_uv = {
        "L02": (0.52, 0.02),   # 耳上点 - 外耳最高点
        "L07": (0.55, 0.20),   # 耳根上点 - 耳根上边界
        "L10": (0.42, 0.35),   # 耳甲腔上点 - 耳甲腔上缘
        "L13": (0.22, 0.40),   # 耳甲前缘点 - 耳甲腔前侧边界
        "L15": (0.75, 0.30),   # 耳根后点 - 耳根后侧位置
        "L19": (0.22, 0.55),   # 耳屏点 - 耳屏位置
        "L20": (0.62, 0.53),   # 对耳屏点 - 对耳屏位置
        "L21": (0.42, 0.58),   # 耳屏间切迹 - 耳屏与对耳屏之间凹陷
        "L26": (0.50, 0.92),   # 耳根下点 - 耳根下边界
        "L28": (0.38, 0.48),   # 耳道入口上点
        "L29": (0.38, 0.54),   # 耳道入口下点
        "L30": (0.38, 0.51),   # 耳道截面中心
        "L31": (0.55, 0.32),   # 三角窝附近耳轮后点
    }

    # 从曲面插值获取 landmark 的三维坐标
    # 使用二维线性插值: 从 U, V, Z 网格中插值得到 z, 然后 x,y 用公式算
    from scipy.interpolate import RegularGridInterpolator

    z_interp = RegularGridInterpolator(
        (u_vals, v_vals), Z,  # Z shape (n_u, n_v), meshgrid(..., indexing="ij") already correct
        bounds_error=False,
        fill_value=None,
    )

    landmark_coords = {}
    for lm_id, (u_lm, v_lm) in landmark_uv.items():
        # 插值 z
        z_val = float(z_interp(np.array([[u_lm, v_lm]]))[0])
        # 计算 x, y
        # f_v at this v
        f_v_lm = 1.0 - 0.15 * np.sin(np.pi * v_lm) - 0.05 * np.cos(2 * np.pi * v_lm)
        x_val = ear_width * (u_lm - 0.5) * f_v_lm
        y_val = ear_height * (v_lm - 0.35)
        landmark_coords[lm_id] = (x_val, y_val, z_val)

    return vertices, faces, landmark_coords


def save_mesh_ply(vertices: np.ndarray, faces: np.ndarray, filepath: Path):
    """保存 mesh 为 PLY 文件."""
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.export(str(filepath))


def save_landmarks_csv(landmark_coords: dict, filepath: Path, sample_id: str, annotator: str = "simulated"):
    """保存特征点为 CSV 文件."""
    records = []
    for lm_id in LANDMARK_IDS:
        x, y, z = landmark_coords[lm_id]
        records.append({
            "landmark_id": lm_id,
            "x": round(x, 4),
            "y": round(y, 4),
            "z": round(z, 4),
            "confidence": 1.0,
            "annotator": annotator,
            "comment": "",
        })
    df = pd.DataFrame(records)
    df.to_csv(filepath, index=False)


def generate_all_simulated_data(
    clean_mesh_dir: Path,
    landmarks_dir: Path,
    logger: logging.Logger,
):
    """
    生成所有模拟样本的 mesh 和 landmarks.

    使用不同随机种子确保样本之间有合理的个体差异.
    """
    logger.info("开始生成模拟数据...")

    seeds = [42, 123, 999]  # S001, S002, S003 各用不同种子
    noise_levels = [0.25, 0.35, 0.28]  # 个体噪声水平

    for i, sample_id in enumerate(SIMULATED_SAMPLES):
        logger.info(f"  生成 {sample_id}_{SIMULATED_SIDE} (seed={seeds[i]})...")

        vertices, faces, landmark_coords = generate_ear_surface(
            seed=seeds[i],
            noise_scale=noise_levels[i],
        )

        # 保存 mesh
        mesh_path = clean_mesh_dir / f"{sample_id}_{SIMULATED_SIDE}.ply"
        save_mesh_ply(vertices, faces, mesh_path)

        # 保存 landmarks
        lm_path = landmarks_dir / f"{sample_id}_{SIMULATED_SIDE}_landmarks.csv"
        save_landmarks_csv(landmark_coords, lm_path, sample_id)

        logger.info(
            f"    -> mesh: {mesh_path} (顶点={vertices.shape[0]}, 面={faces.shape[0]})"
        )
        logger.info(f"    -> landmarks: {lm_path}")

    logger.info("模拟数据生成完成.\n")


# ============================================================================
# 3. 工具函数: 文件加载
# ============================================================================

def read_csv_robust(filepath: Path, logger: logging.Logger | None = None) -> pd.DataFrame:
    """以 UTF-8 优先、GBK 兜底的方式读取 CSV."""
    for enc in ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin-1']:
        try:
            df = pd.read_csv(filepath, encoding=enc)
            if logger:
                logger.debug(f"读取 CSV: {filepath} (encoding={enc})")
            return df
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"无法解码 CSV 文件: {filepath}")


def load_mesh(mesh_path: str, logger: logging.Logger) -> trimesh.Trimesh:
    """
    加载 mesh 文件 (.ply, .obj, .stl).

    Parameters
    ----------
    mesh_path : str
        Mesh 文件路径.
    logger : logging.Logger
        日志记录器.

    Returns
    -------
    trimesh.Trimesh
        加载的 mesh 对象.

    Raises
    ------
    ValueError
        如果无法加载或 mesh 为空.
    """
    logger.debug(f"加载 mesh: {mesh_path}")
    mesh = trimesh.load(mesh_path, process=False)

    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))

    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"无法将文件加载为 Trimesh: {mesh_path}")

    if mesh.vertices.shape[0] == 0:
        raise ValueError(f"空 mesh: {mesh_path}")

    logger.debug(f"  -> 顶点数={mesh.vertices.shape[0]}, 面数={len(mesh.faces) if mesh.faces is not None else 0}")
    return mesh


def load_landmarks(csv_path: str, logger: logging.Logger) -> pd.DataFrame:
    """
    加载特征点 CSV 文件.

    Parameters
    ----------
    csv_path : str
        CSV 文件路径, 至少包含 landmark_id, x, y, z 列.
    logger : logging.Logger
        日志记录器.

    Returns
    -------
    pd.DataFrame
        以 landmark_id 为索引的 DataFrame.
    """
    logger.debug(f"加载特征点: {csv_path}")
    df = read_csv_robust(Path(csv_path), logger)

    required = {"landmark_id", "x", "y", "z"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"特征点文件缺少列: {missing}")

    df["landmark_id"] = df["landmark_id"].astype(str)
    df = df.set_index("landmark_id")
    logger.debug(f"  -> 加载了 {len(df)} 个特征点")
    return df


def get_landmark(lms: pd.DataFrame, lm_id: str, logger: logging.Logger) -> np.ndarray:
    """
    从 DataFrame 中提取指定特征点的 (x, y, z) 坐标.

    Parameters
    ----------
    lms : pd.DataFrame
        特征点 DataFrame, 以 landmark_id 为索引.
    lm_id : str
        特征点编号.
    logger : logging.Logger
        日志记录器.

    Returns
    -------
    np.ndarray
        shape (3,) 的坐标数组.
    """
    if lm_id not in lms.index:
        logger.error(f"缺少特征点: {lm_id}")
        raise KeyError(f"Missing landmark: {lm_id}")
    return lms.loc[lm_id, ["x", "y", "z"]].to_numpy(dtype=float)


# ============================================================================
# 4. 核心算法: 重心坐标与采样
# ============================================================================

def barycentric_3d(
    points: np.ndarray,
    A: np.ndarray,
    B: np.ndarray,
    C: np.ndarray,
) -> np.ndarray:
    """
    将三维点投影到三角形 ABC 所在平面, 并计算重心坐标.

    算法: 使用最小二乘法将点投影到三角形平面,
    然后解二维线性方程组求重心坐标.

    Parameters
    ----------
    points : np.ndarray, shape (N, 3)
        待投影的三维点集.
    A, B, C : np.ndarray, shape (3,)
        三角形的三个顶点.

    Returns
    -------
    np.ndarray, shape (N, 3)
        重心坐标 [lambda_A, lambda_B, lambda_C].

    Raises
    ------
    ValueError
        三角形接近退化 (面积接近0).
    """
    P = np.asarray(points, dtype=float)
    v0 = B - A
    v1 = C - A
    v2 = P - A

    d00 = np.dot(v0, v0)
    d01 = np.dot(v0, v1)
    d11 = np.dot(v1, v1)
    d20 = v2 @ v0
    d21 = v2 @ v1

    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-12:
        raise ValueError("退化三角形: 三个特征点接近共线 (面积≈0)")

    lambda_B = (d11 * d20 - d01 * d21) / denom
    lambda_C = (d00 * d21 - d01 * d20) / denom
    lambda_A = 1.0 - lambda_B - lambda_C

    return np.column_stack([lambda_A, lambda_B, lambda_C])


def make_barycentric_grid(resolution: int) -> np.ndarray:
    """
    在标准二维三角形中生成固定采样点的重心坐标.

    采样模式:
      - 三角形被细分为 resolution 份
      - 每条边被 r 等分
      - 总共 N = (r+1)(r+2)/2 个点

    Parameters
    ----------
    resolution : int
        采样阶数 r (r >= 1).

    Returns
    -------
    np.ndarray, shape (N, 3)
        重心坐标 [lambda_A, lambda_B, lambda_C].

    Raises
    ------
    ValueError
        resolution < 1.
    """
    if resolution < 1:
        raise ValueError(f"resolution 必须 >= 1, 当前值: {resolution}")

    samples = []
    r = resolution
    for i in range(r + 1):       # i = 0..r (lambda_B 方向)
        for j in range(r + 1 - i):  # j = 0..r-i (lambda_C 方向)
            lambda_B = i / r
            lambda_C = j / r
            lambda_A = 1.0 - lambda_B - lambda_C
            samples.append([lambda_A, lambda_B, lambda_C])

    return np.array(samples, dtype=float)


def remove_duplicate_uv(
    uv: np.ndarray,
    xyz: np.ndarray,
    decimals: int = 8,
) -> tuple[np.ndarray, np.ndarray]:
    """
    删除 UV 坐标重复的点, 防止 LinearNDInterpolator 报错.

    Parameters
    ----------
    uv : np.ndarray, shape (N, 2)
        二维 UV 坐标.
    xyz : np.ndarray, shape (N, 3)
        对应的三维坐标.
    decimals : int
        舍入精度.

    Returns
    -------
    uv_unique : np.ndarray
        去重后的 UV 坐标.
    xyz_unique : np.ndarray
        去重后的三维坐标.
    """
    uv_round = np.round(uv, decimals=decimals)
    _, unique_idx = np.unique(uv_round, axis=0, return_index=True)
    return uv[unique_idx], xyz[unique_idx]


def source_points_from_patch_mesh(
    patch_mesh: trimesh.Trimesh,
    dense_count: int = DENSE_SAMPLE_COUNT,
) -> np.ndarray:
    """
    从区域 patch mesh 中提取源点.

    优先在三角面上采样, 如果无法采样则使用顶点.

    Parameters
    ----------
    patch_mesh : trimesh.Trimesh
        区域 patch.
    dense_count : int
        面采样点数.

    Returns
    -------
    np.ndarray, shape (M, 3)
        源点坐标.
    """
    vertices = patch_mesh.vertices.copy()
    if patch_mesh.faces is not None and len(patch_mesh.faces) > 0:
        try:
            sampled, _ = trimesh.sample.sample_surface(patch_mesh, dense_count)
            points = np.vstack([vertices, sampled])
        except Exception:
            points = vertices
    else:
        points = vertices
    return points


# ============================================================================
# 5. 单区域处理
# ============================================================================

def process_region(
    sample_id: str,
    side: str,
    full_mesh: trimesh.Trimesh,
    patch_dir: Path | None,
    lms: pd.DataFrame,
    region: dict,
    global_start_id: int,
    logger: logging.Logger,
    projection_tol: float = PROJECTION_TOL,
) -> tuple[pd.DataFrame, dict]:
    """
    处理一个三角区域: 投影 -> 采样 -> 插值回三维.

    流程:
      1. 获取 A/B/C 三个特征点
      2. 生成源点 (优先用 patch 文件, 否则从 full mesh 投影筛选)
      3. 源点三维 -> 二维 (重心坐标)
      4. 固定采样
      5. 二维插值回三维 (LinearNDInterpolator + cKDTree 兜底)

    Parameters
    ----------
    sample_id : str
        样本编号.
    side : str
        左右侧.
    full_mesh : trimesh.Trimesh
        完整耳 mesh.
    patch_dir : Path | None
        patch 文件目录 (可为 None).
    lms : pd.DataFrame
        特征点表.
    region : dict
        区域定义, 包含 region_id, lm_a, lm_b, lm_c, resolution 等.
    global_start_id : int
        全局点编号起始值.
    logger : logging.Logger
        日志记录器.
    projection_tol : float
        投影筛选容差.

    Returns
    -------
    df_region : pd.DataFrame
        该区域的采样点记录.
    qc : dict
        该区域的 QC 信息.
    """
    region_id = str(region["region_id"])
    region_name = str(region.get("region_name", ""))
    lm_a = str(region["lm_a"])
    lm_b = str(region["lm_b"])
    lm_c = str(region["lm_c"])
    resolution = int(region["resolution"])
    expected_points = (resolution + 1) * (resolution + 2) // 2

    logger.info(f"  [{region_id}] {region_name}: A={lm_a}, B={lm_b}, C={lm_c}, r={resolution}, 预期点数={expected_points}")

    # Step 1: 获取特征点坐标
    A = get_landmark(lms, lm_a, logger)
    B = get_landmark(lms, lm_b, logger)
    C = get_landmark(lms, lm_c, logger)

    logger.debug(f"    A({lm_a}) = ({A[0]:.2f}, {A[1]:.2f}, {A[2]:.2f})")
    logger.debug(f"    B({lm_b}) = ({B[0]:.2f}, {B[1]:.2f}, {B[2]:.2f})")
    logger.debug(f"    C({lm_c}) = ({C[0]:.2f}, {C[1]:.2f}, {C[2]:.2f})")

    # Step 2: 获取源点
    patch_mesh = None
    used_patch_file = False

    if patch_dir is not None:
        candidate_files = [
            patch_dir / f"{region_id}.ply",
            patch_dir / f"{region_id}.obj",
            patch_dir / f"{region_id}.stl",
        ]
        for f in candidate_files:
            if f.exists():
                logger.debug(f"    使用 patch 文件: {f}")
                patch_mesh = load_mesh(str(f), logger)
                used_patch_file = True
                break

    if patch_mesh is not None:
        source_xyz = source_points_from_patch_mesh(patch_mesh)
        logger.debug(f"    patch 源点数={source_xyz.shape[0]}")
    else:
        # 从 full mesh 投影筛选
        logger.debug("    无 patch 文件, 从 full mesh 投影筛选...")
        source_xyz_all = full_mesh.vertices.copy()
        lambdas_all = barycentric_3d(source_xyz_all, A, B, C)
        mask = (
            np.all(lambdas_all >= -projection_tol, axis=1)
            & np.all(lambdas_all <= 1.0 + projection_tol, axis=1)
        )
        source_xyz = source_xyz_all[mask]
        logger.debug(f"    投影筛选后源点数={source_xyz.shape[0]} (全mesh顶点={source_xyz_all.shape[0]})")

    # 确保 A/B/C 在源点中 (边界稳定)
    source_xyz = np.vstack([
        source_xyz,
        A.reshape(1, 3),
        B.reshape(1, 3),
        C.reshape(1, 3),
    ])

    if source_xyz.shape[0] < MIN_SOURCE_POINTS:
        logger.error(f"    [{region_id}] 源点过少: {source_xyz.shape[0]} < {MIN_SOURCE_POINTS}")
        raise ValueError(f"区域 {region_id} 源点不足 (仅 {source_xyz.shape[0]} 个)")

    logger.debug(f"    去重前源点数={source_xyz.shape[0]}")

    # Step 3: 源点三维 -> 二维
    source_lambdas = barycentric_3d(source_xyz, A, B, C)
    source_uv = source_lambdas[:, [1, 2]]  # (lambda_B, lambda_C) -> (u, v)

    # 去重
    source_uv, source_xyz = remove_duplicate_uv(source_uv, source_xyz)
    logger.debug(f"    去重后源点数={source_xyz.shape[0]}")

    # Step 4: 生成目标采样点 (重心坐标网格)
    target_lambdas = make_barycentric_grid(resolution)
    target_uv = target_lambdas[:, [1, 2]]
    logger.debug(f"    目标采样点数={target_uv.shape[0]}")

    # Step 5: 二维插值回三维
    fallback_ratio = 0.0
    interpolator_used = "LinearNDInterpolator"

    try:
        interpolator = LinearNDInterpolator(source_uv, source_xyz)
        target_xyz = interpolator(target_uv)

        nan_mask = np.isnan(target_xyz).any(axis=1)
        n_nan = nan_mask.sum()

        if n_nan > 0:
            logger.debug(f"    LinearNDInterpolator 产生 {n_nan} 个 NaN, 使用 cKDTree 兜底")
            tree = cKDTree(source_uv)
            _, idx = tree.query(target_uv[nan_mask], k=1)
            target_xyz[nan_mask] = source_xyz[idx]
            fallback_ratio = float(n_nan / target_xyz.shape[0])
    except Exception as e:
        logger.warning(f"    LinearNDInterpolator 失败: {e}, 全部使用 cKDTree 最近邻")
        tree = cKDTree(source_uv)
        _, idx = tree.query(target_uv, k=1)
        target_xyz = source_xyz[idx]
        fallback_ratio = 1.0
        interpolator_used = "cKDTree(fallback)"

    logger.info(
        f"    [{region_id}] 完成: 源点={source_xyz.shape[0]}, "
        f"采样点={target_xyz.shape[0]}/{expected_points}, "
        f"兜底率={fallback_ratio:.2%}, 插值器={interpolator_used}"
    )

    # Step 6: 构建输出记录
    records = []
    n_points = target_xyz.shape[0]
    for local_id in range(n_points):
        point_global_id = global_start_id + local_id
        la, lb, lc = target_lambdas[local_id]
        u, v = target_uv[local_id]
        x, y, z = target_xyz[local_id]
        records.append({
            "sample_id": sample_id,
            "side": side,
            "region_id": region_id,
            "region_name": region_name,
            "point_id_global": point_global_id,
            "point_id_region": local_id,
            "x": round(x, 6),
            "y": round(y, 6),
            "z": round(z, 6),
            "u": round(u, 6),
            "v": round(v, 6),
            "lambda_a": round(la, 6),
            "lambda_b": round(lb, 6),
            "lambda_c": round(lc, 6),
            "lm_a": lm_a,
            "lm_b": lm_b,
            "lm_c": lm_c,
        })

    # QC 信息
    qc = {
        "region_id": region_id,
        "region_name": region_name,
        "used_patch_file": used_patch_file,
        "source_point_count": int(source_xyz.shape[0]),
        "sample_point_count": int(n_points),
        "expected_point_count": expected_points,
        "fallback_ratio": round(fallback_ratio, 6),
        "interpolator": interpolator_used,
        "status": _qc_status(fallback_ratio, int(n_points), expected_points),
    }

    return pd.DataFrame(records), qc


def _qc_status(fallback_ratio: float, actual: int, expected: int) -> str:
    """根据兜底比例和点数判定 QC 状态."""
    if actual != expected:
        return "FAIL"
    if fallback_ratio < FALLBACK_WARNING_THRESHOLD:
        return "PASS"
    elif fallback_ratio < FALLBACK_FAIL_THRESHOLD:
        return "WARNING"
    else:
        return "FAIL"


# ============================================================================
# 6. 主流程
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="3D耳模型参数化: 三角区域投影 + 统一重采样",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用已有数据
  python parameterize_ear.py \\
    --sample_id S001 --side R \\
    --mesh data/clean_mesh/S001_R.ply \\
    --landmarks data/landmarks/S001_R_landmarks.csv \\
    --regions config/region_table.csv \\
    --out_points output/parameterized_points/S001_R_points.csv \\
    --out_qc output/qc/S001_R_qc.csv

  # 使用 patch 目录
  python parameterize_ear.py \\
    --sample_id S001 --side R \\
    --mesh data/clean_mesh/S001_R.ply \\
    --landmarks data/landmarks/S001_R_landmarks.csv \\
    --regions config/region_table.csv \\
    --patch_dir data/patches_optional/S001_R \\
    --out_points output/parameterized_points/S001_R_points.csv \\
    --out_qc output/qc/S001_R_qc.csv
        """,
    )
    parser.add_argument("--sample_id", required=True, help="样本编号, 如 S001")
    parser.add_argument("--side", required=True, choices=["R", "L"], help="左右侧")
    parser.add_argument("--mesh", required=True, help="clean mesh 文件路径")
    parser.add_argument("--landmarks", required=True, help="特征点 CSV 路径")
    parser.add_argument("--regions", required=True, help="区域表 CSV 路径")
    parser.add_argument("--patch_dir", default=None, help="区域 patch 目录 (可选)")
    parser.add_argument("--out_points", required=True, help="输出点云 CSV 路径")
    parser.add_argument("--out_qc", required=True, help="输出 QC CSV 路径")
    parser.add_argument("--log_dir", default="output/logs", help="日志目录")
    args = parser.parse_args()

    # 解析路径
    mesh_path = Path(args.mesh)
    landmarks_path = Path(args.landmarks)
    regions_path = Path(args.regions)
    out_points_path = Path(args.out_points)
    out_qc_path = Path(args.out_qc)
    log_dir = Path(args.log_dir)
    patch_dir = Path(args.patch_dir) if args.patch_dir else None

    # 设置日志
    logger = setup_logging(args.sample_id, args.side, log_dir)

    try:
        # 加载数据
        logger.info("加载输入数据...")
        full_mesh = load_mesh(str(mesh_path), logger)
        lms = load_landmarks(str(landmarks_path), logger)
        regions = read_csv_robust(regions_path, logger)
        logger.info(f"加载了 {len(regions)} 个区域定义")
        # handle the case where region_id is nan or empty

        # 检查特征点完整性
        required_landmarks = set()
        for _, row in regions.iterrows():
            required_landmarks.add(str(row["lm_a"]))
            required_landmarks.add(str(row["lm_b"]))
            required_landmarks.add(str(row["lm_c"]))
        missing_lms = required_landmarks - set(lms.index)
        if missing_lms:
            raise ValueError(f"特征点缺失: {missing_lms}")
        logger.info(f"特征点检查通过: 需要 {len(required_landmarks)} 个, 实际 {len(lms)} 个")

        # 处理每个区域
        logger.info("开始处理各区域...")
        all_points = []
        qc_list = []
        global_id = 0

        for _, row in regions.iterrows():
            region = row.to_dict()
            try:
                df_region, qc = process_region(
                    sample_id=args.sample_id,
                    side=args.side,
                    full_mesh=full_mesh,
                    patch_dir=patch_dir,
                    lms=lms,
                    region=region,
                    global_start_id=global_id,
                    logger=logger,
                )
                all_points.append(df_region)
                qc_list.append(qc)
                global_id += len(df_region)
            except Exception as e:
                logger.error(f"处理区域 {row.get('region_id', '?')} 时出错: {e}")
                # 记录失败的区域
                qc_list.append({
                    "region_id": str(row.get("region_id", "?")),
                    "region_name": str(row.get("region_name", "")),
                    "used_patch_file": False,
                    "source_point_count": 0,
                    "sample_point_count": 0,
                    "expected_point_count": 0,
                    "fallback_ratio": 1.0,
                    "interpolator": "N/A",
                    "status": "FAIL",
                })
                raise

        # 合并所有区域
        df_all = pd.concat(all_points, ignore_index=True)

        # 保存输出
        out_points_path.parent.mkdir(parents=True, exist_ok=True)
        out_qc_path.parent.mkdir(parents=True, exist_ok=True)

        df_all.to_csv(out_points_path, index=False)
        pd.DataFrame(qc_list).to_csv(out_qc_path, index=False)

        # 打印摘要
        total_points = len(df_all)
        logger.info("=" * 60)
        logger.info("参数化完成!")
        logger.info(f"  总采样点数: {total_points}")
        logger.info(f"  区域数: {len(qc_list)}")
        logger.info(f"  点云输出: {out_points_path}")
        logger.info(f"  QC 输出:  {out_qc_path}")

        # QC 摘要
        qc_df = pd.DataFrame(qc_list)
        pass_count = (qc_df["status"] == "PASS").sum()
        warn_count = (qc_df["status"] == "WARNING").sum()
        fail_count = (qc_df["status"] == "FAIL").sum()
        logger.info(f"  QC: PASS={pass_count}, WARNING={warn_count}, FAIL={fail_count}")

        if fail_count > 0:
            logger.warning("存在 FAIL 区域, 请检查 QC 报告!")

        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"参数化失败: {e}", exc_info=True)
        sys.exit(1)


# ============================================================================
# 7. 一键运行入口 (模拟数据生成 + 批量参数化)
# ============================================================================

def run_simulation(
    project_root: Path | None = None,
):
    """
    一键运行模拟流程:
      1. 生成模拟 mesh + landmarks
      2. 对每个样本执行参数化

    Parameters
    ----------
    project_root : Path | None
        项目根目录. 默认为脚本所在目录的上一级.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    clean_mesh_dir = project_root / "data" / "clean_mesh"
    landmarks_dir = project_root / "data" / "landmarks"
    regions_csv = project_root / "config" / "region_table.csv"
    output_points_dir = project_root / "output" / "parameterized_points"
    output_qc_dir = project_root / "output" / "qc"
    log_dir = project_root / "output" / "logs"

    # 确保目录存在
    for d in [clean_mesh_dir, landmarks_dir, output_points_dir, output_qc_dir, log_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # 设置主日志
    main_logger = setup_logging("SIMULATION", "ALL", log_dir)
    main_logger.info("=" * 60)
    main_logger.info("开始一键模拟流程")
    main_logger.info(f"项目根目录: {project_root}")
    main_logger.info("=" * 60)

    # Step 1: 生成模拟数据
    generate_all_simulated_data(clean_mesh_dir, landmarks_dir, main_logger)

    # Step 2: 检查 region_table.csv
    if not regions_csv.exists():
        main_logger.error(f"区域表不存在: {regions_csv}")
        sys.exit(1)
    regions = read_csv_robust(regions_csv, main_logger)
    main_logger.info(f"区域表: {len(regions)} 个区域")
    for _, r in regions.iterrows():
        n_expected = (int(r["resolution"]) + 1) * (int(r["resolution"]) + 2) // 2
        main_logger.info(f"  {r['region_id']}: resolution={r['resolution']}, 预期点数={n_expected}, PCA={r['use_for_pca']}")

    # Step 3: 对每个样本运行参数化
    main_logger.info("\n" + "=" * 60)
    main_logger.info("开始批量参数化...")
    main_logger.info("=" * 60)

    all_qc_summaries = []

    for sample_id in SIMULATED_SAMPLES:
        side = SIMULATED_SIDE
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

        # 当前样本日志
        sample_logger = setup_logging(sample_id, side, log_dir)

        try:
            main_logger.info(f"\n--- 处理 {sample_id}_{side} ---")
            full_mesh = load_mesh(str(mesh_path), sample_logger)
            lms = load_landmarks(str(landmarks_path), sample_logger)

            required_landmarks = set()
            for _, row in regions.iterrows():
                required_landmarks.add(str(row["lm_a"]))
                required_landmarks.add(str(row["lm_b"]))
                required_landmarks.add(str(row["lm_c"]))
            missing_lms = required_landmarks - set(lms.index)
            if missing_lms:
                raise ValueError(f"特征点缺失: {missing_lms}")

            all_points = []
            qc_list = []
            global_id = 0

            for _, row in regions.iterrows():
                region = row.to_dict()
                try:
                    df_region, qc = process_region(
                        sample_id=sample_id,
                        side=side,
                        full_mesh=full_mesh,
                        patch_dir=None,  # 模拟数据无 patch
                        lms=lms,
                        region=region,
                        global_start_id=global_id,
                        logger=sample_logger,
                    )
                    all_points.append(df_region)
                    qc_list.append(qc)
                    global_id += len(df_region)
                except Exception as e:
                    sample_logger.error(f"区域 {region.get('region_id', '?')} 处理失败: {e}")
                    qc_list.append({
                        "region_id": str(region.get("region_id", "?")),
                        "region_name": str(region.get("region_name", "")),
                        "used_patch_file": False,
                        "source_point_count": 0,
                        "sample_point_count": 0,
                        "expected_point_count": (int(region["resolution"]) + 1) * (int(region["resolution"]) + 2) // 2,
                        "fallback_ratio": 1.0,
                        "interpolator": "N/A",
                        "status": "FAIL",
                    })
                    continue

            df_all = pd.concat(all_points, ignore_index=True)
            df_all.to_csv(out_points, index=False)
            pd.DataFrame(qc_list).to_csv(out_qc, index=False)

            # QC 摘要
            qc_df = pd.DataFrame(qc_list)
            pass_c = (qc_df["status"] == "PASS").sum()
            warn_c = (qc_df["status"] == "WARNING").sum()
            fail_c = (qc_df["status"] == "FAIL").sum()

            sample_logger.info(f"  [{sample_id}] 完成: 总点数={len(df_all)}, QC: PASS={pass_c} WARNING={warn_c} FAIL={fail_c}")

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
    main_logger.info("\n" + "=" * 60)
    main_logger.info("批量参数化完成 - 最终摘要")
    main_logger.info("=" * 60)

    summary_df = pd.DataFrame(all_qc_summaries)
    for _, s in summary_df.iterrows():
        status_icon = "OK" if s["fail"] == 0 else "FAIL"
        main_logger.info(
            f"  {status_icon} {s['sample_id']}_{s['side']}: "
            f"总点={s['total_points']}, "
            f"PASS={s['pass']}, WARN={s['warning']}, FAIL={s['fail']}"
        )

    main_logger.info(f"\n输出目录:")
    main_logger.info(f"  点云: {output_points_dir}")
    main_logger.info(f"  QC:   {output_qc_dir}")
    main_logger.info(f"  日志: {log_dir}")
    main_logger.info("=" * 60)


# ============================================================================
# 8. 入口
# ============================================================================

if __name__ == "__main__":
    # 如果直接运行脚本 (无命令行参数), 执行模拟流程
    if len(sys.argv) == 1:
        print("未提供命令行参数, 切换到模拟模式...")
        print("(使用 --help 查看参数化模式用法)")
        print()
        run_simulation()
    else:
        main()