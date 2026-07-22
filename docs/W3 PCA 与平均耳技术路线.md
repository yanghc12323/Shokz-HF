# W3 PCA 与平均耳技术路线

> 面向对象：后续接手项目的 AI 或工程师
> 更新时间：2026-07-14
> 当前状态：W3 PCA 与平均耳核心模块已实现；已完成 11 个样本的 GPA/T076 首轮对比，待扩展至当前 28 个原始配对样本的合格子集。

## 1. 目标与边界

W3 的目标是对已经统一点序、统一三角面拓扑并完成刚体对齐的整耳模型做 PCA，选取累计解释方差不少于 75% 的最少主成分，并将均值向量恢复为三维平均耳。

W3 **不**重新做 landmark 标注、patch remesh、区域修补或边界焊接。这些工作均属于上游 W2/整耳流程。刚体对齐后可形成两条独立的 W3 输入：隔离模式为 `weld_repaired -> aligned_gpa`（GPA）与 `weld_repaired -> aligned_reference_T076_L`（固定参考耳）；未传 `--output-root` 的 legacy CLI 模式保留 `weld_repaired -> aligned_weld_repaired` 与 `weld_repaired -> aligned_reference_weld_repaired`。

进入 W2 前，正式批处理会将所有输入标准化为 canonical L：L 耳保持不变，R 耳默认沿 X 轴镜像并反转 face 绕序。原始文件不改写。桌面隔离模式（传入 `--output-root`）将标准化层及 JSON 审计保存于 `<output-root>/canonical_inputs_r24/`；未传 `--output-root` 的 legacy CLI 模式才保存于 `output/canonical_inputs_r24/`。这一步只统一左右侧别；其后可选择 GPA 或固定参考耳进行刚体对齐。

## 2. 正式输入与准入门禁

桌面软件隔离模式（传入 `--output-root`）的 GPA 主输入目录：

```text
<output-root>/whole_ear_r24/aligned_gpa/
  alignment_qc_summary.csv
  <sample>_aligned_whole_ear_points.csv
  <sample>_aligned_whole_ear_faces.csv
```

隔离模式的固定参考耳输入目录：

```text
<output-root>/whole_ear_r24/aligned_reference_T076_L/
  alignment_qc_summary.csv
  fixed_reference_landmarks.csv
  <sample>_aligned_whole_ear_points.csv
  <sample>_aligned_whole_ear_faces.csv
```

未传 `--output-root` 的 legacy CLI 模式才使用原有 GPA 主输入目录：

```text
output/whole_ear_r24/aligned_weld_repaired/
  alignment_qc_summary.csv
  <sample>_aligned_whole_ear_points.csv
  <sample>_aligned_whole_ear_faces.csv
```

legacy CLI 的可选固定参考耳输入目录：

```text
output/whole_ear_r24/aligned_reference_weld_repaired/
  alignment_qc_summary.csv
  fixed_reference_landmarks.csv
  <sample>_aligned_whole_ear_points.csv
  <sample>_aligned_whole_ear_faces.csv
```

两条目录只能各自独立运行 PCA，不能混合读取。GPA 使用群体迭代平均 landmark 作为目标，适合群体统计；固定参考耳使用指定样本 landmark 作为目标，适合稳定的工程坐标表达。两者均只做旋转和平移。

固定参考耳对齐还会输出每个样本的 `*_aligned_whole_ear.obj` 和 `*_aligned_whole_ear.stl`，用于工程查看；PCA 始终读取对应目录中的 points/faces CSV。

隔离模式的 Weld 来源目录为 `<output-root>/whole_ear_r24/weld_repaired/`；未传 `--output-root` 的 legacy CLI 模式回查以下固定来源目录：

```text
output/whole_ear_r24/weld_repaired/
  <sample>_weld_qc_summary.csv
```

一个样本只有同时满足以下条件才进入 PCA：

1. `alignment_qc_summary.csv` 中 `status=PASS`。
2. 对齐记录中的 `input_layer=weld_repaired`。
3. 对应 Weld 汇总中 `status=PASS`、`pca_ready=True` 且 `input_layer=weld_repaired`。
4. 坐标 `x/y/z` 全部有限；`global_vertex_id` 无重复，且所有准入样本的点编号序列完全一致。
5. 所有准入样本的 `global_face_id` 与 `global_v0/v1/v2` 完全一致。

门禁结果写入 `pca_input_manifest.csv`。任何不满足条件的样本会写明 `exclusion_reason`，不会被静默忽略或混入计算。

## 3. 数据矩阵与数学方法

每个样本先按 `global_vertex_id` 升序排列，得到固定形状的坐标数组：

```text
xyz.shape = (4453, 3)
vector = xyz.reshape(-1)       # 长度 13359
X.shape = (N, 13359)
```

对 `X` 按列求均值并中心化，再执行 NumPy SVD：

