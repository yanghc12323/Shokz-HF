# Remesh QC 可视化与 Region Table 优化策略

> 更新时间：2026-07-11  
> 适用范围：W2 真实样本 QC、region table 诊断、W3 前置筛选

## 1. 当前问题

历史 r8 `T013_L/T076_L/T077_L/T078_L` 在旧版 region table 上的 QC 可视化曾显示：

```text
T013_L: PASS=2, WARNING=10, FAIL=1
T076_L: PASS=2, WARNING=11, FAIL=0
T077_L: PASS=3, WARNING=10, FAIL=0
T078_L: PASS=3, WARNING=9,  FAIL=1
共同 PASS region: 0
完全无 FAIL region: 12
```

当前主线已经切换到 `resolution=24`，并且 `region_table.csv` 已扩展为 15 个 region。最新输出不再写死在本文档中，应以当前 CSV 和 QC 图为准。

当前新增了第三层 `salvaged` 输出：它不会改变 raw/repaired 的判定，只对满足安全限制的 raw FAIL 尝试少量补点，并把结果单独标记。W3 需要多个样本在同一个 region 上同时具备可信输入，否则该 region 的 PCA 输入矩阵会包含 NaN 或样本数不足。

## 2. 主要证据

当前失败诊断优先看：

```text
output/parameterized_points_r24/raw/<sample>_L_remesh_qc.csv
output/parameterized_points_r24/repaired/<sample>_L_remesh_qc.csv
output/parameterized_points_r24/salvaged/<sample>_L_remesh_qc.csv
output/qc_visualizations_r24/raw/<sample>_L/<region_id>_qc.png
output/qc_visualizations_r24/repaired/<sample>_L/<region_id>_qc.png
output/qc_visualizations_r24/salvaged/<sample>_L/<region_id>_qc.png
```

诊断顺序建议是：先看 raw 图确认真实问题；再看 repaired 图确认 WARNING 补点；最后看 salvaged 图判断 raw FAIL 是否只是少量边界丢点，还是仍属于边界路径或 patch 提取失败。

## 3. 三样本参考结果

如果暂时排除特殊或明显异常样本，多数 region 至少可以完成可检查输出。当前不要再依赖旧版静态统计表，而应每次补充样本或修改 region table 后重新生成 summary：

```powershell
python scripts/visualize_remesh_qc.py --samples T013_L T049_L T076_L T077_L T078_L T088_L T094_L T097_L T099_L
```

这些结果说明 remesh 主流程本身是可工作的，但 region table 和边界路径策略仍需要被更多样本挑战。

## 4. 当前判断

当前问题不应首先理解为“采样精度不足”。

更合理的判断是：

1. 部分 region 的 landmark 三角组合不稳定。
2. mesh 上的最短路径 boundary 可能抄近路，不等于解剖边界。
3. 三条 boundary path 可能围出过窄、错误或退化 patch。
4. patch component 选择策略还缺少面积、覆盖率、闭环质量等约束。

因此，不建议优先提高 `resolution` 或放宽 QC。

## 5. 为什么不优先调高 Resolution

`resolution` 控制标准三角域中的 template 点数：

```text
resolution=12 -> 91 points
resolution=16 -> 153 points
resolution=24 -> 325 points
```

当前已经按 mentor 讨论结果切换到 `resolution=24`。如果 patch 没有覆盖完整标准三角域，提高 `resolution` 会暴露更多 unmapped 点，因此必须配套 raw/repaired/salvaged 三层 QC。

当前策略是：r24 raw QC 用于判断原始映射质量；r24 repaired 输出用于处理 raw WARNING；r24 salvaged 输出用于观察一部分 raw FAIL 是否可被保守抢救。

QC 可视化保持 raw/repaired/salvaged 三层：

```text
output/qc_visualizations_r24/raw/<sample_tag>/<region_id>_qc.png
output/qc_visualizations_r24/raw/qc_visualization_summary.csv
output/qc_visualizations_r24/repaired/<sample_tag>/<region_id>_qc.png
output/qc_visualizations_r24/repaired/qc_visualization_summary.csv
output/qc_visualizations_r24/salvaged/<sample_tag>/<region_id>_qc.png
output/qc_visualizations_r24/salvaged/qc_visualization_summary.csv
```

raw 图用于看未修补前的真实问题；repaired 图用于确认 raw WARNING 补点是否消除了角点或局部 unmapped；salvaged 图用于确认 raw FAIL 在安全限制内是否能被抢救。橙色三角表示已修补点，红色叉号表示仍未修补点。

salvaged summary 中重点看三列：

```text
salvage_attempted：是否真正尝试了 raw FAIL 抢救
salvage_accepted：抢救后是否无 unmapped 且可导出
salvage_rejection_reason：未尝试或未接受的原因
```

当前默认限制是 `--max_salvage_unmapped_ratio 0.35`。如果 `degenerate_faces > 0`，不做 salvage；如果 raw unmapped 比例超过 0.35，也不做 salvage。

## 6. 推荐处理顺序

当前采用以下优先级：

```text
T0：继续用真实样本验证 region table 的稳定性。
T1：调整 region table，尝试增加 region、拆分 region、替换不稳定 landmark 组合。
T2：确认 region 定义合理后，再调整边界路径策略、patch 选择策略或其它参数。
```

## 7. T0：更多样本验证

新增样本后，先运行 W2 remesh：

