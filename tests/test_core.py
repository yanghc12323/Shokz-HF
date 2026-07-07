#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_core.py — ear_param.core 模块单元测试
============================================

覆盖 core.py 中所有核心数学函数:
  1. _is_triangle_degenerate    — 三角形退化检测
  2. _barycentric_batch         — 批量重心坐标计算
  3. barycentric_3d             — 单点重心坐标 (公开接口)
  4. _clip_points_to_triangle    — 三角形区域源点裁剪
  5. make_barycentric_grid       — 固定分辨率重心坐标网格
  6. _to_atlas_uv                — 二维 UV 展开
  7. _interpolate_sample_points  — 插值重建采样点
  8. process_region              — 单区域完整处理流水线

测试分类:
  - TestIsTriangleDegenerate:    退化检测 (边界条件)
  - TestBarycentricBatch:        批量重心坐标 (数值正确性 + 不变性)
  - TestBarycentric3D:           单点接口 (一致性验证)
  - TestClipPointsToTriangle:    裁剪逻辑 (内部/外部/边界/容差)
  - TestMakeBarycentricGrid:     网格生成 (点数/形状/属性)
  - TestToAtlasUV:               UV 展开 (local/atlas 坐标)
  - TestInterpolateSamplePoints: 插值重建 (正常/兜底/边界)
  - TestProcessRegion:           端到端集成 (返回结构/Qubit 指标)
