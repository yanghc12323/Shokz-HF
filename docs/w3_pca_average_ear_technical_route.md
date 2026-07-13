# W3 PCA 与平均耳技术路线

> 面向对象：后续接手项目的 AI 或工程师
> 更新时间：2026-07-13
> 当前状态：整耳全局模板、焊接 QC、共享边耦合修补和刚体统一坐标系已实现；PCA 尚未实现

## 1. 当前上游状态

W2 已将每个样本划分为 15 个三角 region，每区在 resolution=24 下固定为 325 点和 576 面。正式下游采用 `salvaged` 层，并已进一步完成：

```text
15 个 region salvaged 输出
-> 全局模板合并共享角点和共享边
-> 4453 个唯一整耳顶点、8640 个固定面
-> 边界焊接 QC
-> L7/L13/L15/L26 刚体 Generalized Procrustes
-> aligned whole-ear PCA 输入
```

当前 whole-ear QC 分为不可改写的 baseline 与正式修补层：

```text
baseline salvaged: 6 PASS, 2 WARNING (T094_L, T097_L), 1 FAIL (T049_L)
weld_repaired PCA_READY:
T013_L, T076_L, T077_L, T078_L, T088_L, T094_L, T097_L, T099_L
FAIL: T049_L
```

`T094_L` 和 `T097_L` 仅在满足保守条件时由共享边锚点插值并投影回原始 mesh，分别把单点冲突从 0.4135 mm 和 0.3098 mm 修补为 0。`T049_L` 因相邻 T003 的 raw region FAIL 而被明确拒绝自动修补。当前 8 个 PCA_READY 样本已完成对齐。所有 `det(R)=1`，最大 mesh 边长保持误差约 `1.84e-14 mm`。这批数据可以用于实现和验证 PCA 流程，但样本量较小，暂不能代表稳定总体分布。

## 2. W3 唯一正式输入

W3 不再读取原始高密度 PLY，不重新寻找 landmark，也不重新 remesh、repair、salvage 或焊接。正式输入为：

```text
output/whole_ear_r24/aligned_weld_repaired/<sample>_aligned_whole_ear_points.csv
output/whole_ear_r24/aligned_weld_repaired/<sample>_aligned_whole_ear_faces.csv
output/whole_ear_r24/aligned_weld_repaired/alignment_qc_summary.csv
```

同时回查：

```text
output/whole_ear_r24/weld_repaired/<sample>_weld_qc_summary.csv
output/whole_ear_r24/weld_repaired/<sample>_edge_repair_qc.csv
```

样本准入条件：

```text
weld_repaired pca_ready == True
alignment input_layer == weld_repaired
alignment status == PASS
global_vertex_id 完整且唯一
x/y/z 全部有限
所有样本 global_vertex_id 序列完全相同
所有样本 global_v0/v1/v2 faces 完全相同
```

baseline 的 WARNING/FAIL 不通过放宽阈值自动进入 PCA。只有带有 `edge_repair_qc.csv` 审计记录、修补后整耳重新判为 PASS 的样本，才能从独立 `weld_repaired` 层进入 PCA。

## 3. PCA 数据矩阵

每个合格样本必须先按 `global_vertex_id` 升序排列：

```python
xyz = points[["x", "y", "z"]].to_numpy(dtype=float)  # (4453, 3)
vector = xyz.reshape(-1)                                # (13359,)
```

将 N 个样本堆叠：

```text
X.shape = (N, 13359)
```

不能依赖 CSV 原始行顺序，也不能重新生成 faces。

## 4. PCA 计算

建议使用 NumPy SVD，避免增加 scikit-learn 依赖：

```python
mean_vector = X.mean(axis=0)
X_centered = X - mean_vector
U, singular_values, Vt = np.linalg.svd(X_centered, full_matrices=False)
explained_variance = singular_values**2 / (N - 1)
explained_ratio = explained_variance / explained_variance.sum()
cumulative_ratio = np.cumsum(explained_ratio)
n_components_75 = int(np.searchsorted(cumulative_ratio, 0.75) + 1)
components = Vt[:n_components_75]
scores = X_centered @ components.T
```

