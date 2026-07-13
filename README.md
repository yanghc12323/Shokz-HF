# 3D Ear Cross-Parameterisation with Patch-Based Remesh

> 当前主线：论文式 patch-based remesh  
> 当前阶段：W2 remesh 主流程已可运行，正在做多样本 QC、region table 优化与 raw FAIL 保守 salvage  
> 更新时间：2026-07-11

## 1. 项目目标

本项目用于把不同受试者的 3D 耳模型转换为可跨样本统计分析的统一表达。原始 mesh 的顶点数量、面片拓扑和局部形态都不一致，不能直接堆叠后做 PCA。因此当前采用论文式 patch-based remesh 路线：

```text
原始耳朵 mesh
  + landmark 标注
  + region_table 三角选区
  -> 局部 patch 提取
  -> harmonic UV 参数化到标准 2D 三角域
  -> 固定 2D subdivision 降采样
  -> 映射回 3D
  -> 输出同点序、同面片模板的 remesh patch
```

这样每个合格样本、每个合格区域都有相同点数、相同点序、相同 template faces，可用于后续 PCA、平均耳和形态特征分析。

## 2. 当前真实数据状态

当前有效真实样本以 `data/clean_mesh/` 与 `data/landmarks/` 中成对存在的文件为准。目前项目内已有：

```text
T013_L, T049_L, T076_L, T077_L, T078_L,
T088_L, T094_L, T097_L, T099_L, T100_L
```

当前 `config/region_table.csv` 包含 15 个三角 region，每个 region 当前 `resolution=24`，即每区 325 个 template 点、576 个 template faces。T100_L 目前作为特殊诊断样本处理；如果出现 `degenerate_faces`，不要直接把它混入 W3 PCA 输入。

旧的 `T001_L` 输入和输出已经从当前主线移除。不要再把旧 T001 结果作为当前 13 区域方案的有效结果使用。

## 3. 当前 W2 进展

W2 任务是：

> 参考论文明确耳朵模型需求形态以及划分选区的特征点，将划分的三维三角区域投影至二维平面，进行降采样处理，限定每一区域的采样点数量相同，并根据选取的特征点计算相关特征值。

当前已经实现：

1. landmark 吸附到 mesh 顶点。
2. mesh 顶点图构建。
3. 三个 landmark 之间的最短边界路径。
4. 边界限定 patch face 提取。
5. patch 局部子网格构建。
6. harmonic UV 参数化到标准 2D 三角域。
7. 标准 2D 三角域固定 subdivision 降采样。
8. 2D 采样点定位到源 UV face，并映射回 3D。
9. 使用 `sample_points_3d + template.faces` 组装 remesh patch。
10. 输出 points/faces/features/QC/PLY。
11. 输出每个 region 的 QC 可视化图。

结论：代码层面 W2 主流程已经可运行；当前主要工作不是继续堆功能，而是用真实样本验证 region table 的稳定性，并修正不稳定 region。

## 4. 安装依赖

在 VSCode 中打开项目根目录 `D:\YHC\人头项目` 后，打开 Terminal，运行：

```powershell
pip install -r requirements.txt
```

当前依赖：

```text
numpy
pandas
scipy
trimesh
matplotlib
```

## 5. 运行 W2 Remesh

### 单样本运行

```powershell
python scripts/parameterize_ear_remesh.py --sample_id T013 --side L --mesh data/clean_mesh/T013_L.ply --landmarks data/landmarks/T013_L_landmarks.csv
python scripts/parameterize_ear_remesh.py --sample_id T076 --side L --mesh data/clean_mesh/T076_L.ply --landmarks data/landmarks/T076_L_landmarks.csv
python scripts/parameterize_ear_remesh.py --sample_id T077 --side L --mesh data/clean_mesh/T077_L.ply --landmarks data/landmarks/T077_L_landmarks.csv
python scripts/parameterize_ear_remesh.py --sample_id T078 --side L --mesh data/clean_mesh/T078_L.ply --landmarks data/landmarks/T078_L_landmarks.csv
```