```powershell
python scripts/parameterize_ear_remesh.py --sample_id T013 --side L --mesh data/clean_mesh/T013_L.ply --landmarks data/landmarks/T013_L_landmarks.csv
python scripts/parameterize_ear_remesh.py --sample_id T076 --side L --mesh data/clean_mesh/T076_L.ply --landmarks data/landmarks/T076_L_landmarks.csv
python scripts/parameterize_ear_remesh.py --sample_id T077 --side L --mesh data/clean_mesh/T077_L.ply --landmarks data/landmarks/T077_L_landmarks.csv
python scripts/parameterize_ear_remesh.py --sample_id T078 --side L --mesh data/clean_mesh/T078_L.ply --landmarks data/landmarks/T078_L_landmarks.csv
```

然后生成 QC 可视化：

```powershell
python scripts/visualize_remesh_qc.py --samples T013_L T076_L T077_L T078_L
```

汇总文件：

```text
output/qc_visualizations_r24/raw/qc_visualization_summary.csv
output/qc_visualizations_r24/repaired/qc_visualization_summary.csv
```

优先查看每个 region 在所有样本中的 PASS 数、FAIL 数和 unmapped 数。

## 8. T1：调整 Region Table

当前优先诊断顺序：

```text
1. 先按 raw summary 找出 FAIL 频率最高的 region。
2. 再按 salvaged summary 查看 salvage_rejection_reason。
3. 对反复出现在相邻 region 中的失败边，优先考虑周一加入共享 M 控制点。
4. 对 degenerate_faces > 0 的样本单独诊断，不靠补点硬救。
```

原因：当前 region table 和样本数量已经更新，旧的单一区域结论不再作为最新依据。新的判断应以 raw/repaired/salvaged 三层 QC 文件和图像为准。

调整方向：

1. 替换不稳定 landmark 组合。
2. 将过大、过窄或跨褶皱的三角区拆成更小 region。
3. 增加候选 region，但不要删除历史结果；通过 QC 选择稳定 region。
4. 避免三点过近、近共线或跨越明显耳部褶皱。
5. 每次调整后先跑重点 region，不要一开始全量跑。

重点 region 的快速诊断命令：

```powershell
python scripts/visualize_remesh_qc.py --samples T013_L T076_L T077_L T078_L --region_ids T008 T009
```

## 9. T2：参数或算法策略调整

只有在 region table 合理后，才建议进入 T2。

可能方向：

1. 对 boundary path 增加约束，避免最短路径抄近路。
2. 引入人工中间控制点，让边界沿解剖路径走。
3. patch component 选择时加入面积和 UV 覆盖率判断。
4. 增加 boundary 自交、重叠、过短检测。
5. 在多个候选 patch 中选择 mapped coverage 更高者。

不建议的方向：

1. 直接放宽 QC。
2. 对 unmapped 点强行插值后进入 PCA。
3. 在当前失败状态下提高 `resolution`。

## 10. 整耳焊接 QC 与 W3 准入

当前 W3 不再按独立 region 直接拼接。15 个 salvaged region 会先通过全局模板构成固定 whole-ear，再做共享边 QC。先建立不可改写的 baseline：

```powershell
python scripts/build_whole_ear.py --input_dir output/parameterized_points_r24/salvaged --regions config/region_table.csv --out_dir output/whole_ear_r24/salvaged
```

baseline 的整耳进入共享边修补评估前，必须满足：

```text
15 个 salvaged region 均 PASS
4453 个全局顶点完整且有限
8640 个全局面无退化、无重复
17 条共享边 weld status 均 PASS
weld summary 中 pca_ready == True
```

焊接 QC 必须区分 `replacement` 与 `conflict`：mapped 边界替换 salvaged 插值边界属于可追溯修正；两侧都没有 mapped 权威点且彼此差异较大才属于未解决冲突。当前重点诊断：

```text
T049_L / L13-L17: FAIL, max_conflict=2.1694 mm
T094_L / L20-L21: WARNING, max_conflict=0.4135 mm
T097_L / L21-L29: WARNING, max_conflict=0.3098 mm
```

对 baseline 的 WARNING，只允许在两侧 raw region 非 FAIL、无退化面、冲突为 1--2 个连续 repaired-only 点且两侧存在可信锚点时做共享边耦合修补。修补点通过锚点插值后投影回原始 mesh，并同步写入两侧 region 的对应边界点。运行：

```powershell
python scripts/build_whole_ear.py --input_dir output/parameterized_points_r24/salvaged --regions config/region_table.csv --mesh_dir data/clean_mesh --enable_edge_repair --out_dir output/whole_ear_r24/weld_repaired
```

T094_L 与 T097_L 分别完成一个满足条件的单点修补，修补后冲突均为 0，`weld_repaired` 层由 6 PASS、2 WARNING、1 FAIL 变为 8 PASS/PCA_READY、1 FAIL。`T049_L` 仍因 L13-L17 相邻 raw FAIL 而被拒绝自动修补。请同时查看 `<sample>_edge_repair_qc.csv` 和 weld QC 图：青色点表示已成功修补，紫色点表示被拒绝的候选点。

最终只有 `weld_repaired` 中 `pca_ready=True` 且 `aligned_weld_repaired/alignment_qc_summary.csv` 为 PASS 的样本进入 W3。当前共有 8 个样本已完成刚体对齐。详细字段见 `docs/whole_ear_weld_and_alignment.md`。

## 11. 文档维护

每次发生以下变化后，需要同步更新 README 和本文档：

1. 新增真实样本。
2. 修改 `region_table.csv`。
3. QC 结果发生明显变化。
4. 新增或修改可视化/诊断脚本。
5. W3 候选 region 发生变化。
6. 共享边修补规则、修补审计或整耳候选样本发生变化。
