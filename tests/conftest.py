#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
conftest.py — pytest 共享 fixtures 与配置
==========================================

为 ear_param 包提供可复用的测试数据生成器,
涵盖三角形、点云、mesh、landmarks、区域定义等常用 mock 对象。

Fixtures 约定:
  - 命名描述数据内容 (e.g. unit_triangle, right_triangle)
  - 返回类型明确 (np.ndarray, trimesh.Trimesh, pd.DataFrame 等)
  - 所有 fixtures 为 function scope (隔离各测试用例)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import trimesh

# 确保项目根目录在 sys.path 中, 使 ear_param 可导入
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ear_param.config import (
    LANDMARK_IDS,
    PROJECTION_TOL,
    MIN_SOURCE_POINTS,
    DENSE_SAMPLE_COUNT,
)
from ear_param.core import make_barycentric_grid


# ============================================================================
# 基础几何 fixtures
# ============================================================================


@pytest.fixture
def unit_triangle() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    等边直角三角形, 位于 XY 平面, 边长为 1.

    顶点:
      A = (0, 0, 0)
      B = (1, 0, 0)
      C = (0, 1, 0)

    面积 = 0.5, 非退化.
    """
    a = np.array([0.0, 0.0, 0.0])
    b = np.array([1.0, 0.0, 0.0])
    c = np.array([0.0, 1.0, 0.0])
    return a, b, c


@pytest.fixture
def right_triangle() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    一般位置直角三角形, 非单位长度.

    A = (1, 2, 1)
    B = (4, 2, 1)
    C = (1, 5, 1)

    AB 长 3, AC 长 3, 面积 = 4.5.
    """
    a = np.array([1.0, 2.0, 1.0])
    b = np.array([4.0, 2.0, 1.0])
    c = np.array([1.0, 5.0, 1.0])
    return a, b, c


@pytest.fixture
def degenerate_triangle() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    退化三角形: 三点共线.

    A = (0, 0, 0)
    B = (1, 1, 1)
    C = (2, 2, 2)

    面积 = 0.
    """
    a = np.array([0.0, 0.0, 0.0])
    b = np.array([1.0, 1.0, 1.0])
    c = np.array([2.0, 2.0, 2.0])
    return a, b, c


@pytest.fixture
def near_degenerate_triangle() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    接近退化但面积 > eps 的三角形.

    用于验证退化检测的边界行为.
    """
    a = np.array([0.0, 0.0, 0.0])
    b = np.array([1.0, 0.0, 0.0])
    c = np.array([1.0, 1e-4, 0.0])
    return a, b, c


