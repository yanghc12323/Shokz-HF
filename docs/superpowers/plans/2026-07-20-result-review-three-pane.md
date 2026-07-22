# 结果复核三分区布局 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将结果复核页改为左侧信息、右上 PCA Score、右下 3D 模型的工程软件布局，并消除重叠。

**Architecture:** `ResultWorkbench` 使用左侧可滚动信息栏和右侧 `QSplitter`；PCA Score 表放入右上独立卡片，现有 `MeshViewer` 放入右下独立卡片。数据加载逻辑保持原样，仅重组容器与尺寸策略。

**Tech Stack:** Python 3、PySide6、现有 `ResultWorkbench`、pytest-qt。

## Global Constraints

- 保留 PCA 摘要、PCA Score、样本选择、图层加载、region 高亮与文件夹入口。
- 不改变分析产物、PCA 数据读取或三维渲染算法。
- 不构建 EXE。

---

### Task 1: 右侧 PCA Score / 3D 分割布局

**Files:**
- Modify: `desktop_app/ui/result_workbench.py`
- Test: `tests/test_desktop_result_workbench.py`

- [x] 写失败测试：PCA Score 表属于右上面板，viewer 属于右下分割面板，左侧不含 PCA Score。
- [x] 用 `QScrollArea` 包裹左侧信息栏；用垂直 `QSplitter` 组合右上 Score 卡片与右下 Viewer 卡片。
- [x] 设置默认 42/58 比例和最小高度，保留现有对象属性与数据加载方法。
- [x] 运行定向界面测试。

### Task 2: 工程化视觉样式与回归

**Files:**
- Modify: `desktop_app/ui/main_window.py`
- Test: `tests/test_desktop_ui_flow.py`, `tests/test_desktop_result_workbench.py`

- [x] 写失败测试：新增右侧 Score/Viewer 面板具有独立卡片背景和可读文字样式。
- [x] 添加分割区、PCA Score、Viewer 标题和表格的样式规则。
- [x] 运行结果复核与主窗口样式回归测试。

### Task 3: 文档与最终验证

**Files:**
- Modify: `docs/桌面工程软件使用说明.md`
- Test: `tests/test_desktop_result_workbench.py`, `tests/test_desktop_ui_flow.py`

- [x] 描述结果复核三分区与 PCA Score 位置。
- [x] 运行完整相关测试、Python 编译和 `git diff --check`。
