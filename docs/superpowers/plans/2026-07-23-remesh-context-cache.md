# Remesh 上下文缓存 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为单一样本的 54 个 region 复用邻接图、KDTree/landmark 吸附、最短路径和 r24 模板，并保持分析结果不变。

**Architecture:** 在 `ear_param.remesh` 定义 `RemeshContext` 和构建函数。`build_region_remesh` 接受可选 context；参数化脚本为每个样本创建一次并传入全部 region 调用。

**Tech Stack:** Python、NumPy、SciPy sparse/cKDTree、pytest。

## Global Constraints

- 不改变 Dijkstra、UV、修复、QC 或输出顺序。
- 不写死 54、35 或 resolution 24；从传入 region table 动态生成缓存。
- 未传 context 的 `build_region_remesh(mesh, landmarks, region)` 保持既有行为。
- 不提交用户现有 PLY/landmark 删除或无关文件。

---

### Task 1: 缓存 API 与等价回归测试

**Files:**
- Modify: `ear_param/remesh.py`
- Modify: `tests/test_remesh.py`

**Interfaces:**
- Produces: `prepare_remesh_context(mesh, landmarks, regions) -> RemeshContext`。
- Consumes: `build_region_remesh(mesh, landmarks, region, context: RemeshContext | None = None)`。

- [ ] 写入失败测试：两条方向相反、相同 resolution 的 region 共用 template 和缓存路径。
- [ ] 运行 `pytest -q tests/test_remesh.py -k remesh_context`，预期因 API 缺失失败。
- [ ] 实现 `RemeshContext(adjacency, snapped_landmarks, path_cache, templates)`；构建函数一次性计算动态提取的 landmark 和 resolution。
- [ ] 路径缓存以排序后的顶点对保存；反向请求返回反向列表。
- [ ] 运行 `pytest -q tests/test_remesh.py`，预期通过。
- [ ] 提交：`git add ear_param/remesh.py tests/test_remesh.py && git commit -m "perf: cache per-sample remesh context"`。

### Task 2: 接入正式单样本循环

**Files:**
- Modify: `scripts/parameterize_ear_remesh.py`
- Modify: `tests/test_parameterize_ear_remesh.py`

**Interfaces:**
- Consumes: `prepare_remesh_context(mesh, landmarks, regions.to_dict("records"))`。
- Produces: 每个样本只创建一次 context，全部 region 复用。

- [ ] 写入失败测试：monkeypatch `prepare_remesh_context` 并断言一次 CLI 参数化只调用一次。
- [ ] 运行 `pytest -q tests/test_parameterize_ear_remesh.py -k context`，预期失败。
- [ ] 在 region 循环前创建 `regions_records` 和 context，并传入 `build_region_remesh`。
- [ ] 运行 `pytest -q tests/test_parameterize_ear_remesh.py tests/test_remesh.py` 与 `pytest -q tests/test_pipeline.py -k "parallel_remesh or subprocess_remesh"`。
- [ ] 提交：`git add scripts/parameterize_ear_remesh.py tests/test_parameterize_ear_remesh.py && git commit -m "perf: reuse remesh context across regions"`。

### Task 3: 集成验收

**Files:**
- Verify only: `tests/test_remesh.py`, `tests/test_pipeline.py`, `tests/test_parameterize_ear_remesh.py`

- [ ] 用相同样本分别运行无 context 与 context 的单样本参数化，比较 raw/repaired/salvaged CSV 的数值和 QC 状态。
- [ ] 运行 `git diff --check` 和主项目 `pytest -q tests`。
- [ ] 仅在验证完成后推送 `master`。
