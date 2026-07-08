# 非 Remesh 代码是否删除的客观评估

> 当前日期：2026-07-08  
> 结论摘要：暂时不建议直接删除旧参数化代码。它们不是当前论文式 remesh 主线的核心，但仍有测试、模拟数据、历史对照和回退价值。建议先标记为 legacy，等 W3 PCA 流程稳定后再分阶段清理。

## 1. 当前主线是什么

当前项目主线已经切换为论文式 patch-based remesh：

```text
mesh + landmarks + region_table
-> boundary paths
-> patch extraction
-> harmonic UV
-> fixed 2D subdivision
-> 3D remesh points
-> fixed remesh faces
-> region features
-> QC
-> PLY patch
```

主线文件：

```text
ear_param/remesh.py
scripts/parameterize_ear_remesh.py
tests/test_remesh.py
docs/remesh_usage_w2.md
docs/w3_pca_average_ear_technical_route.md
```

## 2. 与论文式 remesh 关系较弱的旧代码

以下文件来自早期“参数化采样点云/KDTree 插值”路线，不是当前论文式 remesh 的核心：

```text
ear_param/core.py
ear_param/run.py
ear_param/synthetic.py
ear_param/visualization.py
scripts/parameterize_ear.py
scripts/validate_data.py
tests/test_core.py
tests/conftest.py
```

它们现在的状态不是“完全无用”，而是“非当前主线”。原因如下：

| 文件 | 当前价值 | 删除风险 |
|---|---|---|
| `ear_param/core.py` | 保留早期参数化采样算法，可作为论文式 remesh 的对照方案 | 删除会导致旧 CLI 和 `tests/test_core.py` 大量失败 |
| `ear_param/run.py` | 旧流程编排入口，支持模拟/单样本旧参数化 | 删除会破坏 `scripts/parameterize_ear.py` |
| `ear_param/synthetic.py` | 生成模拟耳数据，仍可用于无真实数据时做 smoke test | 删除后失去快速造数能力 |
| `ear_param/visualization.py` | 旧流程可视化，部分思路可迁移到 remesh QC 可视化 | 删除后失去历史可视化工具 |
| `scripts/parameterize_ear.py` | 旧命令行入口 | 删除前需要确认无人再使用旧流程 |
| `scripts/validate_data.py` | 数据检查脚本，可能仍有复用价值 | 需先确认是否与真实数据接入流程相关 |
| `tests/test_core.py` | 旧流程回归测试 | 删除会降低历史算法保护，但可减少维护成本 |

## 3. 是否可以认为它们是无用代码

不能简单认为是无用代码。

更客观的分类是：

```text
当前主线必需：remesh.py、parameterize_ear_remesh.py、test_remesh.py
当前主线辅助：io_utils.py、config.py、requirements.txt、region_table.csv
历史/legacy：core.py、run.py、synthetic.py、visualization.py、parameterize_ear.py、test_core.py
```

旧代码“不再代表最新技术路线”，但仍可能有三个作用：

1. **历史对照**：可以证明为什么从参数化点云/KDTree 插值转向论文式 remesh。
2. **模拟数据**：真实数据不足时，`synthetic.py` 仍可快速生成测试样本。
3. **回退机制**：如果某些真实样本 remesh 暂时失败，旧流程可作为诊断对照。

## 4. 当前是否建议删除

当前不建议删除。

理由：

1. W3 PCA 还没实现，过早清理会增加风险。
2. 旧测试仍在保护项目基本数值工具。
3. 旧代码与当前 remesh 主线共存，没有阻塞当前使用。
4. README 可以明确主线入口，避免误用旧流程，而不需要马上删除。

## 5. 推荐清理策略

### 阶段 A：现在

做法：

- 保留旧代码。
- README 明确声明旧流程是 legacy。
- 新工作只围绕 remesh 主线开发。

### 阶段 B：W3 PCA 完成后

做法：

- 确认 `ear_param/pca_average.py`、`scripts/build_average_ear.py`、W3 测试稳定。
- 确认真实样本批处理不再依赖旧流程。
- 将旧代码移动到 `legacy/` 或保留但从 README 主线中移除。

### 阶段 C：项目交付前

做法：

- 若导师/团队确认只交付 remesh + PCA 路线，可删除旧流程。
- 删除时必须同步删除或迁移相关测试。
- 删除后运行全量测试，确保主线仍通过。

## 6. 如果要删除，建议删除顺序

不要一次性删除全部旧代码。建议顺序：

1. 先停用旧 CLI：`scripts/parameterize_ear.py`。
2. 再迁移或删除旧测试：`tests/test_core.py`。
3. 再删除旧流程编排：`ear_param/run.py`。
4. 最后评估 `core.py/synthetic.py/visualization.py` 中是否有可复用函数。

如果希望保留历史但让结构更干净，可以移动到：

```text
legacy/
```

但移动文件会改变 import 路径，需要同步调整或删除旧测试。

## 7. 当前推荐结论

当前最稳妥的判断是：

```text
旧代码不是当前主线，但不是马上可以安全删除的无用代码。
```

建议现在只做文档层面的“legacy 标记”，不要删除。等 W3 PCA 平均耳流程完成、测试通过、真实数据批处理稳定后，再做一次专门的清理任务。
