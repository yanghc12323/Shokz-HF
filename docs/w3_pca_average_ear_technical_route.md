# W3 PCA 平均耳技术路线说明

> 面向对象：后续接手本项目的 AI 或工程师  
> 更新时间：2026-07-09  
> 上游输入：W2 patch-based remesh 合格输出  
> 当前状态：W3 尚未正式实现；W2 主线已切换到 resolution=24，并引入 raw/repaired 两层输出

## 1. 一句话背景

本项目的目标是把不同人的 3D 耳模型转换成同拓扑、同点序、同 region 定义的 remesh 表达，然后在这个统一表达上做统计形态分析。W2 已经实现：根据 landmark 划分三角区域，将局部 3D patch 参数化到标准 2D 三角域，固定采样点数量，再映射回 3D，并输出 remesh points、faces、QC 和 landmark 几何特征。

W3 的任务是：对所有合格模型进行 PCA，选取累计解释方差达到 75% 的主成分，计算平均形态，并使用 W2 的固定 template faces 生成平均 patch / 平均耳。

## 2. 当前 W2 状态对 W3 的影响

当前有效真实样本：

```text
T013_L
T076_L
T077_L
T078_L
```

历史 r8 13 区域 QC 可视化结果：

```text
T013_L: PASS=2, WARNING=10, FAIL=1
T076_L: PASS=2, WARNING=11, FAIL=0
T077_L: PASS=3, WARNING=10, FAIL=0
T078_L: PASS=3, WARNING=9,  FAIL=1
共同 PASS region: 0
```

因此当前不建议立刻做正式 W3 PCA。原因是 W3 的 PCA 矩阵要求同一个 `region_id` 在多个样本中都有完整、无 NaN、同点序的 3D 坐标。更新 T078 PLY 后，四样本无 FAIL region 已增加到 12 个，但当前四样本仍没有共同 PASS region，强行做 PCA 会导致输入不足或需要错误地填补 NaN。

当前 r24 已在四个真实样本上完成验证：

```text
raw:
T013_L: PASS=2, WARNING=10, FAIL=1
T076_L: PASS=2, WARNING=11, FAIL=0
T077_L: PASS=3, WARNING=10, FAIL=0
T078_L: PASS=3, WARNING=9,  FAIL=1

repaired:
T013_L: PASS=12, WARNING=0, FAIL=1
T076_L: PASS=13, WARNING=0, FAIL=0
T077_L: PASS=13, WARNING=0, FAIL=0
T078_L: PASS=12, WARNING=0, FAIL=1
```

r24 repaired 输出适合用于补齐 PLY 可视化；是否进入 W3 PCA，需要后续明确采用 raw PASS-only 还是 repaired exportable 数据。默认更保守的 W3 方案仍使用 raw PASS-only。

当前正确顺序是：

```text
T0：继续用真实样本验证 region table。
T1：调整 region table，找到多个样本共同 PASS 的候选 region。
T2：必要时再调整边界路径、patch 选择或参数。
W3：只对共同 PASS 的 region 做 PCA。
```

## 3. W3 输入契约

W3 不读取原始高密度 mesh，不重新找 landmark，不重新做 harmonic parameterization。W3 的可信输入只能来自 W2 输出：

```text
output/parameterized_points_r24/raw/<sample>_<side>_remesh_points.csv
output/parameterized_points_r24/raw/<sample>_<side>_remesh_faces.csv
output/parameterized_points_r24/raw/<sample>_<side>_remesh_qc.csv
output/parameterized_points_r24/repaired/<sample>_<side>_remesh_points.csv
output/parameterized_points_r24/repaired/<sample>_<side>_remesh_faces.csv
output/parameterized_points_r24/repaired/<sample>_<side>_remesh_qc.csv
```

可选读取：

```text
output/parameterized_points_r24/raw/<sample>_<side>_region_features.csv
```

`region_features` 用于解释 landmark 尺寸、角度、面积差异，不是 PCA 坐标矩阵的必需输入。

## 4. 合格 region 判定

W3 只能使用满足以下条件的 region：

```text
status == "PASS"
sample_point_count == expected_point_count
unmapped_count == 0
degenerate_faces == 0
x/y/z 不含 NaN 或 Inf
```

不要把 `WARNING` 或 `FAIL` region 的 NaN 坐标填补后做 PCA。这样会把 W2 的边界失败混入 W3 的形态统计结果。

## 5. points CSV 必要字段

`*_remesh_points.csv` 必须包含：

```text
point_id
sample_id
side
region_id
region_name
region_point_id
lambda_a
lambda_b
lambda_c
u
v
source_face_index
is_unmapped
x
y
z
```

关键对齐字段：

```text
region_id
region_point_id
```

W3 必须按 `region_point_id` 显式排序，不能依赖 CSV 原始行顺序。

## 6. faces CSV 必要字段

`*_remesh_faces.csv` 必须包含：

```text
sample_id
side
region_id
region_name
face_id
local_v0
local_v1
local_v2
global_v0
global_v1
global_v2
```

W3 生成平均 patch 时必须使用 W2 输出的 fixed template faces，不要重新 triangulate。

## 7. 推荐数据组织方式

建议先按 region 独立做 PCA：

