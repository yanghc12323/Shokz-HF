# Remesh QC 可视化与 Region Table 优化策略

> 更新时间：2026-07-10  
> 适用范围：W2 真实样本 QC、region table 诊断、W3 前置筛选

## 1. 当前问题

历史 r8 `T013_L/T076_L/T077_L/T078_L` 在 13 个 region 上的 QC 可视化汇总为：

```text
T013_L: PASS=2, WARNING=10, FAIL=1
T076_L: PASS=2, WARNING=11, FAIL=0
T077_L: PASS=3, WARNING=10, FAIL=0
T078_L: PASS=3, WARNING=9,  FAIL=1
共同 PASS region: 0
完全无 FAIL region: 12
```

当前主线已经切换到 `resolution=24`，并且 `region_table.csv` 已将 T009 调整为 `L18-L29-L30`。最新四样本 r24 结果为：

```text
raw:
T013_L: PASS=2, WARNING=11, FAIL=0
T076_L: PASS=1, WARNING=11, FAIL=1
T077_L: PASS=1, WARNING=12, FAIL=0
T078_L: PASS=2, WARNING=11, FAIL=0

repaired:
T013_L: PASS=13, WARNING=0, FAIL=0
T076_L: PASS=12, WARNING=0, FAIL=1
T077_L: PASS=13, WARNING=0, FAIL=0
T078_L: PASS=13, WARNING=0, FAIL=0
```

这说明 r24 主流程和 WARNING-only repair 已经能在四个真实样本上运行。W3 需要多个样本在同一个 region 上同时 `PASS`，否则该 region 的 PCA 输入矩阵会包含 NaN 或样本数不足。

## 2. 主要证据

T009 是本轮 region table 更新的重点。旧版 T009 使用 `L28-L29-L30` 时在 T078 上出现 raw FAIL；新版改为 `L18-L29-L30` 后，四样本 T009 均不再 FAIL：

```text
T013_L / T009:
raw unmapped_count = 1 / 325
raw status = WARNING
repaired status = PASS

T076_L / T009:
raw unmapped_count = 4 / 325
raw status = WARNING
repaired status = PASS

T077_L / T009:
raw unmapped_count = 51 / 325
raw status = WARNING
repaired status = PASS

T078_L / T009:
raw unmapped_count = 6 / 325
raw status = WARNING
repaired status = PASS
```

这说明 T009 的新版特征点组合有效解决了持续 FAIL 问题。但 `T077_L / T009` 仍有 51 个 raw unmapped 点，说明它虽然可被 repaired 层补齐并导出 PLY，但是否适合进入 W3 PCA 仍需要后续明确策略。

当前唯一剩余 FAIL 是：

```text
T076_L / T008:
patch_face_count = 1323
raw unmapped_count = 113 / 325
raw status = FAIL
repaired status = FAIL
```

因此下一轮 region table 诊断重点应从 T009 转移到 `T076_L / T008`。

## 3. 三样本参考结果

如果暂时排除 T078，只看 `T013_L/T076_L/T077_L`，多数 region 至少可以完成可检查输出：

```text
当前 raw 无 FAIL region:
T001, T002, T003, T004, T005, T006, T007, T009, T010, T011, T012, T013

当前仍有 FAIL 的 region:
T008，仅出现在 T076_L
```

这些结果说明 remesh 主流程本身是可工作的，但 region table 仍需要被更多样本挑战。

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

当前已经按 mentor 讨论结果切换到 `resolution=24`。如果 patch 没有覆盖完整标准三角域，提高 `resolution` 会暴露更多 unmapped 点，因此必须配套 raw/repaired 两层 QC。

当前策略是：r24 raw QC 用于判断原始映射质量；r24 repaired 输出用于尽可能导出完整 PLY。

QC 可视化也保持 raw/repaired 两层：

```text
output/qc_visualizations_r24/raw/<sample_tag>/<region_id>_qc.png
output/qc_visualizations_r24/raw/qc_visualization_summary.csv
output/qc_visualizations_r24/repaired/<sample_tag>/<region_id>_qc.png
output/qc_visualizations_r24/repaired/qc_visualization_summary.csv
```

raw 图用于看未修补前的真实问题；repaired 图用于确认补点是否消除了角点或局部 unmapped。repaired 图中的橙色三角表示已修补点，红色叉号表示仍未修补点。

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
1. 先看 output/qc_visualizations_r24/raw/T076_L/T008_qc.png 和 repaired/T076_L/T008_qc.png
2. 再看 output/qc_visualizations_r24/raw/T077_L/T009_qc.png 和 repaired/T077_L/T009_qc.png
3. 对比四个样本的 T009 repaired 图，确认新版 T009 是否形态连续、无明显插值异常
```

原因：T009 已从 FAIL 改善为 WARNING/PASS；当前唯一真正失败的是 `T076_L / T008`。T009 后续重点不是“是否能跑通”，而是“repaired 后是否足够可信用于 W3”。

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

## 10. W3 候选 Region 标准

一个 region 进入 W3 候选池的最低标准：

```text
所有目标样本该 region 均 status == PASS
所有目标样本 unmapped_count == 0
所有目标样本 degenerate_faces == 0
所有目标样本 sample_point_count == expected_point_count
```

短期目标：

```text
先找到 3-5 个 region，在多个真实样本上全部 PASS。
```

这些 region 可以作为 W3 第一版 PCA 的输入。

## 11. 文档维护

每次发生以下变化后，需要同步更新 README 和本文档：

1. 新增真实样本。
2. 修改 `region_table.csv`。
3. QC 结果发生明显变化。
4. 新增或修改可视化/诊断脚本。
5. W3 候选 region 发生变化。
