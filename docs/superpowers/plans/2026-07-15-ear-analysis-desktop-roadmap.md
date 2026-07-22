# 耳模型分析工程软件开发路线图

> 依据：[耳模型分析工程软件设计规格](../specs/2026-07-15-ear-analysis-desktop-design.md)

## 总原则

- 先稳定计算任务接口，再开发桌面界面；
- 现有 `ear_param` 算法保持唯一实现；
- 每个里程碑都必须产生可独立测试、可回归的交付物；
- 不修改 `data/` 和 `config/`；
- 不覆盖历史运行；
- 每次代码调整同步更新 README 和相关文档；
- 未经用户明确要求，不执行 Git commit。

## 里程碑

| 顺序 | 里程碑 | 独立交付物 | 前置依赖 |
|---:|---|---|---|
| 1 | 运行级输出隔离与 Manifest | `--output-root`、独立批次目录、`manifest.json`、兼容旧 CLI | 现有全流程 |
| 2 | 机器可读事件与计算 Worker | `events.jsonl`、阶段/样本/region 进度、开发/打包 Worker、取消协议 | 里程碑 1 |
| 3 | 桌面骨架与项目扫描 | PySide6 主窗口、工作区导航、项目打开、输入校验、历史批次发现 | 里程碑 2 |
| 4 | 批处理中心 | 任务配置、QProcess、实时进度、日志、安全取消、诊断重跑 | 里程碑 3 |
| 5 | QC 与三维查看 | Raw/Repaired/Salvaged/Weld 筛选、PNG 对照、PyVistaQt PLY 查看 | 里程碑 4 |
| 6 | 整耳、对齐与 PCA 工作区 | Weld/Alignment/PCA 结果解析、平均耳、PC 形态、scores、双路径对比 | 里程碑 5 |
| 7 | 汇报包与 Windows 交付 | HTML/XLSX 报告、PyInstaller onedir、端到端验收、使用文档 | 里程碑 6 |

## 验收顺序

每个里程碑依次执行：

1. 设计边界复核；
2. TDD 实现；
3. 定向测试；
4. 全量自动测试；
5. 代表性样本验证；
6. 文档同步；
7. 用户验收后进入下一里程碑。

## 当前执行计划

当前只执行里程碑 1，详细步骤见：

- [运行级输出隔离与 Manifest 实施计划](2026-07-15-run-scoped-pipeline-artifacts.md)