1. 读取所有样本的 W2 输出。
2. 根据 QC 找出每个 region 的合格样本。
3. 只保留至少 2 个合格样本的 region。
4. 对每个 region，按 `region_point_id` 排序。
5. 将每个样本的 `(P, 3)` 坐标展平为 `(P*3,)`。
6. 堆叠成 `X.shape == (N, P*3)`。
7. 对该 region 独立做 PCA。
8. 输出该 region 的平均 patch。
9. 最后再拼接多个平均 patch，得到平均耳雏形。

暂不建议一开始就把所有 region 拼成整耳 PCA。原因是不同 region 的 QC 状态可能不同，按 region 做更容易定位问题。

## 8. PCA 算法路线

输入：

```text
X.shape == (N, D)
D = P * 3
```

步骤：

```python
mean_vector = X.mean(axis=0)
X_centered = X - mean_vector
U, S, Vt = np.linalg.svd(X_centered, full_matrices=False)
explained_variance = (S ** 2) / (N - 1)
explained_variance_ratio = explained_variance / explained_variance.sum()
cumulative = np.cumsum(explained_variance_ratio)
n_components_75 = int(np.searchsorted(cumulative, 0.75) + 1)
components = Vt[:n_components_75]
```

当前建议优先使用 `numpy.linalg.svd`，避免新增 `scikit-learn` 依赖。

## 9. 样本数量限制

真正 PCA 至少需要：

```text
N >= 2
```

如果某个 region 只有 1 个合格样本：

1. 不计算 PCA。
2. 可以输出该 region 的均值点作为流程验证。
3. `pca_summary.csv` 中标记为 `INSUFFICIENT_SAMPLES`。

如果某个 region 没有合格样本：

1. 不输出平均 patch。
2. `pca_summary.csv` 中标记为 `NO_PASS_SAMPLES`。

## 10. 平均 patch 生成

对每个 region：

```python
mean_points = mean_vector.reshape(P, 3)
faces = faces_df[["local_v0", "local_v1", "local_v2"]].to_numpy(dtype=int)
mesh = trimesh.Trimesh(vertices=mean_points, faces=faces, process=False)
```

faces 必须来自 W2 的 remesh faces。不要重新 Delaunay，不要重新 remesh。

## 11. 平均耳生成

第一版可以直接把多个平均 patch 拼接：

1. 每个 region 生成一组 `mean_points`。
2. 每个 region 的 faces 加上顶点 offset。
3. 合并 vertices 和 faces。
4. 导出 `average_ear.ply`。

注意：相邻 region 的边界点可能重复。第一版可以接受重复边界点，因为 W3 的核心目标是统计对齐，不是生成生产级 watertight mesh。

## 12. 建议新增文件

W3 实现时建议新增：

```text
ear_param/pca_average.py
scripts/build_average_ear.py
tests/test_pca_average.py
```

建议输出目录：

```text
output/pca_average/
```

建议命令：

```powershell
python scripts/build_average_ear.py --points_dir output/parameterized_points --out_dir output/pca_average
```

## 13. 建议输出文件

```text
output/pca_average/pca_summary.csv
output/pca_average/<region_id>_mean_points.csv
output/pca_average/<region_id>_pca_components.csv
output/pca_average/<region_id>_explained_variance.csv
output/pca_average/<region_id>_mean_patch.ply
output/pca_average/average_ear.ply
output/pca_average/average_ear_points.csv
output/pca_average/average_ear_faces.csv
```

`pca_summary.csv` 建议字段：

```text
region_id
n_samples
n_points
n_dimensions
n_components_75
explained_variance_75
status
message
```

## 14. 测试计划

`tests/test_pca_average.py` 至少覆盖：

1. `run_pca_75` 能正确选择累计解释方差 >= 75% 的主成分数。
2. 单 region points CSV 能构造成正确形状矩阵。
3. 点序按 `region_point_id` 排序。
4. QC 不合格样本被剔除。
5. 只有 1 个合格样本时返回 `INSUFFICIENT_SAMPLES`。
6. mean vector reshape 后得到 `(P, 3)`。
7. 平均 patch mesh 使用 W2 fixed template faces。
8. 不依赖真实大 mesh，用小型合成 CSV 做单元测试。

## 15. 常见错误

### 错误 1：把 WARNING/FAIL region 填 NaN 后做 PCA

禁止。必须先按 QC 剔除不合格样本。

### 错误 2：忘记按 `region_point_id` 排序

会导致不同样本的点错位，PCA 结果无意义。

### 错误 3：把单样本结果当 PCA

单样本只能得到均值，不能得到可靠主成分。

### 错误 4：重新生成 faces

W3 不应重新 remesh 或重新 triangulate。faces 必须来自 W2 的 `*_remesh_faces.csv`。

### 错误 5：忽略 W2 QC 可视化结论

如果某个 region 在 W2 中 patch/UV 覆盖不足，应先修 region table 或边界策略，而不是在 W3 中补救。

## 16. 当前结论

W3 技术路线已经明确，但当前四样本还不满足正式 PCA 的前置条件。下一步应先完成 W2 的 T0/T1/T2：继续验证、调整 region table、再考虑算法参数。等多个样本在同一 region 上同时 PASS 后，再实现并运行 W3。
