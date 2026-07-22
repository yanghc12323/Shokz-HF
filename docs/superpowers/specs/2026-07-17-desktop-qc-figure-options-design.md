# 桌面端 QC 图选项与结果复核可读性设计

## 目标

修复 Windows 构建出的 EXE 名称乱码；在桌面端运行参数页提供 Region QC PNG 生成档位；修复结果复核页白字白底问题。

## 决策

- PyInstaller 输出固定为 `EarEngineeringAnalysis.exe`，避免 PowerShell/源码编码影响文件名；应用窗口仍使用中文名称。
- 新增 `qc_figure_mode`：`all`、`repaired-fail`、`none`。
  - `all`：为 raw、repaired、salvaged 三层的每个 region 生成 PNG。
  - `repaired-fail`：只为修复后 QC 为 FAIL 的 region 生成 repaired PNG。
  - `none`：不生成任何 Region QC PNG。
- 所有模式都运行原有 Region QC 计算并写入 raw/repaired/salvaged QC CSV；门禁和后续 weld/PCA 输入完全不变。
- 桌面界面默认选择 `repaired-fail`，而 CLI 默认 `all`，因此不改变既有 CLI 的默认行为。
- 结果复核页明确指定侧栏文字、下拉框与输入框的深色前景和浅色背景。

## 数据流

`QComboBox` → `RunOptions.qc_figure_mode` → `RunController` 的 `--qc-figure-mode` → `run_full_pipeline.py` → `PipelineConfig.qc_figure_mode` → `visualize_remesh_qc.py --figure-mode`。

## 验收

1. 构建脚本使用 ASCII EXE 名称。
2. 三个桌面档位均可见并准确传递至 CLI。
3. `none` 和 `repaired-fail` 仍产生 QC 汇总 CSV，且 CLI 阶段状态不受影响。
4. 结果复核页可读控件使用深色文字。
