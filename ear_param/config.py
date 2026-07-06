#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py — 全局配置与常量定义
===============================

集中管理所有可调参数和常量，便于统一修改和调参。

技术依据: 《人头给你了-3D 耳模型跨模型参数化与特征值计算技术执行文档-v0.0》
"""

# ============================================================================
# 特征点定义
# ============================================================================

# 论文 31 个特征点中本项目使用的子集
LANDMARK_IDS: list[str] = [
    "L02", "L07", "L10", "L13", "L15",
    "L19", "L20", "L21", "L26", "L28",
    "L29", "L30", "L31",
]

# ============================================================================
# 模拟样本配置
# ============================================================================

SIMULATED_SAMPLES: list[str] = ["S001", "S002", "S003"]
SIMULATED_SIDE: str = "R"          # 统一用右耳
SIMULATED_SEEDS: list[int] = [42, 123, 999]
SIMULATED_NOISE_LEVELS: list[float] = [0.25, 0.35, 0.28]

# 耳朵外形参数 (mm)
DEFAULT_EAR_WIDTH: float = 35.0
DEFAULT_EAR_HEIGHT: float = 60.0
DEFAULT_EAR_DEPTH: float = 15.0
DEFAULT_EAR_NOISE_SCALE: float = 0.3

# ============================================================================
# 投影参数
# ============================================================================

# 重心坐标容差: 允许 lambda 超出 [0,1] 的容差范围
PROJECTION_TOL: float = 0.15

# ============================================================================
# 插值与兜底参数
# ============================================================================

# 插值兜底阈值
FALLBACK_WARNING_THRESHOLD: float = 0.05   # 5%  -> WARNING
FALLBACK_FAIL_THRESHOLD: float = 0.20      # 20% -> FAIL

# 源点最小数量
MIN_SOURCE_POINTS: int = 5

# 网格面采样密度
DENSE_SAMPLE_COUNT: int = 5000

# ============================================================================
# 目录结构 (相对项目根目录)
# ============================================================================

DIR_CLEAN_MESH: str = "data/clean_mesh"
DIR_LANDMARKS: str = "data/landmarks"
DIR_OUTPUT_POINTS: str = "output/parameterized_points"
DIR_OUTPUT_QC: str = "output/qc"
DIR_OUTPUT_LOGS: str = "output/logs"

# 区域定义表路径
PATH_REGION_TABLE: str = "config/region_table.csv"

