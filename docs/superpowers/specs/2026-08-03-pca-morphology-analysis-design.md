# PCA 形态极值、自动聚类与极端个体分析设计

日期：2026-08-03  
状态：已确认，待实施

## 1. 目标与边界

在既有全耳 PCA 完成后，新增一组可复核的形态学后处理结果：

1. 四个 PCA 理论极值形态：`PC01+`、`PC01-`、`PC02+`、`PC02-`；
2. 四个方向对应的真实极值被试：PC1 最高/最低、PC2 最高/最低；
3. 基于 PCA score 的自动形态聚类；
4. 多变量意义上的候选极端形态个体；
5. 可直接阅读的散点图、聚类图与模型产物；
6. 桌面端对上述结果的查看、选择与三维模型加载。

本功能只消费已经通过既有 PCA 纳入门禁的对齐全耳数据。它不得改变下列任何处理或判定：区域 Remesh、Salvage、Weld、配准、PCA 输入纳入、平均耳、PCA 数学结果、QC 状态及失败原因。

## 2. 术语与解释原则

### 2.1 理论极值形态与真实极端被试

二者必须分别命名、分别输出和分别显示：

| 类型 | 定义 | 是否真实被试 |
| --- | --- | --- |
| PCA 理论极值形态 | 平均耳加/减对应主成分的 2 个标准差，即 `mean ± 2 × sqrt(eigenvalue) × component` | 否 |
| 方向极值被试 | 当前轮 PCA score 中 PC01 或 PC02 的最大值/最小值样本 | 是 |
| 综合极端形态个体 | 在保留 PCA score 的标准化空间中，距离总体中心最远的一组真实样本 | 是 |

同一真实样本可以同时占据多个 PC 方向极值，这不视为异常。

`+PC` 与 `-PC` 仅代表当前 PCA 运行中 score 的正负方向，不自动赋予“大/小”“宽/窄”等解剖语义。用户应通过对应三维形态和图形解释其意义；不同批次 PCA 的正负方向不应在未核对模型的情况下直接比较。

### 2.2 聚类定位

聚类是对本轮 PCA 纳入人群的描述性形态分组，不是 QC 门禁、诊断标签或剔除依据。候选极端个体同样仅用于提示优先复核对象。

## 3. 计算设计

### 3.1 保持既有 PCA 不变

继续使用当前 SVD PCA：以对齐全耳坐标拼接向量为输入、只中心化、不对物理坐标重新缩放。既有 `components.npy`、`scores.csv`、`explained_variance.csv`、平均耳及原有 PCA 汇总的数值保持不变。

形态后处理读取 `PcaInput` 和 `PcaResult`，在 PCA 写出阶段的后续步骤中计算。后处理出错时应在其自身汇总中记录错误，不得篡改已成功生成的 PCA 主结果。

### 3.2 四个 PCA 理论极值形态

当 PC01 和 PC02 均存在时，始终输出以下四个 PLY：

```text
pc_modes/PC01_plus_2sd.ply
pc_modes/PC01_minus_2sd.ply
pc_modes/PC02_plus_2sd.ply
pc_modes/PC02_minus_2sd.ply
```

输出表记录每个模式的组件编号、正负方向、标准差倍数、解释方差比例和 PLY 相对路径。当非零主成分少于 2 个时，PC01 正负形态仍输出，PC02 两项在表中明确标记 `unavailable_insufficient_nonzero_components`，不会伪造模型。

### 3.3 真实方向极值被试

针对 PC01 与 PC02，各自从 `scores.csv` 中选取最大和最小 score 的样本，共四个方向记录。每条记录至少包含：

```text
component, direction, sample_tag, score, score_z, rank,
aligned_points_path, aligned_mesh_path, cluster_id
```

如果 score 出现完全相同的并列值，以字典序更靠前的 `sample_tag` 作为主记录，同时增加并列数和全部并列样本字段，确保运行可重复、信息不丢失。

### 3.4 自动聚类

聚类特征为达到当前 PCA 方差阈值（默认 75%）所保留的所有 PC score。每列 score 按样本进行 Z-score 标准化，防止 PC1 的量级主导距离。

采用 SciPy 的 Ward 层次聚类，保持项目离线依赖不增加 scikit-learn。候选类别数为：

```text
K = 2 ... min(6, 样本数 - 1)
```

对每个候选 K 计算平均 silhouette score；选择得分最高的 K。相同得分以较小的 K 作为稳定的确定性规则。输出所有候选 K 的分数、每类样本数和选择理由。

聚类编号不是算法内部编号：按每个类的 PC01 平均 score 从低到高排序后，重新命名为 `Cluster 01`、`Cluster 02` 等。这样同一轮运行内编号稳定、可读。

样本数少于 4 时，写出 `insufficient_sample_count` 状态并跳过聚类；PCA 和其余形态输出仍可用。若某候选 K 的标签不满足 silhouette 计算条件，记录其不可用原因并不参与选择。

### 3.5 综合极端形态个体

使用和聚类相同的标准化保留 PC score，计算每个样本到总体中心的欧氏距离；在该正交标准化空间中，该距离等价于基于保留主成分的 Mahalanobis 距离。