### PowerShell 批量运行

```powershell
$samples = "T013","T076","T077","T078"
foreach ($s in $samples) {
  python scripts/parameterize_ear_remesh.py --sample_id $s --side L --mesh "data/clean_mesh/${s}_L.ply" --landmarks "data/landmarks/${s}_L_landmarks.csv"
}
```

默认参数：

```text
--regions config/region_table.csv
--out_dir output/parameterized_points_r24/raw
--mesh_out_dir output/remesh_r24/raw
--repaired_out_dir output/parameterized_points_r24/repaired
--repaired_mesh_out_dir output/remesh_r24/repaired
--salvaged_out_dir output/parameterized_points_r24/salvaged
--salvaged_mesh_out_dir output/remesh_r24/salvaged
--max_salvage_unmapped_ratio 0.35
```

输出文件：

```text
output/parameterized_points_r24/raw/<sample>_<side>_remesh_points.csv
output/parameterized_points_r24/raw/<sample>_<side>_remesh_faces.csv
output/parameterized_points_r24/raw/<sample>_<side>_region_features.csv
output/parameterized_points_r24/raw/<sample>_<side>_remesh_qc.csv
output/parameterized_points_r24/repaired/<sample>_<side>_remesh_points.csv
output/parameterized_points_r24/repaired/<sample>_<side>_remesh_faces.csv
output/parameterized_points_r24/repaired/<sample>_<side>_remesh_qc.csv
output/parameterized_points_r24/salvaged/<sample>_<side>_remesh_points.csv
output/parameterized_points_r24/salvaged/<sample>_<side>_remesh_faces.csv
output/parameterized_points_r24/salvaged/<sample>_<side>_remesh_qc.csv
output/remesh_r24/raw/<sample>_<side>/<region_id>_remesh.ply
output/remesh_r24/repaired/<sample>_<side>/<region_id>_remesh_repaired.ply
output/remesh_r24/salvaged/<sample>_<side>/<region_id>_remesh_salvaged.ply
```

说明：raw PLY 只导出原始 PASS 区域；repaired PLY 允许 raw WARNING 在补点成功后导出；salvaged 层会在不改变 raw/repaired 语义的前提下，对满足安全限制的 raw FAIL 尝试少量修补并单独导出。

当前 salvage 安全限制：

```text
degenerate_faces > 0：不 salvage
raw unmapped ratio > --max_salvage_unmapped_ratio：不 salvage
默认 --max_salvage_unmapped_ratio = 0.35
salvage_accepted=True 只表示抢救后无 unmapped 且可导出，不等同于 raw PASS
```

## 6. 运行 QC 可视化

生成所有当前样本、所有 region 的 QC 图：

```powershell
python scripts/visualize_remesh_qc.py --samples T013_L T076_L T077_L T078_L
```

只诊断重点问题区域：

```powershell
python scripts/visualize_remesh_qc.py --samples T013_L T076_L T077_L T078_L --region_ids T001 T002 T009
```

输出：

```text
output/qc_visualizations_r24/raw/<sample_tag>/<region_id>_qc.png
output/qc_visualizations_r24/raw/qc_visualization_summary.csv
output/qc_visualizations_r24/repaired/<sample_tag>/<region_id>_qc.png
output/qc_visualizations_r24/repaired/qc_visualization_summary.csv
output/qc_visualizations_r24/salvaged/<sample_tag>/<region_id>_qc.png
output/qc_visualizations_r24/salvaged/qc_visualization_summary.csv
```

每个 region 会输出三张 QC 图：

