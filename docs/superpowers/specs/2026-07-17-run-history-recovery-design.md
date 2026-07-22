# 历史运行记录与阶段恢复闭环设计

## 目标

让用户在桌面端选择项目历史中的失败或取消 attempt，查看状态和失败原因，并仅对完整性校验通过的上游产物启动单阶段恢复。

## 方案

- `RunHistoryService` 扫描 `<project>/runs/*/attempts/*/desktop_state.json`，并结合同级 `artifacts/manifest.json` 读取状态和错误原因。
- “运行记录”页显示逻辑运行、attempt、状态、失败原因和可恢复阶段；用户选中可恢复 attempt 后点击“进入专家恢复”。
- 专家模式复用已有 `RecoveryService.plan()`，因此只展示通过 manifest 路径完整性校验的阶段。
- 恢复启动后自动切至运行监控；恢复脚本不支持安全检查点，监控页禁用暂停和取消，防止作出无效承诺。

## 不变项

- 历史 attempt 和父产物只读；恢复必定创建子 attempt。
- 正常全流程 CLI 和既有输出目录布局不变。