```python
mean_vector = X.mean(axis=0)
X_centered = X - mean_vector
_, singular_values, Vt = np.linalg.svd(X_centered, full_matrices=False)
explained_variance = singular_values**2 / (N - 1)
```

方差为零的数值残余成分会被剔除。依次累加解释方差比例，取首次达到阈值的主成分数。默认阈值为 0.75。

刚体对齐阶段只使用旋转和平移，不做缩放。因此 W3 会保留真实耳朵尺寸差异，符合人因尺寸分析目标。

## 4. 平均耳与主成分模式

平均耳的顶点直接由均值向量恢复：

```python
mean_points = mean_vector.reshape(4453, 3)
```

面片不重新生成，直接复制已经验证一致的固定 faces（8640 个三角面）。因此平均耳天然具有与所有 PCA 输入相同的全局点编号与拓扑。

对每个保留的 PC，导出：

```text
mean + 2 * sqrt(explained_variance) * component
mean - 2 * sqrt(explained_variance) * component
```

这些 PLY 用于观察该主成分代表的形态变化；它们是统计形态示意，不是新的受试者原始模型。

## 5. 实现文件

```text
ear_param/pca_average.py       # 输入门禁、拓扑校验、SVD、平均耳与文件导出
scripts/build_average_ear.py   # 命令行入口
tests/test_pca_average.py      # 输入契约与 PCA 回归测试
```

## 6. 运行命令

从原始配对数据运行正式全流程：

```powershell
python scripts/run_full_pipeline.py
```

当前正式全流程使用 `MQ_S068L` 作为固定参考耳：

```powershell
python scripts/run_full_pipeline.py --parallel-workers 4 --alignment-mode fixed-reference --reference-sample MQ_S068L
```

### 正式隔离全流程（桌面软件）

桌面软件运行正式 W2-to-W3 批处理时必须使用隔离模式，不能依赖旧的共享 `output/...` 输出。`--output-root` 是 opt-in 参数，只有显式传入才启用；目标目录必须不存在，或完全为空（不能含任何文件或子目录）。进程会原子创建 `<output-root>/.pipeline-reservation` 认领该目录；崩溃后标记有意保留并阻止复用，下一次必须使用新的运行目录。使用以下正式命令：

```powershell
python scripts/run_full_pipeline.py `
  --parallel-workers 4 `
  --alignment-mode fixed-reference `
  --reference-sample MQ_S068L `
  --output-root output/pipeline_runs/mq_full_20260722
```

该命令未另传 `--run_dir`，因此 `<output-root>` 包含所有 canonical、W2、QC、Weld、Alignment、PCA、汇总、日志和 manifest 产物：

```text
<output-root>/
  .pipeline-reservation
  manifest.json
  pipeline_batch_summary.csv
  pipeline_run_summary.csv
  pipeline_run.log
  canonical_inputs_r24/
  parameterized_points_r24/{raw,repaired,salvaged}/
  remesh_r24/{raw,repaired,salvaged}/
  remesh_qc_r24/
  whole_ear_r24/{weld_repaired,aligned_gpa,aligned_reference_MQ_S068L}/
  pca_gpa_r24/
  pca_reference_MQ_S068L_r24/
```

固定参考耳目录名跟随实际的 `--reference-sample`，即 `aligned_reference_<reference-sample>` 与 `pca_reference_<reference-sample>_r24`；上面的 `T076_L` 是正式示例，未选择其他参考样本时仍使用该默认目录名。

不传 `--output-root` 时，所有阶段继续使用原有固定 `output/...` 目录；`--run_dir` 仍只控制批次汇总目录，不会重定向 W2、QC、Weld、对齐或 PCA 的阶段输出，旧命令和 `--run_dir` 语义完全不变。传入 `--output-root` 时只能省略 `--run_dir`，或让两者解析为同一路径；不同的 `--run_dir` 会被拒绝，manifest、CSV 汇总、日志和阶段产物都位于同一隔离根。桌面软件必须传 `--output-root`，不能依赖旧的共享输出模式。

上文未传 `--output-root` 的默认旧命令会自动发现 mesh/landmark 配对样本，并在单样本失败时继续处理其他样本；其 manifest、批次总表、统计汇总和日志写入 `output/pipeline_runs/<时间戳>/`。隔离命令未传 `--run_dir` 时，这些批次文件改为写入指定的 `<output-root>/`，并与各阶段产物同处一个隔离根。两种模式下，如需缩短运行时间，均可使用 `--skip-remesh-qc` 跳过耗时的区域 QC 图，但不会跳过 remesh、Weld、对齐或 PCA。

单独重跑 GPA-PCA 时，隔离模式必须显式使用同一个 `<output-root>`：