1. `raw` 图：显示未修补前的原始映射结果，右侧红色叉号为 raw unmapped template 点。
2. `repaired` 图：显示修补后的结果，右侧橙色三角为 repaired 点，红色叉号为仍未修补点。
3. `salvaged` 图：显示对 raw FAIL 进行保守 salvage 后的结果；如果没有满足安全限制，会保留未修补状态并在 summary 中写明原因。

三张图左侧都显示 3D patch faces、三条 landmark boundary path 和三个 landmark 点；右侧都显示 2D UV patch 与固定 template samples。

这些图用于判断 region 失败到底是 landmark 组合问题、边界最短路径问题、patch 过窄问题，还是 UV 覆盖问题。

## 7. 当前 QC 结果

`scripts/parameterize_ear_remesh.py` 与 `scripts/visualize_remesh_qc.py` 使用同一套 raw PASS/WARNING/FAIL 判定规则。统一规则为：无 unmapped 且无 degenerate 为 PASS；少量 unmapped 为 WARNING；unmapped 比例超过 20% 或存在 degenerate face 为 FAIL。

repaired 层只处理 raw WARNING：标准三角形角点 unmapped 优先用对应吸附 landmark 替换，其余少量 unmapped 点用模板网格上的平滑插值填补。salvaged 层在相同修补算法基础上，额外允许一部分 raw FAIL 尝试修补，但会记录 `salvage_attempted`、`salvage_accepted` 和 `salvage_rejection_reason`。

当前 QC 结果不要再以旧四样本静态表为准，应直接读取最新输出：

```text
output/parameterized_points_r24/raw/<sample>_L_remesh_qc.csv
output/parameterized_points_r24/repaired/<sample>_L_remesh_qc.csv
output/parameterized_points_r24/salvaged/<sample>_L_remesh_qc.csv
output/qc_visualizations_r24/raw/qc_visualization_summary.csv
output/qc_visualizations_r24/repaired/qc_visualization_summary.csv
output/qc_visualizations_r24/salvaged/qc_visualization_summary.csv
```

当前判断：

1. 已就位样本都可以通过同一条 CLI 运行并产出 points/faces/features/QC。
2. r24 输出保持每个 region 325 点、576 面。
3. 当前已新增 salvaged 层，用于记录 raw FAIL 是否能被保守修补。
4. 如果 `degenerate_faces > 0` 或 `salvage_rejection_reason` 非空，应优先回到 boundary/region table 诊断。
5. 当前仍不建议盲目放宽 QC 或直接进入正式 W3 PCA。

## 8. 当前处理策略

当前按以下优先级推进：

```text
T0：继续用真实样本验证 region table 的稳定性。
T1：调整 region table，尝试增加 region、拆分 region、替换不稳定 landmark 组合。
T2：在确认 region 定义合理后，再考虑边界路径策略、patch 选择策略或参数调整。
```

具体原则：

1. 先对比同一样本、同一区域的 raw / repaired / salvaged 三张图。
2. raw FAIL 先看 `salvage_rejection_reason`：`degenerate_faces` 和 `unmapped_ratio` 都说明不应靠补点硬救。
3. 对反复失败的共享边，周一继续推进人工 M 点方案，用解剖控制点约束最短路径。
4. 不把 `WARNING` 或 `FAIL` 区域直接填 NaN 后做 PCA。
5. W3 只使用多个样本在同一 region 上同时 `PASS` 的区域。

## 9. 输出文件说明

### remesh points

路径：

```text
output/parameterized_points_r24/raw/<sample>_<side>_remesh_points.csv
output/parameterized_points_r24/repaired/<sample>_<side>_remesh_points.csv
```

关键字段：

| 字段 | 含义 |
|---|---|
| `region_id` | 区域编号 |
| `region_point_id` | 区域内部固定点序 |
| `lambda_a/lambda_b/lambda_c` | 标准三角域重心坐标 |
| `u/v` | 标准 2D 参数坐标 |
| `source_face_index` | 该点落入的源 UV face |
| `is_unmapped` | 是否未成功映射 |
| `x/y/z` | 映射回 3D 后的坐标 |