@pytest.fixture
def flat_triangle() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    倾斜但非退化的三角形, 平面不与任何坐标轴对齐.
    用于验证三维空间到三角形平面的投影.

    A = (0, 0, 0)
    B = (3, 1, 2)
    C = (1, 4, -1)
    """
    a = np.array([0.0, 0.0, 0.0])
    b = np.array([3.0, 1.0, 2.0])
    c = np.array([1.0, 4.0, -1.0])
    return a, b, c


# ============================================================================
# 点云 fixtures
# ============================================================================


@pytest.fixture
def points_inside_unit_triangle() -> np.ndarray:
    """
    严格位于 unit_triangle 内部的点 (z=0, 重心坐标均 ∈ [0,1]).
    """
    return np.array([
        [0.2, 0.3, 0.0],
        [0.1, 0.1, 0.0],
        [0.5, 0.2, 0.0],
        [0.3, 0.6, 0.0],
        [0.7, 0.1, 0.0],
    ])


@pytest.fixture
def points_on_triangle_vertices() -> np.ndarray:
    """三角形三个顶点本身."""
    return np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ])


@pytest.fixture
def points_on_triangle_edges() -> np.ndarray:
    """三角形边上的点."""
    return np.array([
        [0.5, 0.0, 0.0],   # AB 中点
        [0.0, 0.5, 0.0],   # AC 中点
        [0.5, 0.5, 0.0],   # BC 中点
    ])


@pytest.fixture
def points_outside_triangle() -> np.ndarray:
    """明显在三角形外部的点."""
    return np.array([
        [-1.0, -1.0, 0.0],
        [2.0, 2.0, 0.0],
        [1.0, 2.0, 0.0],
        [-0.5, 1.5, 0.0],
    ])


@pytest.fixture
def points_offset_above_triangle() -> np.ndarray:
    """
    在 XY 投影落在三角形内, 但 Z 坐标偏移的点.

    用于验证三维点到三角形平面的投影计算.
    """
    return np.array([
        [0.2, 0.3, 5.0],
        [0.1, 0.1, -3.0],
        [0.5, 0.2, 10.0],
    ])


# ============================================================================
# mesh fixtures
# ============================================================================


@pytest.fixture
def simple_plane_mesh() -> trimesh.Trimesh:
    """
    简单平面 mesh: 由两个三角形组成的单位正方形.

    顶点:
      (0,0,0), (1,0,0), (1,1,0), (0,1,0)

    面:
      [0,1,2], [0,2,3]
    """
    vertices = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0],
    ])
    faces = np.array([
        [0, 1, 2],
        [0, 2, 3],
    ])
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


@pytest.fixture
def small_dense_mesh() -> trimesh.Trimesh:
    """
    小型密集网格: 位于 XY 平面, 尺寸约 10x10, 共 121 个顶点.

    通过 meshgrid 生成, 用于测试 DENSE_SAMPLE_COUNT 以下的路径.
    """
    grid = np.linspace(0, 10, 11)
    xx, yy = np.meshgrid(grid, grid)
    vertices = np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)])
    from scipy.spatial import Delaunay
    tri_uv = Delaunay(vertices[:, :2])
    faces = tri_uv.simplices
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


# ============================================================================
# landmarks fixtures
# ============================================================================


@pytest.fixture
def landmarks_unit_triangle() -> pd.DataFrame:
    """
    模拟特征点: 以 unit_triangle 三个顶点 + 三角形中心为 landmarks.

    包含 L02, L10, L13, L15 — 覆盖 region_table.csv 中需要的部分 ID.
    """
    records = [
        {"landmark_id": "L10", "x": 0.0, "y": 0.0, "z": 0.0},   # A
        {"landmark_id": "L02", "x": 1.0, "y": 0.0, "z": 0.0},   # B
        {"landmark_id": "L13", "x": 0.0, "y": 1.0, "z": 0.0},   # C
        {"landmark_id": "L15", "x": 0.3, "y": 0.3, "z": 0.0},   # 内部
    ]
    df = pd.DataFrame(records)
    df = df.set_index("landmark_id")
    return df


@pytest.fixture
def landmarks_full() -> pd.DataFrame:
    """
    模拟完整 13 个特征点, 位于简单几何位置.

    每个 landmark 坐标基于其在参数空间中的预定义位置缩放.
    """
    # 使用 config 中的 landmark ID 列表
    positions = {
        "L02": (4.8, 0.2, 0.0),
        "L07": (9.0, 6.2, 0.0),
        "L10": (3.0, 3.0, 0.0),
        "L13": (0.8, 7.5, 0.0),
        "L15": (9.5, 5.0, 0.0),
        "L19": (1.0, 9.5, 0.0),
        "L20": (8.5, 9.5, 0.0),
        "L21": (4.0, 9.5, 0.0),
        "L26": (5.0, 9.8, 0.0),
        "L28": (4.0, 6.0, 0.0),
        "L29": (4.0, 7.5, 0.0),
        "L30": (4.0, 5.5, 0.0),
        "L31": (6.0, 2.5, 0.0),
    }
    records = []
    for lm_id in LANDMARK_IDS:
        x, y, z = positions.get(lm_id, (0.0, 0.0, 0.0))
        records.append({
            "landmark_id": lm_id,
            "x": x, "y": y, "z": z,
            "confidence": 1.0,
            "annotator": "test",
            "comment": "",
        })
    df = pd.DataFrame(records)
    df = df.set_index("landmark_id")
    return df


# ============================================================================
# 区域定义 fixtures
# ============================================================================


@pytest.fixture
def region_basic() -> dict:
    """基本区域定义 (使用 unit_triangle 的 landmarks)."""
    return {
        "region_id": "T001",
        "region_name": "耳甲腔上区",
        "lm_a": "L10",   # A = (0,0,0)
        "lm_b": "L02",   # B = (1,0,0)
        "lm_c": "L13",   # C = (0,1,0)
        "resolution": 4,
    }


# ============================================================================
# Logger fixtures
# ============================================================================


@pytest.fixture
def null_logger():
    """返回一个将输出写入 /dev/null 的 logger, 避免测试日志污染."""
    import logging
    logger = logging.getLogger("test_null")
    logger.setLevel(logging.DEBUG)
    # 清除已有 handler
    logger.handlers.clear()
    # 添加 NullHandler
    logger.addHandler(logging.NullHandler())
    return logger


# ============================================================================
# 重心坐标 & 插值 fixtures
# ============================================================================


@pytest.fixture
def barycentric_grid_res4() -> np.ndarray:
    """分辨率 4 的重心坐标网格: (5*6)/2 = 15 个点."""
    grid = make_barycentric_grid(4)
    assert grid.shape == (15, 3)
    return grid


@pytest.fixture
def barycentric_grid_res8() -> np.ndarray:
    """分辨率 8 的重心坐标网格: (9*10)/2 = 45 个点."""
    grid = make_barycentric_grid(8)
    assert grid.shape == (45, 3)
    return grid