```powershell
python scripts/build_average_ear.py --aligned_dir <output-root>/whole_ear_r24/aligned_gpa --weld_dir <output-root>/whole_ear_r24/weld_repaired --out_dir <output-root>/pca_gpa_r24 --variance_threshold 0.75
```

单独重跑固定参考耳 PCA 的隔离模式命令：

```powershell
python scripts/build_average_ear.py --aligned_dir <output-root>/whole_ear_r24/aligned_reference_T076_L --weld_dir <output-root>/whole_ear_r24/weld_repaired --out_dir <output-root>/pca_reference_T076_L_r24 --variance_threshold 0.75
```

以下两条命令仅用于未传 `--output-root` 的 legacy CLI 模式：

```powershell
python scripts/build_average_ear.py --aligned_dir output/whole_ear_r24/aligned_weld_repaired --weld_dir output/whole_ear_r24/weld_repaired --out_dir output/w3_pca_r24 --variance_threshold 0.75
```

单独重跑固定参考耳 PCA：

```powershell
python scripts/build_average_ear.py --aligned_dir output/whole_ear_r24/aligned_reference_weld_repaired --weld_dir output/whole_ear_r24/weld_repaired --out_dir output/w3_pca_reference_r24 --variance_threshold 0.75
```

终端会打印纳入样本、排除样本数、达到阈值的主成分数和输出路径。

## 7. 输出说明

未传 `--output-root` 的 legacy CLI 模式输出为：

```text
output/w3_pca_r24/
  pca_input_manifest.csv
  pca_summary.csv
  mean_whole_ear_points.csv
  mean_whole_ear_faces.csv
  mean_whole_ear.ply
  components.npy
  scores.csv
  explained_variance.csv
  pc_modes/PC01_plus_2sd.ply
  pc_modes/PC01_minus_2sd.ply
  ...
```

legacy CLI 的固定参考耳分支输出同样的文件结构，但根目录为 `output/w3_pca_reference_r24/`。隔离模式的两条 PCA 输出根目录分别为 `<output-root>/pca_gpa_r24/` 与 `<output-root>/pca_reference_<reference-sample>_r24/`；正式 `T076_L` 示例对应 `<output-root>/pca_reference_T076_L_r24/`。应分别比较两条路径的 `pca_summary.csv`、平均耳与主成分模式，不应将 scores 或 components 直接合并。

- `pca_input_manifest.csv`：逐样本的 Weld/对齐来源检查与纳入决定。
- `pca_summary.csv`：纳入数、排除数、点数、面数、阈值、保留主成分数和实际累计方差。
- `mean_whole_ear_points.csv`、`mean_whole_ear_faces.csv`、`mean_whole_ear.ply`：平均耳。
- `components.npy`：每行一个主成分，列顺序为点 0 的 `x,y,z`，再到点 1，以此类推。
- `scores.csv`：每个受试者在各主成分上的得分。
- `explained_variance.csv`：每个主成分的方差、比例、累计比例，以及是否被 75% 阈值保留。
- `pc_modes/`：保留主成分的均值正负 2 个标准差形态。

## 8. 当前真实运行结果

2026-07-14 的首轮已处理批次包含 12 个样本；它是当前 28 个原始配对样本中的已完成子集：

```text
Weld PASS / PCA-ready / Alignment PASS:
T013_L, T066_L, T068_L, T069_L, T076_L, T077_L,
T078_L, T088_L, T094_L, T097_L, T099_L

Weld FAIL，未进入 PCA:
T049_L
```

PCA 的 11 个输入均为 4453 顶点、8640 面。按 75% 阈值：

| 主成分 | 解释方差比例 | 累计比例 | 是否保留 |
|---|---:|---:|---|
| PC1 | 36.38% | 36.38% | 是 |
| PC2 | 21.70% | 58.08% | 是 |
| PC3 | 17.27% | 75.35% | 是 |

所以首轮保留 3 个主成分；`mean_whole_ear.ply` 已导出，且检查为 4453 个有限顶点和 8640 个三角面。

以 `T076_L` 为固定参考耳、对同一 11 个样本完成的独立 PCA 同样保留 3 个主成分，前三项累计解释 75.3138%。两条路径的平均耳在最佳刚体叠合后的顶点 RMS 差异为 0.00855 mm，PC1/PC2 scores 相关性均大于 0.999。完整对比见 `docs/GPA与T076固定参考耳PCA对比.md`。

## 9. 测试与解释边界

自动化测试覆盖：点编号排序、修补层来源门禁、重复点编号、NaN 坐标、面拓扑不一致、75% 阈值选择和输出文件生成。

11 个样本足以验证流程和查看初步模式，但不足以代表稳定总体形态分布。正式人群结论前，应继续扩充样本，并优先修复 `T049_L` 的共享边失败原因；不得通过降低 Weld/PCA 门禁来强行纳入。

相关上游说明见 `docs/整耳全局模板、边界焊接与刚体统一坐标系.md`。
