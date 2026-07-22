# 并行 Remesh QC 独立汇总 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让独立样本的 Remesh 与 QC 在桌面端安全并行，并保留标准 QC 汇总产物与 CLI 默认兼容性。

**Architecture:** QC CLI 将图像输出与 summary 输出解耦：图像仍落在标准 QC 目录，而每个并发样本使用私有 summary 根目录。管线工作线程完成 Remesh 后直接完成该样本 QC；协调线程在所有任务完成后合并私有 summary 为既有标准 CSV。

**Tech Stack:** Python 3、pandas、`concurrent.futures.ThreadPoolExecutor`、现有 CLI。

## Global Constraints

- 未传新 CLI 参数时，`visualize_remesh_qc.py` 的输出路径与行为保持不变。
- 样本 QC 状态、QC 判定算法、PNG 输出路径和标准汇总文件名不得改变。
- 仅桌面传入并行数 `0/1/2/4` 时启用内部并发；CLI 默认仍为 1。
- 不构建 EXE。

---

### Task 1: QC CLI 私有 summary 输出

**Files:**
- Modify: `scripts/visualize_remesh_qc.py`
- Test: `tests/test_visualize_remesh_qc.py`

- [x] 写失败测试：传 `--summary-dir` 时，三份 summary 写入该目录，而 PNG 仍在 `--out-dir`。
- [x] 在解析器增加可选 `--summary-dir`；未提供时回退为 `--out-dir`。
- [x] 将 summary 的父目录创建与三份 CSV 写入改为该变量。
- [x] 运行定向测试，确认默认调用仍写入 `--out-dir`。

### Task 2: 并行工作单元与标准汇总合并

**Files:**
- Modify: `ear_param/pipeline.py`
- Test: `tests/test_pipeline.py`

- [x] 写失败测试：并行模式下两个 QC 调用重叠、每个读取自己的私有 summary，且汇总回标准路径。
- [x] 将 QC 调用封装回样本工作单元；仅在 `parallel_workers > 1` 时为它构造 `<qc_dir>/_sample_summaries/<sample_tag>`。
- [x] 在 `build_subprocess_stages` 传递 `--summary-dir` 并从私有 salvaged summary 计算该样本状态。
- [x] 增加协调线程的 summary 合并回调：按 sample_tag、region_id 稳定排序，写入三个既有标准文件。
- [x] 在 Remesh/QC 全部完成后调用合并；合并失败作为运行错误，防止留下不完整审计产物。
- [x] 运行定向测试，确认样本记录顺序和耗时记录均保持正确。

### Task 3: 文档与回归验证

**Files:**
- Modify: `docs/桌面工程软件使用说明.md`
- Test: `tests/test_pipeline.py`, `tests/test_visualize_remesh_qc.py`, `tests/test_desktop_cli_parity.py`, `tests/test_desktop_ui_flow.py`

- [x] 记录并行 QC 的私有汇总和最终标准汇总语义，以及暂停/取消边界。
- [x] 运行涉及桌面参数、QC CLI、管线、manifest 与结果复核的完整测试集合。
- [x] 运行 `python -m compileall -q desktop_app ear_param scripts/run_full_pipeline.py` 与 `git diff --check`。
