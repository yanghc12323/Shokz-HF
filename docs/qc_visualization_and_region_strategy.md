# Remesh QC 可视化与 Region Table 优化策略

> 更新时间：2026-07-08  
> 适用范围：W2 真实样本 QC、region table 诊断、W3 前置筛选

## 1. 当前问题

当前 T076_L 与 T077_L 在 12 个 region 上的 QC 结果为：

```text
T076_L: PASS=2, WARNING=8, FAIL=2
T077_L: PASS=1, WARNING=10, FAIL=1
共同 PASS region: 0
```

这说明当前还不能直接进入 W3 正式 PCA。W3 需要多个样本在同一个 region 上同时 `PASS`，否则该 region 的 PCA 输入矩阵会包含 NaN 或样本数不足。

## 2. 主要证据

当前最严重的区域是：

```text
T001: 两个样本都 FAIL，total unmapped = 31
T008: T076 FAIL，T077 WARNING，total unmapped = 28
```

典型例子：

```text
T076_L / T008:
sample_point_count = 45
unmapped_count = 24
patch_face_count = 252
status = FAIL
```

QC 可视化显示，失败区域的实际 UV patch 不能覆盖完整标准三角域，大量 template 点落在 patch UV 覆盖之外。

## 3. 当前判断

当前问题不应首先理解为“采样精度不足”。

更合理的判断是：

1. 部分 region 的 landmark 三角组合不稳定。
2. mesh 上的最短路径 boundary 可能抄近路，不等于解剖边界。
3. 三条 boundary path 可能围出过窄 patch。
4. patch component 选择策略还缺少面积、覆盖率、简单闭环等约束。

因此，不建议优先提高 `resolution` 或放宽 QC。

## 4. 为什么不优先调高 Resolution

`resolution` 控制标准三角域中的 template 点数：

```text
resolution=8  -> 45 points
resolution=12 -> 91 points
resolution=16 -> 153 points
```

如果当前 patch 没有覆盖完整标准三角域，提高 `resolution` 只会生成更多 template 点，通常会暴露更多 unmapped 点。它不能修复 patch 过窄或边界路径错误。

建议保持 `resolution=8`，先把 region 稳定性调好。

## 5. 推荐处理顺序

当前采用以下优先级：

```text
T0：用更多真实样本验证 region table 的稳定性。
T1：调整 region table，尝试增加 region、拆分 region、替换不稳定 landmark 组合。
T2：确认 region 定义合理后，再调整边界路径策略、patch 选择策略或其它参数。
```

## 6. T0：更多样本验证

新增样本后，先运行 W2 remesh：

```powershell
python scripts/parameterize_ear_remesh.py --sample_id T078 --side L --mesh data/clean_mesh/T078_L.ply --landmarks data/landmarks/T078_L_landmarks.csv
python scripts/parameterize_ear_remesh.py --sample_id T079 --side L --mesh data/clean_mesh/T079_L.ply --landmarks data/landmarks/T079_L_landmarks.csv
```

然后生成 QC 可视化：

```powershell
python scripts/visualize_remesh_qc.py --samples T076_L T077_L T078_L T079_L
```

汇总文件：

```text
output/qc_visualizations/qc_visualization_summary.csv
```

优先查看每个 region 在所有样本中的 PASS 数。

## 7. T1：调整 Region Table

优先处理高 unmapped 区域：

```text
T001
T008
```

调整方向：

1. 替换不稳定 landmark 组合。
2. 将过大的或过窄的三角区拆成更小 region。
3. 增加候选 region，但不要删除历史结果；通过 QC 选择稳定 region。
4. 避免三点过近、近共线或跨越明显褶皱。
5. 每次调整后只先跑重点 region，不要一开始全量跑。

重点 region 的快速诊断命令：

```powershell
python scripts/visualize_remesh_qc.py --samples T076_L T077_L --region_ids T001 T008
```

## 8. T2：参数或算法策略调整

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

## 9. W3 候选 Region 标准

一个 region 进入 W3 候选池的最低标准：

```text
所有目标样本该 region 均 status == PASS
所有目标样本 unmapped_count == 0
所有目标样本 degenerate_faces == 0
所有目标样本 sample_point_count == expected_point_count
```

短期目标：

```text
先找到 3-5 个 region，在 4 个真实样本上全部 PASS。
```

这些 region 可以作为 W3 第一版 PCA 的输入。

## 10. 文档维护

每次发生以下变化后，需要同步更新 README 和本文件：

1. 新增真实样本。
2. 修改 `region_table.csv`。
3. QC 结果发生明显变化。
4. 新增或修改可视化/诊断脚本。
5. W3 候选 region 发生变化。