W3 必须使用 `region_id + region_point_id` 对齐不同样本的点。

### remesh faces

路径：

```text
output/parameterized_points_r24/raw/<sample>_<side>_remesh_faces.csv
output/parameterized_points_r24/repaired/<sample>_<side>_remesh_faces.csv
```

faces 是固定 template faces。W3 不应重新 triangulate。

### region features

路径：

```text
output/parameterized_points_r24/raw/<sample>_<side>_region_features.csv
```

该表记录 landmark 三角形边长、周长、面积、内角、质心、法向和 landmark 吸附距离，满足 W2 “根据选取的特征点计算相关特征值”的交付要求。

### QC

路径：

```text
output/parameterized_points_r24/raw/<sample>_<side>_remesh_qc.csv
output/parameterized_points_r24/repaired/<sample>_<side>_remesh_qc.csv
output/qc_visualizations_r24/raw/qc_visualization_summary.csv
output/qc_visualizations_r24/repaired/qc_visualization_summary.csv
```

建议进入 W3 的最低条件：

```text
status == PASS
sample_point_count == expected_point_count
unmapped_count == 0
degenerate_faces == 0
```

## 10. 当前主线文件

| 文件 | 作用 |
|---|---|
| `ear_param/remesh.py` | 论文式 remesh 核心算法 |
| `ear_param/qc_visualization.py` | remesh QC 可视化 |
| `scripts/parameterize_ear_remesh.py` | W2 remesh 命令行入口 |
| `scripts/visualize_remesh_qc.py` | QC 可视化命令行入口 |
| `docs/remesh_usage_w2.md` | W2 使用说明 |
| `docs/qc_visualization_and_region_strategy.md` | QC 与 region table 优化策略 |
| `docs/w3_pca_average_ear_technical_route.md` | W3 PCA 平均耳技术路线 |

## 11. Legacy 代码说明

仓库中仍保留早期参数化采样/KDTree 插值路线：

```text
ear_param/core.py
ear_param/run.py
ear_param/synthetic.py
ear_param/visualization.py
scripts/parameterize_ear.py
tests/test_core.py
```

这些代码不是当前论文式 remesh 主线，但暂时不建议直接删除。原因是它们仍保留历史算法对照、模拟数据、旧数值工具测试和回退价值。等 W3 PCA 平均耳流程完成并稳定后，再单独做 legacy 清理。

详细评估见：

```text
docs/non_remesh_code_assessment.md
```

## 12. 测试

运行全部测试：

```powershell
python -m pytest -q
```

当前验证结果：

```text
91 passed
```

备注：可能出现 `.pytest_cache` warning，这是本地缓存目录问题，不影响测试通过。

## 13. W3 前置条件

W3 不应再读取原始高密度 mesh，也不应重新做 remesh。W3 的可信输入是 W2 合格输出：

```text
*_remesh_points.csv
*_remesh_faces.csv
*_remesh_qc.csv
```

当前不建议直接进入 W3 正式 PCA。原因是四个样本暂无共同 PASS region。下一阶段应先通过 T0/T1/T2 得到多个样本在同一 region 上同时 PASS 的数据。

W3 技术路线详见：

```text
docs/w3_pca_average_ear_technical_route.md
```

## 14. 文档维护规则

每次代码调整、功能开发、数据流程变化或 QC 结论变化后，都应同步更新：

1. `README.md`：记录当前项目真实状态、主命令、当前结论。
2. `docs/remesh_usage_w2.md`：记录 W2 使用方法、QC 判定和诊断流程。
3. `docs/qc_visualization_and_region_strategy.md`：记录 QC 证据、region table 调整策略。
4. `docs/w3_pca_average_ear_technical_route.md`：如果 W2 输出契约或 W3 前置条件变化，需要同步更新。

不要让 README 停留在旧样本、旧 region table 或旧结论上。