输出每个样本的距离、距离百分位、排名、聚类编号和是否为候选极端个体。候选阈值为距离的 95 百分位及以上；它是展示与人工复核阈值，不修改任何样本的 PASS/FAIL 状态。

### 3.6 聚类平均耳

对每个聚类中真实样本的对齐坐标逐点求均值，沿用既有公共拓扑，生成一个聚类平均耳 PLY。它是该组真实样本的几何均值，不是由 PCA 合成的虚拟形态。

## 4. 输出契约

新增目录位于 PCA 输出根目录：

```text
pca_morphology/
  pca_morphology_summary.csv
  pc_extreme_shapes.csv
  observed_pc_extremes.csv
  multivariate_extreme_individuals.csv
  cluster_k_selection.csv
  cluster_assignments.csv
  cluster_summary.csv
  cluster_means/
    Cluster_01_mean.ply
    ...
  figures/
    pc1_pc2_clusters.png
    pc_variance_scree.png
```

文件职责：

| 文件 | 内容 |
| --- | --- |
| `pca_morphology_summary.csv` | 后处理状态、样本数、特征 PC 数、选中 K、极端阈值、异常原因 |
| `pc_extreme_shapes.csv` | 四个理论 PC 极值形态及其模型路径 |
| `observed_pc_extremes.csv` | 四个方向上的真实极值被试 |
| `multivariate_extreme_individuals.csv` | 全部样本的综合形态距离、排名与候选标记 |
| `cluster_k_selection.csv` | 每个候选 K 的 silhouette score、有效性、选择标记 |
| `cluster_assignments.csv` | 每个样本的聚类归属及其 PCA score |
| `cluster_summary.csv` | 每个类的样本数、中心 score、成员清单、平均耳路径 |
| `pc1_pc2_clusters.png` | PC1–PC2 散点、聚类颜色和四个真实方向极值标记 |
| `pc_variance_scree.png` | 各 PC 解释方差与累计解释方差图 |

真实极端个体不复制原模型，以相对路径引用已有 aligned 全耳产物，避免不必要的 I/O 与重复占用空间。

## 5. 图形化呈现

### 5.1 CLI 产物

输出两张 PNG：

1. **PC1–PC2 聚类散点图**：每个点是一个真实样本，颜色表示聚类；标出 `PC01+`、`PC01-`、`PC02+`、`PC02-` 的真实极值样本；坐标轴注明解释方差比例。
2. **解释方差 Scree 图**：柱状图表示单个 PC 的解释方差比例，折线表示累计比例，并标出当前方差阈值和达到阈值的最小 PC 数。

图形仅用于理解与汇报，全部结论均可回溯至 CSV 和 PLY。

### 5.2 桌面软件

在“结果复核”内新增独立的“PCA 形态分析”页面，避免继续挤占现有 PCA score 和三维查看区域。页面布局：

| 区域 | 内容 |
| --- | --- |
| 左侧 | PCA 汇总、自动选定 K、聚类摘要、理论极值/真实极值/综合极端个体列表 |
| 右上 | `PC1–PC2` 聚类散点图和 PCA score 表 |
| 右下 | 三维模型查看器；可切换平均耳、四个理论极值、聚类平均耳和真实极端个体 |

点击表格中的样本或模型条目，应直接加载对应 PLY。页面必须清晰标注“理论形态”或“真实被试”，防止混淆。若本轮没有可用聚类，界面显示具体原因，不显示空白或错误结论。

## 6. 错误处理与兼容性

1. PCA 自身失败时，不创建虚假的形态分析结果；索引器和桌面端显示 PCA 原始失败原因。
2. PCA 成功但形态后处理因样本数或组件数不足而无法完成时，保留可生成的产物，摘要 CSV 写入状态和原因。
3. 同一输入、参数、排序下，极值选择、聚类结果和输出文件顺序必须可重复。
4. 不增加联网需求；只使用已在 `requirements.txt` 中的 NumPy、SciPy、Pandas、Matplotlib 和 Trimesh。
5. 原有 CLI 参数、PCA 路径、已有输出文件名和桌面端旧运行的加载逻辑保持兼容。

## 7. 验证策略

新增单元和集成测试覆盖：

1. 四个 PC 理论极值 PLY 和其清单正确生成；PC02 不可用时明确报告。
2. 四个真实方向极值的样本、score、并列规则和排序正确。
3. 自动 K 在合成可分群数据上选中期望类别数；候选 K、silhouette 与稳定 tie-break 可复核。
4. 样本过少、无法 silhouette、全部 shape variance 为零等边界情况不会伪造结论。
5. 综合极端距离、百分位与候选标记正确，且不影响 PCA 纳入状态。
6. 聚类平均耳保持输入公共拓扑。
7. PNG 图像存在且包含 PC 坐标、聚类或方差所需信息。
8. 原 PCA 输出在新增后处理前后数值一致。
9. 桌面端可加载新旧两类运行：新运行显示形态分析，旧运行以明确的无产物状态正常显示。
