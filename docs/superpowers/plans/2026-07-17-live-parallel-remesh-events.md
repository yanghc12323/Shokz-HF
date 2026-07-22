# 并行 Remesh 实时事件转发 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在并行 Remesh/QC 执行期间，将每个样本的 region 事件实时显示到桌面运行监控页面。

**Architecture:** 每个并行子进程保留私有 JSONL 事件文件；管线协调线程维护每个文件的读取偏移量，在等待 future 时轮询并转发新增完整行到现有主事件流。完成回收时用同一偏移量补读，避免重复。

**Tech Stack:** Python 3、JSON Lines、`concurrent.futures.wait`、现有 PySide6 监控轮询。

## Global Constraints

- 子进程不得并发写主 `events.jsonl`。
- 串行 CLI 行为不变。
- 不改动 region QC 判定、输出文件或并行工作数量。
- 不构建 EXE。

---

### Task 1: 私有事件日志的增量读取器

**Files:**
- Modify: `ear_param/pipeline.py`
- Test: `tests/test_pipeline.py`

- [x] 写失败测试：日志写入 `region_started` 后、样本 future 尚未完成时，协调 reporter 已收到事件。
- [x] 写失败测试：同一私有日志的已读事件不会重复转发，完成后的 EOF 补读能转发最后一行。
- [x] 实现私有 JSONL 增量读取器，维护每样本字节偏移量和未完成尾行缓冲。
- [x] 运行定向测试。

### Task 2: 管线等待循环集成

**Files:**
- Modify: `ear_param/pipeline.py`
- Test: `tests/test_pipeline.py`

- [x] 将 `wait(... FIRST_COMPLETED)` 改为有限超时等待；每次超时和完成后均轮询所有 in-flight 私有日志。
- [x] 将原完成后的事件回放改为同一读取器的 EOF 补读，确保不会重复。
- [x] 运行并行 Remesh/QC、region 事件与桌面事件回归测试。

### Task 3: 文档与最终验证

**Files:**
- Modify: `docs/桌面工程软件使用说明.md`
- Test: `tests/test_pipeline.py`, `tests/test_desktop_ui_flow.py`

- [x] 记录并行模式下 region 进度实时更新与暂停边界。
- [x] 运行完整相关测试集合、Python 编译与 `git diff --check`。