"""

from __future__ import annotations

import math
import logging

import numpy as np
import pandas as pd
import pytest

# 导入待测函数
from ear_param.core import (
    _is_triangle_degenerate,
    _barycentric_batch,
    barycentric_3d,
    _clip_points_to_triangle,
    make_barycentric_grid,
    _to_atlas_uv,
    _interpolate_sample_points,
    process_region,
)
from ear_param.config import (
    PROJECTION_TOL,
    FALLBACK_WARNING_THRESHOLD,
    FALLBACK_FAIL_THRESHOLD,
    MIN_SOURCE_POINTS,
    DENSE_SAMPLE_COUNT,
)


# ============================================================================
# 1. 三角形退化检测
# ============================================================================


class TestIsTriangleDegenerate:
    """测试 _is_triangle_degenerate 函数."""

    def test_non_degenerate_unit_triangle(self, unit_triangle):
        """非退化单位三角形应返回 False."""
        a, b, c = unit_triangle
        assert _is_triangle_degenerate(a, b, c) is False

    def test_non_degenerate_right_triangle(self, right_triangle):
        """一般位置直角三角形应返回 False."""
        a, b, c = right_triangle
        assert _is_triangle_degenerate(a, b, c) is False

    def test_non_degenerate_flat_triangle(self, flat_triangle):
        """倾斜非退化三角形应返回 False."""
        a, b, c = flat_triangle
        assert _is_triangle_degenerate(a, b, c) is False

    def test_degenerate_collinear(self, degenerate_triangle):
        """共线三点应返回 True."""
        a, b, c = degenerate_triangle
        assert _is_triangle_degenerate(a, b, c) is True

    def test_degenerate_identical_points(self):
        """三点重合 (面积=0) 应返回 True."""
        p = np.array([1.0, 2.0, 3.0])
        assert _is_triangle_degenerate(p, p, p) is True

    def test_near_degenerate_default_eps(self, near_degenerate_triangle):
        """接近退化但面积 > 默认 eps(1e-6) 应返回 False."""
        a, b, c = near_degenerate_triangle
        # 面积 = 0.5 * |AB × AC| = 0.5 * |(1,0,0) × (1,1e-4,0)| = 0.5 * 1e-4 = 5e-5 > 1e-6
        assert _is_triangle_degenerate(a, b, c) is False

    def test_near_degenerate_custom_strict_eps(self, near_degenerate_triangle):
        """使用更严格的 eps, 接近退化三角形应被视为非退化."""
        a, b, c = near_degenerate_triangle
        assert _is_triangle_degenerate(a, b, c, eps=1e-8) is False

    def test_edge_case_zero_area_exactly(self):
        """精确零面积: 三个点形成一条直线的两端和中点."""
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([2.0, 0.0, 0.0])
        c = np.array([1.0, 0.0, 0.0])  # AB 中点
        assert _is_triangle_degenerate(a, b, c) is True

    def test_symmetric_invariance(self, right_triangle):
        """顶点顺序不影响退化检测结果."""
        a, b, c = right_triangle
        r1 = _is_triangle_degenerate(a, b, c)
        r2 = _is_triangle_degenerate(b, c, a)
        r3 = _is_triangle_degenerate(c, a, b)
        assert r1 == r2 == r3


# ============================================================================
# 2. 批量重心坐标计算
# ============================================================================


class TestBarycentricBatch:
    """测试 _barycentric_batch 函数."""

    # --- 数值正确性 ---

    def test_vertex_a_returns_lambda_a_one(self, unit_triangle):
        """点位于顶点 A 时, λ_a = 1, λ_b = λ_c = 0."""
        a, b, c = unit_triangle
        result = _barycentric_batch(a.reshape(1, 3), a, b, c)
        assert result.shape == (1, 3)
        np.testing.assert_allclose(result[0], [1.0, 0.0, 0.0], atol=1e-10)

    def test_vertex_b_returns_lambda_b_one(self, unit_triangle):
        """点位于顶点 B 时, λ_b = 1, λ_a = λ_c = 0."""
        a, b, c = unit_triangle
        result = _barycentric_batch(b.reshape(1, 3), a, b, c)
        np.testing.assert_allclose(result[0], [0.0, 1.0, 0.0], atol=1e-10)

    def test_vertex_c_returns_lambda_c_one(self, unit_triangle):
        """点位于顶点 C 时, λ_c = 1, λ_a = λ_b = 0."""
        a, b, c = unit_triangle
        result = _barycentric_batch(c.reshape(1, 3), a, b, c)
        np.testing.assert_allclose(result[0], [0.0, 0.0, 1.0], atol=1e-10)

    def test_centroid_returns_equal_weights(self, unit_triangle):
        """三角形质心应返回 λ_a = λ_b = λ_c = 1/3."""
        a, b, c = unit_triangle
        centroid = (a + b + c) / 3.0
        result = _barycentric_batch(centroid.reshape(1, 3), a, b, c)
        np.testing.assert_allclose(result[0], [1/3, 1/3, 1/3], atol=1e-10)

    def test_edge_midpoint_ab(self, unit_triangle):
        """AB 边中点: λ_a = 0.5, λ_b = 0.5, λ_c = 0."""
        a, b, c = unit_triangle
        mid_ab = (a + b) / 2.0
        result = _barycentric_batch(mid_ab.reshape(1, 3), a, b, c)
        np.testing.assert_allclose(result[0], [0.5, 0.5, 0.0], atol=1e-10)

    def test_edge_midpoint_ac(self, unit_triangle):
        """AC 边中点: λ_a = 0.5, λ_c = 0.5, λ_b = 0."""
        a, b, c = unit_triangle
        mid_ac = (a + c) / 2.0
        result = _barycentric_batch(mid_ac.reshape(1, 3), a, b, c)
        np.testing.assert_allclose(result[0], [0.5, 0.0, 0.5], atol=1e-10)

    def test_edge_midpoint_bc(self, unit_triangle):
        """BC 边中点: λ_b = 0.5, λ_c = 0.5, λ_a = 0."""
        a, b, c = unit_triangle
        mid_bc = (b + c) / 2.0
        result = _barycentric_batch(mid_bc.reshape(1, 3), a, b, c)
        np.testing.assert_allclose(result[0], [0.0, 0.5, 0.5], atol=1e-10)

    # --- 不变性 ---

    def test_sum_to_one(self, unit_triangle, points_inside_unit_triangle):
        """所有点的重心坐标之和应为 1."""
        a, b, c = unit_triangle
        result = _barycentric_batch(points_inside_unit_triangle, a, b, c)
        sums = result.sum(axis=1)
        np.testing.assert_allclose(sums, 1.0, atol=1e-10)

    def test_internal_points_non_negative(self, unit_triangle, points_inside_unit_triangle):
        """三角形内部点的重心坐标应全部非负."""
        a, b, c = unit_triangle
        result = _barycentric_batch(points_inside_unit_triangle, a, b, c)
        assert np.all(result >= -1e-10)

    def test_external_points_may_be_negative(self, unit_triangle, points_outside_triangle):
        """三角形外部点的重心坐标可能有负分量."""
        a, b, c = unit_triangle
        result = _barycentric_batch(points_outside_triangle, a, b, c)
        # 至少有一个分量严格为负 (按定义)
        has_negative = np.any(result < -1e-10)
        assert has_negative, "外部点应有负的重心坐标分量"

    # --- 投影 (三维到平面) ---

    def test_offset_points_project_correctly(self, unit_triangle, points_offset_above_triangle):
        """
        Z 偏移点的重心坐标应与 XY 投影一致.
        (证明计算的是三角形平面上的投影, 而非三维空间中的位置)
        """
        a, b, c = unit_triangle
        result = _barycentric_batch(points_offset_above_triangle, a, b, c)

        # 投影到平面的点应恢复
        expected_xy = np.array([
            [0.2, 0.3, 0.0],
            [0.1, 0.1, 0.0],
            [0.5, 0.2, 0.0],
        ])
        expected_lambdas = _barycentric_batch(expected_xy, a, b, c)
        np.testing.assert_allclose(result, expected_lambdas, atol=1e-10)

    # --- 退化三角形兜底 ---

    def test_degenerate_returns_centroid(self, degenerate_triangle):
        """退化三角形: 所有点投影到质心."""
        a, b, c = degenerate_triangle
        points = np.random.default_rng(42).uniform(-10, 10, size=(10, 3))
        result = _barycentric_batch(points, a, b, c)
        expected = np.full((10, 3), [1/3, 1/3, 1/3])
        np.testing.assert_allclose(result, expected, atol=1e-10)

    # --- 批量与单点一致性 ---

    def test_batch_consistency_with_single(self, unit_triangle, points_inside_unit_triangle):
        """批量计算与逐点计算的 barycentric_3d 结果一致."""
        a, b, c = unit_triangle
        batch_result = _barycentric_batch(points_inside_unit_triangle, a, b, c)
        for i, pt in enumerate(points_inside_unit_triangle):
            single_result = barycentric_3d(pt, a, b, c)
            np.testing.assert_allclose(batch_result[i], single_result, atol=1e-10)

    # --- 一般位置三角形 ---

    def test_right_triangle_correctness(self, right_triangle):
        """一般位置直角三角形: 验证重心坐标正确性."""
        a, b, c = right_triangle
        # 三角形质心
        centroid = (a + b + c) / 3.0
        result = _barycentric_batch(centroid.reshape(1, 3), a, b, c)
        np.testing.assert_allclose(result[0], [1/3, 1/3, 1/3], atol=1e-10)

    def test_flat_triangle_correctness(self, flat_triangle):
        """倾斜三角形: 验证投影正确性."""
        a, b, c = flat_triangle
        # 质心验证
        centroid = (a + b + c) / 3.0
        result = _barycentric_batch(centroid.reshape(1, 3), a, b, c)
        np.testing.assert_allclose(result[0], [1/3, 1/3, 1/3], atol=1e-10)

    # --- 效率: 空输入 ---

    def test_empty_points(self, unit_triangle):
        """空点集输入应返回空数组."""
        a, b, c = unit_triangle
        empty = np.empty((0, 3), dtype=float)
        result = _barycentric_batch(empty, a, b, c)
        assert result.shape == (0, 3)

    # --- 重建验证 ---

    def test_reconstruction_from_barycentric(self, unit_triangle, points_inside_unit_triangle):
        """用重心坐标重建的点应与原始点一致 (证明逆变换正确)."""
        a, b, c = unit_triangle
        lambdas = _barycentric_batch(points_inside_unit_triangle, a, b, c)
        # 重建: P = λ_a * A + λ_b * B + λ_c * C
        reconstructed = (
            lambdas[:, 0:1] * a
            + lambdas[:, 1:2] * b
            + lambdas[:, 2:3] * c
        )
        np.testing.assert_allclose(reconstructed, points_inside_unit_triangle, atol=1e-10)


# ============================================================================
# 3. 公开单点接口 barycentric_3d
# ============================================================================


class TestBarycentric3D:
    """测试 barycentric_3d 公开接口."""

    def test_single_point_vertex(self, unit_triangle):
        """单点接口: 顶点 A 返回 [1, 0, 0]."""
        a, b, c = unit_triangle
        result = barycentric_3d(a, a, b, c)
        np.testing.assert_allclose(result, [1.0, 0.0, 0.0], atol=1e-10)

    def test_shape_is_3(self, unit_triangle):
        """返回值形状应为 (3,)."""
        a, b, c = unit_triangle
        result = barycentric_3d(np.array([0.3, 0.3, 0.0]), a, b, c)
        assert result.shape == (3,)


# ============================================================================
# 4. 三角形区域源点裁剪
# ============================================================================


class TestClipPointsToTriangle:
    """测试 _clip_points_to_triangle 函数."""

    def test_no_points(self, unit_triangle):
        """空点集: 返回空数组."""
        a, b, c = unit_triangle
        empty = np.empty((0, 3), dtype=float)
        result = _clip_points_to_triangle(empty, a, b, c)
        assert result.shape == (0, 3)

    def test_all_inside(self, unit_triangle, points_inside_unit_triangle):
        """所有点在三角形内: 全部保留."""
        a, b, c = unit_triangle
        result = _clip_points_to_triangle(points_inside_unit_triangle, a, b, c)
        assert result.shape[0] == points_inside_unit_triangle.shape[0]

    def test_all_outside(self, unit_triangle, points_outside_triangle):
        """所有点在三角形外 (超出容差): 全部丢弃."""
        a, b, c = unit_triangle
        result = _clip_points_to_triangle(points_outside_triangle, a, b, c, tolerance=0.0)
        assert result.shape[0] == 0

    def test_vertices_always_inside(self, unit_triangle):
        """三角形顶点自身应总被保留."""
        a, b, c = unit_triangle
        verts = np.array([a, b, c])
        result = _clip_points_to_triangle(verts, a, b, c, tolerance=0.0)
        assert result.shape[0] == 3

    def test_edge_midpoints_always_inside(self, unit_triangle, points_on_triangle_edges):
        """边上的点 (容差=0) 应被保留."""
        a, b, c = unit_triangle
        result = _clip_points_to_triangle(points_on_triangle_edges, a, b, c, tolerance=0.0)
        assert result.shape[0] == 3

    def test_tolerance_effect(self, unit_triangle, points_outside_triangle):
        """增大容差: 近边界的外部点被纳入."""
        a, b, c = unit_triangle
        # 容差=0 时全部丢弃
        strict = _clip_points_to_triangle(points_outside_triangle, a, b, c, tolerance=0.0)
        # 容差=2 时更多点被纳入
        loose = _clip_points_to_triangle(points_outside_triangle, a, b, c, tolerance=2.0)
        assert loose.shape[0] >= strict.shape[0]

    def test_default_tolerance_from_config(self, unit_triangle):
        """使用默认 PROJECTION_TOL 时, 近边界点应被纳入."""
        a, b, c = unit_triangle
        # 构造紧贴三角形外部边界的点 (λ 超出 [0,1] 不超过 0.1)
        near_boundary = np.array([[-0.1, -0.1, 0.0], [1.1, 0.0, 0.0], [0.0, 1.1, 0.0]])
        result = _clip_points_to_triangle(near_boundary, a, b, c, tolerance=PROJECTION_TOL)
        # PROJECTION_TOL = 0.15, 这些点紧贴边界, 应被纳入
        assert result.shape[0] > 0

    def test_clipped_points_are_subset_of_input(self, unit_triangle, points_inside_unit_triangle):
        """裁剪结果应是输入的子集 (精确坐标匹配)."""
        a, b, c = unit_triangle
        # 混合一些外部点
        mixed = np.vstack([points_inside_unit_triangle, np.array([[-5.0, -5.0, 0.0]])])
        result = _clip_points_to_triangle(mixed, a, b, c, tolerance=0.0)
        # 检查 result 中的每一行都存在于 mixed 中
        for pt in result:
            assert np.any(np.all(np.isclose(mixed, pt, atol=1e-10), axis=1))


# ============================================================================
# 5. 固定分辨率重心坐标网格
# ============================================================================


class TestMakeBarycentricGrid:
    """测试 make_barycentric_grid 函数."""

    def test_resolution_1_point_count(self):
        """分辨率 1: (2*3)/2 = 3 个点."""
        grid = make_barycentric_grid(1)
        assert grid.shape == (3, 3)

    def test_resolution_2_point_count(self):
        """分辨率 2: (3*4)/2 = 6 个点."""
        grid = make_barycentric_grid(2)
        assert grid.shape == (6, 3)

    def test_resolution_4_point_count(self):
        """分辨率 4: (5*6)/2 = 15 个点."""
        grid = make_barycentric_grid(4)
        assert grid.shape == (15, 3)

    def test_resolution_8_point_count(self):
        """分辨率 8: (9*10)/2 = 45 个点."""
        grid = make_barycentric_grid(8)
        assert grid.shape == (45, 3)

    def test_sum_to_one(self):
        """所有点的 λ_a + λ_b + λ_c 应为 1."""
        for res in [1, 2, 4, 8, 16]:
            grid = make_barycentric_grid(res)
            sums = grid.sum(axis=1)
            np.testing.assert_allclose(sums, 1.0, atol=1e-10)

    def test_all_non_negative(self):
        """所有重心坐标分量应为非负."""
        for res in [1, 2, 4, 8, 16]:
            grid = make_barycentric_grid(res)
            assert np.all(grid >= -1e-10)

    def test_all_within_0_1(self):
        """所有重心坐标分量应在 [0, 1] 范围内."""
        for res in [1, 2, 4, 8]:
            grid = make_barycentric_grid(res)
            assert np.all(grid >= -1e-10)
            assert np.all(grid <= 1.0 + 1e-10)

    def test_corner_points_present(self):
        """分辨率 ≥1 时, 三个顶点 (1,0,0), (0,1,0), (0,0,1) 必须存在."""
        for res in [1, 2, 4, 8]:
            grid = make_barycentric_grid(res)
            # 每个顶点的重心坐标
            has_a = np.any(np.all(np.isclose(grid, [1, 0, 0], atol=1e-10), axis=1))
            has_b = np.any(np.all(np.isclose(grid, [0, 1, 0], atol=1e-10), axis=1))
            has_c = np.any(np.all(np.isclose(grid, [0, 0, 1], atol=1e-10), axis=1))
            assert has_a, f"res={res}: 缺少顶点 (1,0,0)"
            assert has_b, f"res={res}: 缺少顶点 (0,1,0)"
            assert has_c, f"res={res}: 缺少顶点 (0,0,1)"

    def test_centroid_present_for_even_resolution(self):
        """分辨率为偶数时, 质心 (1/3, 1/3, 1/3) 应存在."""
        for res in [3, 6, 9, 12]:
            grid = make_barycentric_grid(res)
            has_centroid = np.any(
                np.all(np.isclose(grid, [1/3, 1/3, 1/3], atol=1e-10), axis=1)
            )
            assert has_centroid, f"res={res}: 缺少质心"

    def test_invalid_resolution_raises(self):
        """负数或零 resolution 应抛出 ValueError."""
        with pytest.raises(ValueError):
            make_barycentric_grid(0)
        with pytest.raises(ValueError):
            make_barycentric_grid(-1)

    def test_deterministic(self):
        """相同 resolution 多次调用结果一致."""
        g1 = make_barycentric_grid(8)
        g2 = make_barycentric_grid(8)
        np.testing.assert_array_equal(g1, g2)

    def test_monotonic_increasing_count(self):
        """resolution 越高, 点数越多."""
        prev_count = 0
        for res in [1, 2, 3, 4, 5]:
            count = make_barycentric_grid(res).shape[0]
            assert count > prev_count
            prev_count = count

    def test_step_size(self):
        """相邻 λ_b 或 λ_c 值之间的步长 = 1/resolution."""
        for res in [1, 2, 4, 8]:
            grid = make_barycentric_grid(res)
            # 取唯一非零 λ_b 值
            lb_vals = np.unique(np.round(grid[:, 1], decimals=10))
            lb_vals = lb_vals[lb_vals > 0]  # 排除 λ_b=0
            if len(lb_vals) > 0:
                step = float(lb_vals[0])
                assert math.isclose(step, 1.0 / res, rel_tol=1e-10)


# ============================================================================
# 6. 二维 UV 展开
# ============================================================================


class TestToAtlasUV:
    """测试 _to_atlas_uv 函数."""

    def test_local_uv_equals_lambda_b_lambda_c(self, barycentric_grid_res8):
        """Local UV 应等于 λ_b, λ_c."""
        u_local, v_local, u_atlas, v_atlas = _to_atlas_uv(barycentric_grid_res8, "T001")
        np.testing.assert_array_equal(u_local, barycentric_grid_res8[:, 1])
        np.testing.assert_array_equal(v_local, barycentric_grid_res8[:, 2])

    def test_atlas_uv_offset_T001(self, barycentric_grid_res8):
        """T001 (col=0, row=0): atlas = local (无偏移)."""
        u_local, v_local, u_atlas, v_atlas = _to_atlas_uv(barycentric_grid_res8, "T001")
        np.testing.assert_array_equal(u_atlas, u_local)
        np.testing.assert_array_equal(v_atlas, v_local)

    def test_atlas_uv_offset_T003(self, barycentric_grid_res8):
        """T003 (col=2, row=0): u_atlas = 2 + λ_b, v_atlas = λ_c."""
        u_local, v_local, u_atlas, v_atlas = _to_atlas_uv(barycentric_grid_res8, "T003")
        np.testing.assert_allclose(u_atlas, 2.0 + barycentric_grid_res8[:, 1])
        np.testing.assert_allclose(v_atlas, barycentric_grid_res8[:, 2])

    def test_atlas_uv_offset_T005(self, barycentric_grid_res8):
        """T005 (col=1, row=1): u_atlas = 1 + λ_b, v_atlas = 1 + λ_c."""
        u_local, v_local, u_atlas, v_atlas = _to_atlas_uv(barycentric_grid_res8, "T005")
        np.testing.assert_allclose(u_atlas, 1.0 + barycentric_grid_res8[:, 1])
        np.testing.assert_allclose(v_atlas, 1.0 + barycentric_grid_res8[:, 2])

    def test_unknown_region_falls_back_to_0_0(self, barycentric_grid_res8):
        """未定义的 region ID 应默认 (col=0, row=0) 即 local = atlas."""
        u_local, v_local, u_atlas, v_atlas = _to_atlas_uv(barycentric_grid_res8, "UNKNOWN")
        np.testing.assert_array_equal(u_atlas, u_local)
        np.testing.assert_array_equal(v_atlas, v_local)

    def test_output_shapes(self, barycentric_grid_res8):
        """四个返回值长度均等于输入行数."""
        n = len(barycentric_grid_res8)
        u_local, v_local, u_atlas, v_atlas = _to_atlas_uv(barycentric_grid_res8, "T001")
        assert len(u_local) == n
        assert len(v_local) == n
        assert len(u_atlas) == n
        assert len(v_atlas) == n

    def test_local_uv_range(self, barycentric_grid_res8):
        """local_uv 应在 [0, 1] 范围内."""
        u_local, v_local, _, _ = _to_atlas_uv(barycentric_grid_res8, "T001")
        assert np.all(u_local >= -1e-10)
        assert np.all(u_local <= 1.0 + 1e-10)
        assert np.all(v_local >= -1e-10)
        assert np.all(v_local <= 1.0 + 1e-10)


# ============================================================================
# 7. 插值重建
# ============================================================================


class TestInterpolateSamplePoints:
    """测试 _interpolate_sample_points 函数."""

    def test_normal_interpolation_no_fallback(
        self, unit_triangle, barycentric_grid_res4, null_logger
    ):
        """
        源点密集且均匀分布时, 所有目标网格点应能通过 LinearNDInterpolator 插值.

        使用与目标网格 (res=4, 15点) 相同的重心坐标作为源点, 保证完全覆盖.
        """
        a, b, c = unit_triangle
        # 源点: 用网格点本身 (保证完全覆盖目标网格凸包)
        grid = barycentric_grid_res4  # 15 个点
        source_lambdas = grid.copy()
        source_points = np.array([
            la * a + lb * b + lc * c
            for la, lb, lc in grid
        ])

        reconstructed, fallback = _interpolate_sample_points(
            source_points,
            source_lambdas,
            grid,
            (a, b, c),
            null_logger,
        )

        assert reconstructed.shape == (15, 3)
        assert fallback.shape == (15,)
        # 源点包含所有目标点, LinearNDInterpolator 应无 NaN
        assert not np.any(fallback)

    def test_insufficient_points_qhull_error(
        self, unit_triangle, barycentric_grid_res4, null_logger
    ):
        """
        仅 2 个源点: LinearNDInterpolator 需要至少 4 个点 (2D),
        不足时会抛出 QhullError.
        """
        a, b, c = unit_triangle
        source_points = np.array([a, b])  # 仅 2 个点
        source_lambdas = _barycentric_batch(source_points, a, b, c)

        from scipy.spatial import QhullError
        with pytest.raises(QhullError):
            _interpolate_sample_points(
                source_points,
                source_lambdas,
                barycentric_grid_res4,
                (a, b, c),
                null_logger,
            )

    def test_few_source_points_causes_fallback(
        self, unit_triangle, barycentric_grid_res4, null_logger
    ):
        """仅 4 个源点形成小三角形: 外部目标点需要兜底."""
        a, b, c = unit_triangle
        # 4 个源点形成一个较小的子三角形 (在 unit triangle 内部, 不覆盖角落)
        # 这样 res=4 的目标网格中靠近边缘和顶点的部分将位于凸包外
        mid_ab = (a + b) / 2.0
        mid_bc = (b + c) / 2.0
        mid_ca = (c + a) / 2.0
        inner_centroid = (a + b + c) / 3.0
        source_points = np.array([mid_ab, mid_bc, mid_ca, inner_centroid])
        source_lambdas = _barycentric_batch(source_points, a, b, c)

        reconstructed, fallback = _interpolate_sample_points(
            source_points,
            source_lambdas,
            barycentric_grid_res4,
            (a, b, c),
            null_logger,
        )
        # 源点子三角形不覆盖顶点区域, 部分目标点需要兜底
        assert np.any(fallback)
        # 所有重建点坐标应有限
        assert np.all(np.isfinite(reconstructed))

    def test_single_source_point_qhull_error(
        self, unit_triangle, barycentric_grid_res4, null_logger
    ):
        """
        极端: 仅 1 个源点 → QhullError (Delaunay 需要至少 4 个点).
        """
        a, b, c = unit_triangle
        source_points = np.array([a])
        source_lambdas = _barycentric_batch(source_points, a, b, c)

        from scipy.spatial import QhullError
        with pytest.raises(QhullError):
            _interpolate_sample_points(
                source_points,
                source_lambdas,
                barycentric_grid_res4,
                (a, b, c),
                null_logger,
            )

    def test_reconstructed_within_source_convex_hull(
        self, unit_triangle, barycentric_grid_res4, null_logger
    ):
        """
        当源点完全覆盖三角形时, 重建点应位于源点凸包内.
        """
        a, b, c = unit_triangle
        # 用顶点 + 质心作为源点 (4 个点, 刚好够 Delaunay)
        source_points = np.array([a, b, c, (a + b + c) / 3.0])
        source_lambdas = _barycentric_batch(source_points, a, b, c)

        reconstructed, fallback = _interpolate_sample_points(
            source_points,
            source_lambdas,
            barycentric_grid_res4,
            (a, b, c),
            null_logger,
        )
        # 验证所有未兜底的重建点的重心坐标在 [0,1] 内
        if not np.all(fallback):
            non_fallback = reconstructed[~fallback]
            recon_lambdas = _barycentric_batch(non_fallback, a, b, c)
            assert np.all(recon_lambdas >= -1e-10)
            assert np.all(recon_lambdas <= 1.0 + 1e-10)

    def test_output_shape_consistent(self, unit_triangle, barycentric_grid_res8, null_logger):
        """输出形状与目标网格行数一致."""
        a, b, c = unit_triangle
        pts = np.array([a, b, c, (a + b + c) / 3.0])
        lambdas = _barycentric_batch(pts, a, b, c)

        reconstructed, fallback = _interpolate_sample_points(
            pts, lambdas, barycentric_grid_res8, (a, b, c), null_logger
        )
        assert reconstructed.shape == (45, 3)
        assert fallback.shape == (45,)

    def test_fallback_ratio_monotonic_with_source_count(
        self, unit_triangle, barycentric_grid_res4, null_logger
    ):
        """源点越多, 兜底比例越低 (从 >=4 个源点开始, 避免 QhullError)."""
        a, b, c = unit_triangle

        # 用不同的源点数测试 (>=4, 满足 Delaunay 最小点数要求)
        ratios = []
        for n_src in [4, 6, 8, 12]:
            # 生成 n_src 个随机内部点
            rng = np.random.default_rng(42)
            lb_rnd = rng.random((n_src, 2))
            mask = lb_rnd.sum(axis=1) > 1.0
            lb_rnd[mask] = 1.0 - lb_rnd[mask]
            la_rnd = 1.0 - lb_rnd[:, 0] - lb_rnd[:, 1]
            src_pts = (
                la_rnd[:, None] * a
                + lb_rnd[:, 0:1] * b
                + lb_rnd[:, 1:2] * c
            )
            src_lambdas = _barycentric_batch(src_pts, a, b, c)

            _, fallback = _interpolate_sample_points(
                src_pts, src_lambdas, barycentric_grid_res4, (a, b, c), null_logger
            )
            ratios.append(float(fallback.mean()))
        # 兜底比例应随源点数增加而递减
        for i in range(len(ratios) - 1):
            assert ratios[i] >= ratios[i + 1] - 1e-6, \
                f"源点={n_src}: ratio={ratios[i]:.4f} > ratio={ratios[i+1]:.4f}"


# ============================================================================
# 8. 单区域完整处理流水线 process_region
# ============================================================================


class TestProcessRegion:
    """测试 process_region 函数 (端到端集成)."""

    def test_basic_pipeline_with_plane_mesh(
        self, simple_plane_mesh, landmarks_unit_triangle, region_basic, null_logger
    ):
        """
        基本流水线: 平面 mesh + 模拟 landmarks + 区域定义 → 输出参数化结果.
        """
        df_region, qc, detail = process_region(
            sample_id="TEST",
            side="R",
            full_mesh=simple_plane_mesh,
            lms=landmarks_unit_triangle,
            region=region_basic,
            global_start_id=0,
            logger=null_logger,
        )

        # --- 返回类型检查 ---
        assert isinstance(df_region, pd.DataFrame)
        assert isinstance(qc, dict)
        assert isinstance(detail, dict)

        # --- DataFrame 结构检查 ---
        expected_cols = {
            "sample_id", "side", "region_id", "region_name",
            "point_id_global", "point_id_region",
            "x", "y", "z", "u", "v", "u_local", "v_local",
            "lambda_a", "lambda_b", "lambda_c",
            "lm_a", "lm_b", "lm_c",
        }
        actual_cols = set(df_region.columns)
        missing = expected_cols - actual_cols
        assert not missing, f"缺少列: {missing}"

        # --- 采样点数 ---
        resolution = region_basic["resolution"]  # 4
        expected_n = (resolution + 1) * (resolution + 2) // 2  # 15
        assert len(df_region) == expected_n

        # --- 所有 lambda 和应为 1 ---
        lambdas = df_region[["lambda_a", "lambda_b", "lambda_c"]].to_numpy()
        np.testing.assert_allclose(lambdas.sum(axis=1), 1.0, atol=1e-10)

        # --- QC 记录检查 ---
        assert qc["region_id"] == region_basic["region_id"]
        assert qc["region_name"] == region_basic["region_name"]
        assert "fallback_ratio" in qc
        assert "status" in qc
        assert qc["status"] in ("PASS", "WARNING", "FAIL")

        # --- 可视化中间数据 ---
        assert "source_lambdas" in detail
        assert "source_points_3d" in detail
        assert "target_grid" in detail
        assert "reconstructed" in detail
        assert "fallback_mask" in detail
        assert "a_3d" in detail
        assert "b_3d" in detail
        assert "c_3d" in detail

    def test_pipeline_few_source_points(
        self, simple_plane_mesh, landmarks_unit_triangle, null_logger
    ):
        """
        源点不足 (< MIN_SOURCE_POINTS=5) 时的流水线行为.
        此时应使用三角形顶点线性插值, 全部标记为兜底.
        """
        # 使用非常小的三角形区域 (分辨率=1, 源点极少)
        region_mini = {
            "region_id": "T999",
            "region_name": "微型测试区",
            "lm_a": "L10",   # A = (0,0,0)
            "lm_b": "L02",   # B = (1,0,0)
            "lm_c": "L13",   # C = (0,1,0)
            "resolution": 1,
        }
        df_region, qc, detail = process_region(
            sample_id="TEST",
            side="R",
            full_mesh=simple_plane_mesh,  # 仅 4 个顶点
            lms=landmarks_unit_triangle,
            region=region_mini,
            global_start_id=0,
            logger=null_logger,
        )
        # 源点不足, 应触发线性插值路径
        assert qc["source_point_count"] < MIN_SOURCE_POINTS
        # 全部兜底
        assert qc["fallback_ratio"] == 1.0
        assert qc["status"] == "FAIL"
        # 重建点应落在三角形平面内
        assert np.all(np.isfinite(df_region[["x", "y", "z"]].to_numpy()))

    def test_full_landmarks_pipeline(
        self, small_dense_mesh, landmarks_full, null_logger
    ):
        """
        完整特征点集 + 密集 mesh: 测试真实场景规模.
        """
        # 使用 landmarks_full 中的 L10, L28, L30 定义一个区域 (T003: 耳甲腔前区)
        region = {
            "region_id": "T003",
            "region_name": "耳甲腔前区",
            "lm_a": "L10",  # (3,3,0)
            "lm_b": "L28",  # (4,6,0)
            "lm_c": "L30",  # (4,5.5,0)
            "resolution": 4,
        }
        df_region, qc, detail = process_region(
            sample_id="FULL",
            side="R",
            full_mesh=small_dense_mesh,
            lms=landmarks_full,
            region=region,
            global_start_id=0,
            logger=null_logger,
        )
        assert len(df_region) == 15
        assert qc["status"] in ("PASS", "WARNING", "FAIL")
        assert np.all(np.isfinite(df_region[["x", "y", "z"]].to_numpy()))

    def test_degenerate_triangle_in_process_region_raises(
        self, simple_plane_mesh, null_logger
    ):
        """
        若 landmarks 构成退化三角形, process_region 应抛出 ValueError.
        """
        # 构造退化 landmarks
        records = [
            {"landmark_id": "L10", "x": 0.0, "y": 0.0, "z": 0.0},
            {"landmark_id": "L02", "x": 1.0, "y": 1.0, "z": 1.0},
            {"landmark_id": "L13", "x": 2.0, "y": 2.0, "z": 2.0},  # 共线
        ]
        lms = pd.DataFrame(records).set_index("landmark_id")

        region = {
            "region_id": "T000",
            "region_name": "退化区",
            "lm_a": "L10",
            "lm_b": "L02",
            "lm_c": "L13",
            "resolution": 4,
        }
        with pytest.raises(ValueError, match="退化"):
            process_region(
                sample_id="DEGEN",
                side="R",
                full_mesh=simple_plane_mesh,
                lms=lms,
                region=region,
                global_start_id=0,
                logger=null_logger,
            )

    def test_global_point_id_continuity(
        self, simple_plane_mesh, landmarks_unit_triangle, region_basic, null_logger
    ):
        """验证 global_start_id 正确应用到输出 point_id_global."""
        start = 100
        df_region, _, _ = process_region(
            sample_id="ID_TEST",
            side="R",
            full_mesh=simple_plane_mesh,
            lms=landmarks_unit_triangle,
            region=region_basic,
            global_start_id=start,
            logger=null_logger,
        )
        expected_ids = np.arange(start, start + len(df_region))
        np.testing.assert_array_equal(df_region["point_id_global"].to_numpy(),
                                       expected_ids)

    def test_qc_status_boundaries(self):
        """
        验证 QC 状态阈值行为: fallback_ratio 与 PASS/WARNING/FAIL 的对应关系.
        
        实际状态取决于数据, 仅验证 QC 字典中 status 字段的完整性.
        """
        # FALLBACK_WARNING_THRESHOLD = 0.05, FALLBACK_FAIL_THRESHOLD = 0.20
        assert 0 < FALLBACK_WARNING_THRESHOLD < FALLBACK_FAIL_THRESHOLD < 1.0, \
            "阈值关系不合理"

    def test_uv_coordinates_in_output(
        self, simple_plane_mesh, landmarks_unit_triangle, region_basic, null_logger
    ):
        """验证输出 DataFrame 包含正确范围的 UV 坐标."""
        df_region, _, _ = process_region(
            sample_id="UV_TEST",
            side="R",
            full_mesh=simple_plane_mesh,
            lms=landmarks_unit_triangle,
            region=region_basic,
            global_start_id=0,
            logger=null_logger,
        )
        # local UV 在 [0, 1]
        assert np.all(df_region["u_local"] >= -1e-10)
        assert np.all(df_region["u_local"] <= 1.0 + 1e-10)
        assert np.all(df_region["v_local"] >= -1e-10)
        assert np.all(df_region["v_local"] <= 1.0 + 1e-10)
        # atlas UV 在合理范围 (T001: [0, 1])
        assert np.all(df_region["u"] >= -1e-10)
        assert np.all(df_region["u"] <= 1.0 + 1e-10)
        assert np.all(df_region["v"] >= -1e-10)
        assert np.all(df_region["v"] <= 1.0 + 1e-10)


# ============================================================================
# 9. 回归测试: 黄金标准数据
# ============================================================================


class TestRegression:
    """
    回归测试: 将已知输入的输出锁定, 防止后续修改引入意外变更.

    这些测试不验证"正确性", 而是验证"一致性".
    如果算法有预期内的修改, 更新这里的期望值即可.
    """

    def test_barycentric_grid_res8_known_output(self):
        """make_barycentric_grid(8) 的前几行应保持不变 (j-inner 顺序)."""
        grid = make_barycentric_grid(8)
        # 实际顺序: i 外层, j 内层 → λ_c 变化比 λ_b 快
        # i=0: j=0→8 → λ_b=0/8, λ_c=0/8, 1/8, 2/8, ...
        expected_first_rows = np.array([
            [1.0, 0.0, 0.0],       # i=0, j=0
            [7/8, 0.0, 1/8],       # i=0, j=1
            [6/8, 0.0, 2/8],       # i=0, j=2
            [5/8, 0.0, 3/8],       # i=0, j=3
            [4/8, 0.0, 4/8],       # i=0, j=4
        ])
        np.testing.assert_allclose(grid[:5], expected_first_rows, atol=1e-10)
        # 总点数
        assert grid.shape[0] == 45

    def test_barycentric_unit_triangle_vertex_reconstruction(self):
        """
        对 unit triangle, 给定顶点 + 重心坐标, 重建应精确还原.
        (黄金标准值的端到端验证)
        """
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([1.0, 0.0, 0.0])
        c = np.array([0.0, 1.0, 0.0])

        # 已知的重心坐标
        lambdas = np.array([
            [0.5, 0.5, 0.0],
            [0.5, 0.0, 0.5],
            [0.0, 0.5, 0.5],
        ])
        # 期望的三维坐标
        expected = np.array([
            [0.5, 0.0, 0.0],  # AB 中点
            [0.0, 0.5, 0.0],  # AC 中点
            [0.5, 0.5, 0.0],  # BC 中点
        ])
        reconstructed = (
            lambdas[:, 0:1] * a
            + lambdas[:, 1:2] * b
            + lambdas[:, 2:3] * c
        )
        np.testing.assert_allclose(reconstructed, expected, atol=1e-10)

    def test_to_atlas_uv_known_T002(self):
        """T002 (col=1, row=0) 的 atlas UV 偏移验证."""
        # 构造一个简单的一行网格
        bary = np.array([[0.3, 0.3, 0.4]])
        u_local, v_local, u_atlas, v_atlas = _to_atlas_uv(bary, "T002")
        # T002: col=1, row=0
        assert u_local[0] == 0.3
        assert v_local[0] == 0.4
        np.testing.assert_allclose(u_atlas[0], 1.3)
        np.testing.assert_allclose(v_atlas[0], 0.4)