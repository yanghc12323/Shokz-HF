# 桌面工程软件交付收尾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 将当前桌面分支补全为可安装、可运行、可恢复、且与既有 CLI 结果可验收对照的 Windows 本机离线软件。

**Architecture:** UI 保持 PySide6 + PyVista/VTK，运行继续由 `RunController` 启动既有 `scripts/run_full_pipeline.py`。所有桌面运行都写入项目内隔离 attempt；专家重跑只能读取已校验的父 attempt 产物，并将新结果写入新的 attempt。

**Tech Stack:** Python 3.14、PySide6、PyVista/VTK、pytest、pytest-qt、PyInstaller。

## Global Constraints

- Windows 10/11、本机离线、中文界面。
- 同一输入和参数下，桌面运行必须与 CLI 结果一致。
- 不修改原始输入；项目管理输入副本、运行记录和结果。
- 一次仅运行一个流程；暂停/取消只在 pipeline 安全检查点生效。
- 不提交或删除现有用户改动，尤其是未提交的 `config/edge_control_points.csv` 删除状态。

---

### Task 1: 先冻结并验证 CLI 基线

**Files:**
- Modify: `tests/test_desktop_cli_parity.py`
- Modify: `README.md`

- [ ] 建立最小成对网格/地标 fixture，同时分别以 CLI 参数和 `RunController.last_command` 运行。
- [ ] 断言两个 `manifest.json` 的 `parameters`、`pipeline_batch_summary.csv` 状态列和关键输出相同。
- [ ] 单独验证无 `--event-log`、`--control-path` 参数时原 CLI 默认行为保持不变。
- [ ] Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/test_pipeline.py tests/test_desktop_cli_parity.py -q`
- [ ] Commit: `test: verify desktop CLI parity`

### Task 2: 补齐默认向导的真实操作闭环

**Files:**
- Modify: `desktop_app/ui/project_wizard.py`
- Modify: `desktop_app/ui/main_window.py`
- Modify: `desktop_app/ui/run_monitor.py`
- Test: `tests/test_desktop_ui_flow.py`

- [ ] 将项目目录、网格目录、地标目录、区域表和边界控制点的选择控件接到 `ProjectService.create` / `import_inputs`。
- [ ] 导入完成后自动运行 `ValidationService.validate`，并仅在无 ERROR 时开放参数页与“一键分析”。
- [ ] 将参数页值转成 `RunOptions`，启动 `RunController.start`，轮询 JSONL 事件并刷新监控页。
- [ ] 终态完成时索引 attempt 并自动载入 `ResultWorkbench`。
- [ ] Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/test_desktop_ui_flow.py tests/test_desktop_run_controller.py -q`
- [ ] Commit: `feat: complete guided desktop workflow`

### Task 3: 完成专家模式和真实阶段恢复

**Files:**
- Create: `desktop_app/ui/expert_mode.py`
- Modify: `desktop_app/recovery_service.py`
- Modify: `desktop_app/run_controller.py`
- Modify: `desktop_app/ui/main_window.py`
- Test: `tests/test_desktop_recovery_service.py`

- [ ] 为 Weld、对齐、PCA 分别生成仅引用父 artifacts 内已验证目录的命令。
- [ ] 写入 `run_history.json` 与 recovery manifest：父 attempt、源阶段、源 manifest SHA-256、源路径。
- [ ] 专家模式只显示 `RecoveryService.plan` 返回的阶段；恢复失败不得改写父 artifacts。
- [ ] Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/test_desktop_recovery_service.py tests/test_desktop_run_controller.py -q`
- [ ] Commit: `feat: execute expert stage recovery`

### Task 4: 完成结果复核可用性与视觉验收

**Files:**
- Modify: `desktop_app/ui/result_workbench.py`
- Modify: `desktop_app/viewers/mesh_viewer.py`
- Test: `tests/test_desktop_result_workbench.py`

- [ ] 用实际 attempt fixture 验证 raw/repaired/salvaged/整耳/平均耳的启用条件、切换和证据链接。
- [ ] 对 region/QC 不存在、PCA 未纳入、无图形环境分别显示明确中文原因。
- [ ] 在真实 Windows 图形会话人工检查旋转、缩放、平移与区域高亮；离屏测试只验证安全降级。
- [ ] Commit: `feat: finalize result review workbench`

### Task 5: 打包、安装与最终验收

**Files:**
- Create: `desktop_app/__main__.py`
- Create: `scripts/build_desktop.ps1`
- Modify: `README.md`
- Create: `docs/桌面工程软件使用说明.md`

- [ ] `python -m desktop_app` 创建应用、主窗口并进入 Qt 事件循环。
- [ ] PyInstaller 打包字体、PyVista、VTK、pyvistaqt 与入口模块，生成 Windows EXE。
- [ ] 在干净项目目录中执行“新建→导入→校验→分析→复核→导出”，再验证取消和恢复。
- [ ] Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests -q`，再运行 `powershell -ExecutionPolicy Bypass -File scripts/build_desktop.ps1`。
- [ ] Commit: `feat: package desktop engineering app`

## Release Gate

- [ ] CLI/desktop parity 测试通过。
- [ ] 完整 pytest 全绿。
- [ ] 真实图形会话三维交互通过。
- [ ] EXE 可双击启动，并完成一次最小项目端到端运行。
- [ ] 主分支合入前处理或恢复 `config/edge_control_points.csv` 的删除状态。