`n_components_75` 是累计解释方差第一次达到或超过 75% 时的主成分数。由于当前 N=8，最多只能得到 N-1=7 个非零主成分，结果主要用于流程验证。

## 5. 平均耳

平均耳坐标直接来自：

```python
mean_points = mean_vector.reshape(4453, 3)
```

faces 必须复制任一合格样本的固定 `global_v0/v1/v2`，并在运行前验证所有样本 faces 完全一致：

```python
mesh = trimesh.Trimesh(
    vertices=mean_points,
    faces=global_faces,
    process=False,
)
```

这里不再按 region 拼接，也不再焊接；这些工作已经在上游完成。

## 6. 建议实现文件

```text
ear_param/pca_average.py
scripts/build_average_ear.py
tests/test_pca_average.py
```

建议命令：

```powershell
python scripts/build_average_ear.py --aligned_dir output/whole_ear_r24/aligned_weld_repaired --out_dir output/pca_average --variance_threshold 0.75
```

## 7. 建议输出

```text
output/pca_average/pca_summary.csv
output/pca_average/sample_manifest.csv
output/pca_average/mean_whole_ear_points.csv
output/pca_average/mean_whole_ear_faces.csv
output/pca_average/mean_whole_ear.ply
output/pca_average/components.npy
output/pca_average/scores.csv
output/pca_average/explained_variance.csv
output/pca_average/pc_modes/<pc>_minus_2sd.ply
output/pca_average/pc_modes/<pc>_plus_2sd.ply
```

`pca_summary.csv` 至少记录：样本数、顶点数、维度数、75% 主成分数、实际累计解释方差、输入样本列表和状态。

## 8. 实现步骤

1. 读取 `alignment_qc_summary.csv`，筛选 alignment PASS。
2. 回查每个样本 weld `pca_ready=True`。
3. 验证所有点序、顶点数和 faces 完全一致。
4. 构建 `X.shape=(N, 13359)`。
5. 计算均值、中心化矩阵和 SVD。
6. 选取累计解释方差达到 75% 的最小主成分数。
7. 输出 components、scores 和解释方差。
8. 将平均向量 reshape 为 `(4453,3)`，使用固定 faces 导出平均耳。
9. 输出各主成分 `mean +/- 2SD` 模式 PLY，检查变化是否为真实形态而非整体姿态。

## 9. 测试要求

`tests/test_pca_average.py` 至少覆盖：

1. 点 CSV 被显式按 `global_vertex_id` 排序。
2. 顶点缺失、重复、NaN/Inf 时拒绝输入。
3. 不同样本 faces 不一致时拒绝输入。
4. 非 PCA_READY、局部标准面不完整、GPA 未收敛或 alignment FAIL 样本被排除。
5. 已知矩阵能够正确选择累计解释方差 75% 的主成分数。
6. 中心化后的各维均值接近零。
7. mean vector 正确恢复为 `(V,3)`。
8. 平均耳 faces 与 whole-ear 固定模板完全一致。
9. 单样本时返回 `INSUFFICIENT_SAMPLES`，不伪造 PCA。
10. SVD 重构和 score 维度正确。

## 10. 统计与解释注意事项

- 当前 8 个样本只适合验证代码和初步观察，正式统计结论需要更多合格样本。
- 刚体对齐没有缩放，因此 PCA 会保留真实尺寸差异，符合人因尺寸分析目标。
- landmark 对齐残差不应强制为零；它包含真实个体形态差异。
- 不要在 PCA 阶段对 WARNING/FAIL 样本做插值，也不要重新焊接。
- PC1 若主要表现为整体平移或旋转，应回查对齐流程；若表现为局部断裂，应回查 weld QC 和全局点序。

## 11. 相关文档

- `docs/remesh_usage_w2.md`：W2 remesh 与 salvaged 输出。
- `docs/whole_ear_weld_and_alignment.md`：全局模板、焊接 QC、Kabsch/GPA 的实现与字段。
- `README.md`：当前命令、样本状态和主线入口。
