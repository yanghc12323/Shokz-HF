#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
io_utils.py — 文件 I/O 与日志工具
==================================

提供统一的文件加载、保存和日志配置接口。

包含:
  - read_csv_robust: 多编码兼容的 CSV 读取
  - load_mesh:       通用 mesh 加载 (ply/obj/stl)
  - load_landmarks:  特征点 CSV 加载与校验
  - get_landmark:    从 DataFrame 提取单个特征点坐标
  - save_mesh_ply:   保存 mesh 为 PLY
  - save_landmarks_csv: 保存特征点 CSV
  - setup_logging:   配置双输出日志 (控制台 + 文件)
"""

import logging
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import trimesh


# ============================================================================
# 日志配置
# ============================================================================

def setup_logging(
    sample_id: str,
    side: str,
    log_dir: Path,
) -> logging.Logger:
    """
    配置日志: 同时输出到控制台和文件.

    - 文件 handler 使用 DEBUG 级别, 记录详细调试信息
    - 控制台 handler 使用 INFO 级别, 避免刷屏

    Parameters
    ----------
    sample_id : str
        样本编号, 如 'S001', 或 'SIMULATION' 用于批量模式.
    side : str
        左右侧, 'R' 或 'L', 或 'ALL' 用于批量模式.
    log_dir : Path
        日志输出目录.

    Returns
    -------
    logging.Logger
        配置好的 logger 实例, 格式为:
        "YYYY-MM-DD HH:MM:SS | LEVEL    | message"
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{sample_id}_{side}_parameterize_{timestamp}.log"

    logger = logging.getLogger(f"parameterize_{sample_id}_{side}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()  # 防止重复添加 handler

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件 handler (DEBUG 级别)
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 控制台 handler (INFO 级别)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


# ============================================================================
# CSV 读取
# ============================================================================

def read_csv_robust(
    filepath: Path,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """
    以 UTF-8 优先、多编码兜底的方式读取 CSV 文件.

    自动尝试以下编码顺序:
      utf-8 → utf-8-sig → gbk → gb2312 → latin-1

    Parameters
    ----------
    filepath : Path
        CSV 文件路径.
    logger : logging.Logger | None
        日志记录器, 可选.

    Returns
    -------
    pd.DataFrame
        读取的数据表.

    Raises
    ------
    ValueError
        所有编码尝试均失败时抛出.
    """
    encodings = ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin-1']
    for enc in encodings:
        try:
            df = pd.read_csv(str(filepath), encoding=enc)
            if logger:
                logger.debug(f"读取 CSV: {filepath} (encoding={enc})")
            return df
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"无法解码 CSV 文件: {filepath}")


# ============================================================================
# Mesh 加载与保存
# ============================================================================

def load_mesh(
    mesh_path: str | Path,
    logger: logging.Logger | None = None,
) -> trimesh.Trimesh:
    """
    加载 mesh 文件 (.ply, .obj, .stl).

    自动处理 Scene 类型 (提取所有几何体合并).

    Parameters
    ----------
    mesh_path : str | Path
        Mesh 文件路径.
    logger : logging.Logger | None
        日志记录器, 可选.

    Returns
    -------
    trimesh.Trimesh
        加载的独立 mesh 对象.

    Raises
    ------
    FileNotFoundError
        文件不存在.
    ValueError
        无法加载为 Trimesh 或 mesh 为空.
    """
    mesh_path = Path(mesh_path)
    if not mesh_path.exists():
        raise FileNotFoundError(f"Mesh 文件不存在: {mesh_path}")

    if logger:
        logger.debug(f"加载 mesh: {mesh_path}")

    mesh = trimesh.load(str(mesh_path), process=False)

    # 处理 Scene 类型
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))

    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"无法将文件加载为 Trimesh: {mesh_path}")

    n_verts = mesh.vertices.shape[0]
    n_faces = len(mesh.faces) if mesh.faces is not None else 0
    if n_verts == 0:
        raise ValueError(f"空 mesh: {mesh_path}")

    if logger:
        logger.debug(f"  -> 顶点数={n_verts}, 面数={n_faces}")

    return mesh


def save_mesh_ply(
    vertices: np.ndarray,
    faces: np.ndarray,
    filepath: Path,
) -> None:
    """
    保存 mesh 为 PLY 文件.

    Parameters
    ----------
    vertices : np.ndarray, shape (N, 3)
        网格顶点坐标.
    faces : np.ndarray, shape (M, 3)
        三角面片索引.
    filepath : Path
        输出文件路径.
    """
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.export(str(filepath))


# ============================================================================
# Landmarks 加载与保存
# ============================================================================

def load_landmarks(
    csv_path: str | Path,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """
    加载特征点 CSV 文件.

    要求至少包含以下列: landmark_id, x, y, z.
    以 landmark_id 作为 DataFrame 索引.

    Parameters
    ----------
    csv_path : str | Path
        CSV 文件路径.
    logger : logging.Logger | None
        日志记录器, 可选.

    Returns
    -------
    pd.DataFrame
        以 landmark_id 为索引的特征点 DataFrame.

    Raises
    ------
    FileNotFoundError
        文件不存在.
    ValueError
        缺少必要列.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"特征点文件不存在: {csv_path}")

    if logger:
        logger.debug(f"加载特征点: {csv_path}")

    df = read_csv_robust(csv_path, logger)

    required = {"landmark_id", "x", "y", "z"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"特征点文件缺少列: {missing}, 实际列: {list(df.columns)}")

    df["landmark_id"] = df["landmark_id"].astype(str)
    df = df.set_index("landmark_id")

    if logger:
        logger.debug(f"  -> 加载了 {len(df)} 个特征点")

    return df


def get_landmark(
    lms: pd.DataFrame,
    lm_id: str,
    logger: logging.Logger | None = None,
) -> np.ndarray:
    """
    从特征点 DataFrame 中提取指定 landmark 的 (x, y, z) 坐标.

    Parameters
    ----------
    lms : pd.DataFrame
        以 landmark_id 为索引的特征点表.
    lm_id : str
        特征点编号, 如 'L10'.
    logger : logging.Logger | None
        日志记录器, 可选.

    Returns
    -------
    np.ndarray, shape (3,)
        特征点的三维坐标数组 [x, y, z].

    Raises
    ------
    KeyError
        指定的 landmark 不存在.
    """
    if lm_id not in lms.index:
        msg = f"缺少特征点: {lm_id}"
        if logger:
            logger.error(msg)
        raise KeyError(msg)
    return lms.loc[lm_id, ["x", "y", "z"]].to_numpy(dtype=float)


def save_landmarks_csv(
    landmark_coords: dict[str, tuple[float, float, float]],
    filepath: Path,
    sample_id: str,
    landmark_ids: list[str] | None = None,
    annotator: str = "simulated",
) -> None:
    """
    保存特征点为 CSV 文件.

    Parameters
    ----------
    landmark_coords : dict
        {landmark_id: (x, y, z)} 坐标字典.
    filepath : Path
        输出文件路径.
    sample_id : str
        样本编号 (仅用于注释, 不影响输出内容).
    landmark_ids : list[str] | None
        要输出的 landmark 编号列表. 为 None 时输出全部.
    annotator : str
        标注者标识.
    """
    ids = landmark_ids if landmark_ids is not None else list(landmark_coords.keys())
    records = []
    for lm_id in ids:
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
    df.to_csv(str(filepath), index=False)