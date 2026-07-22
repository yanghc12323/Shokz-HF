# 3D Ear Cross-Parameterisation with Patch-Based Remesh

> 当前主线：论文式 patch-based remesh
> 当前阶段：W2/W3 核心功能已完成；已完成 11 样本 GPA/T076 PCA 首轮对比，28 样本全流程验证待运行
> 更新时间：2026-07-14

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

原始输入样本以 `data/clean_mesh/` 与 `data/landmarks/` 中成对存在的文件为准。目前已有 28 个完整配对样本：

```text
T001_L, T002_L, T003_L, T004_L, T005_L, T006_L, T007_L,
T008_L, T009_L, T010_L, T013_L, T049_L, T052_L, T054_L,
T057_L, T058_L, T061_L, T065_L, T066_L, T068_L, T069_L,
T076_L, T077_L, T078_L, T088_L, T094_L, T097_L, T099_L
```

当前 `config/region_table.csv` 包含 15 个三角 region，每个 region 当前 `resolution=24`，即每区 325 个 template 点、576 个 template faces。正式整耳输入采用 `salvaged` 层，再由独立 `weld_repaired` 层完成保守共享边修补。

当前已完成 W2 salvage、Weld 和刚体对齐门禁的仍是 12 个历史处理样本，其中 11 个为 PCA-ready，`T049_L` 为 Weld FAIL。其余原始配对样本尚待本轮全流程批处理验证；原始配对存在不等于可以进入 PCA。

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

### Windows 桌面软件

安装桌面依赖后，可在开发环境启动中文工程工作台：

```powershell
python -m pip install -r requirements-desktop.txt
python -m desktop_app
```

构建可双击启动的 Windows 程序：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_desktop.ps1
```

详细流程见 `docs/桌面工程软件使用说明.md`。原有 CLI 命令仍是分析基线，保持可用。

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

批量运行时，每个样本结束都会扫描当前输出目录中的所有 `*_remesh_qc.csv`，并在终端最后打印按样本汇总表。跑完最后一个样本后，终端末尾会看到类似：

```text
[Remesh] Raw sample summary:
sample_tag  PASS  WARNING  FAIL  TOTAL
    T013_L     8        5     2     15
    T076_L     7        6     2     15

[Remesh] Repaired sample summary:
sample_tag  PASS  WARNING  FAIL  TOTAL
    T013_L    13        0     2     15
    T076_L    12        0     3     15

[Remesh] Salvaged sample summary:
sample_tag  PASS  WARNING  FAIL  TOTAL
    T013_L    14        0     1     15
    T076_L    13        0     2     15
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
--max_salvage_degenerate_ratio 0.015
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
raw unmapped ratio > --max_salvage_unmapped_ratio：不 salvage
raw degenerate ratio > --max_salvage_degenerate_ratio：不尝试 UV 修补
默认 --max_salvage_unmapped_ratio = 0.35
默认 --max_salvage_degenerate_ratio = 0.015（1.5%）
退化面数量不设绝对门槛；比例合格后在 salvaged 层做局部 UV 修补
salvage_accepted=True 必须同时满足：无 unmapped、degenerate_after=0、r24 最终面有效、r48 加密覆盖验证通过
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
3. `salvaged` 图：显示对 raw FAIL 进行保守 salvage 后的结果；若进行了 UV 退化修补，标题会显示 `degenerate=修补前->修补后`，右侧显示修补后的 UV 图。

三张图左侧都显示 3D patch faces、三条 landmark boundary path 和三个 landmark 点；右侧都显示 2D UV patch 与固定 template samples。

这些图用于判断 region 失败到底是 landmark 组合问题、边界最短路径问题、patch 过窄问题，还是 UV 覆盖问题。

## 7. 当前 QC 结果

`scripts/parameterize_ear_remesh.py` 与 `scripts/visualize_remesh_qc.py` 使用同一套 raw PASS/WARNING/FAIL 判定规则。统一规则为：无 unmapped 且无 degenerate 为 PASS；少量 unmapped 为 WARNING；unmapped 比例超过 20% 或存在 degenerate face 为 FAIL。

repaired 层只处理 raw WARNING：标准三角形角点 unmapped 优先用对应吸附 landmark 替换，其余少量 unmapped 点用模板网格上的平滑插值填补。salvaged 层在相同修补算法基础上，额外允许原始退化比例不超过 1.5% 的 raw FAIL 尝试局部 UV 修补，再重新映射与补点；不会新增第四层输出。

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
4. `degenerate_faces` 始终记录原始 source UV 退化数；salvaged 是否可用必须看 `degenerate_after`。只有 `degenerate_after=0` 且 `salvage_accepted=True` 才可继续进入整耳。
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
2. raw FAIL 先看 `salvage_rejection_reason`：`degenerate_ratio` 表示原始退化比例超过 1.5%，`unmapped_ratio` 表示未映射比例超过 0.35；二者都不进入自动 salvage。
3. 对反复失败的共享边，周一继续推进人工 M 点方案，用解剖控制点约束最短路径。
4. 不把 `WARNING` 或 `FAIL` 区域直接填 NaN 后做 PCA。
5. W3 不再直接读取独立 region；只使用整耳焊接 `pca_ready=True` 且刚体对齐 `status=PASS` 的样本。

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
degenerate_after == 0（salvaged QC；旧输出没有此列时退回检查 degenerate_faces）
```

## 10. 构建整耳并统一坐标系

正式输入固定为 W2 `salvaged` 层。全局模板按 landmark 身份和共享 landmark 边建立，不按三维距离猜测合并点；当前模板每个样本固定为 4453 个唯一顶点、8640 个三角面和 17 条共享边。每个 region 的局部面必须与其 resolution 对应的标准细分模板逐面一致，否则整耳直接标记为 FAIL。`salvaged` 是不可改写的基线证据；正式 PCA 输入来自其后的独立 `weld_repaired` 层。

先构建整耳并运行焊接 QC：

```powershell
python scripts/build_whole_ear.py --input_dir output/parameterized_points_r24/salvaged --regions config/region_table.csv --out_dir output/whole_ear_r24/salvaged
```

再建立保守的共享边修补层。它只修补局部 WARNING：双方均为修补点、连续长度不超过 2、存在可信锚点且投影回原始 mesh 后冲突不超过 0.25 mm。通常两侧 raw 状态均不能为 FAIL；唯一例外是低比例 UV 退化已在 salvaged 层完成修补并记录 `degenerate_salvage_accepted=True`、`degenerate_after=0` 的 region。未完成该严格验收的 raw FAIL 仍不会被放行。

```powershell
python scripts/build_whole_ear.py --input_dir output/parameterized_points_r24/salvaged --regions config/region_table.csv --mesh_dir data/clean_mesh --enable_edge_repair --out_dir output/whole_ear_r24/weld_repaired
```

最后对 `weld_repaired` 中 `PCA_READY` 整耳做刚体 Generalized Procrustes / Kabsch：

```powershell
python scripts/align_whole_ear.py --whole_ear_dir output/whole_ear_r24/weld_repaired --landmarks_dir data/landmarks --out_dir output/whole_ear_r24/aligned_weld_repaired
```

焊接 QC 区分两类距离：

1. `max_replacement_distance_mm`：一侧是原始 mapped、另一侧是 salvaged 修补点时，用 mapped 边界替换修补边界所需的位移；它被完整记录，但不等同于可靠边界冲突。
2. `max_conflict_distance_mm`：两侧同为 mapped，或两侧都没有 mapped 权威坐标时的差异；PASS/WARNING/FAIL 使用该值判断，默认阈值为 0.25/1.00 mm。

当前 `weld_repaired` whole-ear 结果：

```text
PASS / PCA_READY: T013_L, T066_L, T068_L, T069_L, T076_L, T077_L, T078_L, T088_L, T094_L, T097_L, T099_L
FAIL:             T049_L（L13-L17 邻接 T003 raw FAIL，自动修补被拒绝）
```

T066_L、T094_L 和 T097_L 的 baseline WARNING 已在独立 `weld_repaired` 层经过保守共享边修补后转为 PASS。11 个 `PCA_READY` 样本均已完成刚体对齐，GPA 均收敛，所有 `det(R)=1`，最大 mesh 边长保持误差约为 `1.84e-14 mm`。

## 11. 当前主线文件

| 文件 | 作用 |
|---|---|
| `ear_param/remesh.py` | 论文式 remesh 核心算法 |
| `ear_param/qc_visualization.py` | remesh QC 可视化 |
| `scripts/parameterize_ear_remesh.py` | W2 remesh 命令行入口 |
| `scripts/visualize_remesh_qc.py` | QC 可视化命令行入口 |
| `ear_param/whole_ear.py` | 全局模板、共享边坐标选择与焊接 QC |
| `scripts/build_whole_ear.py` | 整耳构建、共享边修补、PLY/CSV/QC 图批处理入口 |
| `ear_param/alignment.py` | 刚体 Kabsch、GPA 与固定参考耳对齐 |
| `scripts/align_whole_ear.py` | GPA 或固定参考耳的整耳坐标统一与对齐 QC 入口 |
| `ear_param/pca_average.py` | W3 输入门禁、PCA、平均耳与模式网格导出 |
| `scripts/build_average_ear.py` | W3 PCA 与平均耳命令行入口 |
| `docs/W2 Remesh 使用说明.md` | W2 使用说明 |
| `docs/整耳全局模板、边界焊接与刚体统一坐标系.md` | 整耳焊接与坐标统一说明 |
| `docs/0711-Remesh QC 可视化与 Region Table 优化策略.md` | QC 与 region table 优化策略 |
| `docs/W3 PCA 与平均耳技术路线.md` | W3 PCA 平均耳技术路线 |

## 12. 项目范围

本仓库仅保留论文式 patch-based remesh、W2 质量控制、整耳焊接、共享边修补和刚体坐标统一主线。早期 KDTree 参数化采样路线及其旧命令行、模拟数据、可视化、校验脚本和测试已移除；它们不能作为 remesh 失败时的回退方案，也不能作为 W3 PCA 输入。

`docs/archive/` 仅保存阶段性汇报和开发实施记录，方便追溯，不应作为当前流程的使用说明或 AI 实现依据。当前项目规范以 README、W2 使用说明、整耳 Weld/坐标说明、W3 技术路线和 GPA/T076 对比文档为准。

当前通用的二维标准三角形采样网格由 `ear_param/remesh.py` 直接维护，仍保持每个 resolution 的固定点数与点序。

## 13. 测试

运行当前主线测试：

```powershell
python -m pytest tests -q
```

当前验证结果：

```text
66 passed
```

备注：可能出现 `.pytest_cache` warning，这是本地缓存目录问题，不影响测试通过。

## 14. W3 PCA 与平均耳

### 正式全流程批处理

批处理以左耳 `L` 为标准侧：L 输入不变；R 输入在 remesh 前沿默认 X 轴镜像，并反转三角面绕序。原始输入不改写。桌面隔离正式批处理将标准化 PLY、landmark 与审计 JSON 保存于 `<output-root>/canonical_inputs_r24/`；未传 `--output-root` 的 legacy CLI 模式才保存于 `output/canonical_inputs_r24/`。R 样本仍保留 `_R` 标签，但其几何已处于 canonical L 坐标系。

扫描 `data/clean_mesh/` 与 `data/landmarks/` 中所有同名配对样本，并依次运行 remesh、salvage、整耳 Weld repair、GPA 对齐与 GPA-PCA：

```powershell
python scripts/run_full_pipeline.py
```

每个样本的错误不会中断其他样本。终端会显示阶段进度和最终总表；同一批的 CSV 与日志保存在 `output/pipeline_runs/<时间戳>/`。完整区域级 QC 图会显著增加运行时间；日常快速复核可显式跳过绘图：

```powershell
python scripts/run_full_pipeline.py --skip-remesh-qc
```

默认不使用 `--skip-remesh-qc` 时，只要 remesh 阶段已完成，都会生成 raw、repaired、salvaged 三层 region QC 图；这也包括 `salvaged=FAIL` 的样本，便于定位失败区域。`salvaged=FAIL` 仍会被严格阻止进入 Weld、刚体对齐和 PCA。

如需同时保留固定参考耳坐标系下的独立 PCA 分支，指定一个已通过 Weld 的参考样本。该命令仍会运行 GPA-PCA；两条分支分别写入独立目录，绝不混合输入：

```powershell
python scripts/run_full_pipeline.py --reference-sample T076_L
```

### 桌面软件的隔离运行

桌面软件启动正式批处理时必须使用隔离模式，避免与旧的共享 `output/...` 目录互相覆盖。`--output-root` 是 opt-in 参数：只有显式传入才启用；目标目录必须不存在，或完全为空（不能含任何文件或子目录）。进程认领该目录时会原子创建 `<output-root>/.pipeline-reservation`；若进程崩溃，该标记会有意保留并使目录保持非空，下一次必须改用新的运行目录。正式运行使用：

```powershell
python scripts/run_full_pipeline.py `
  --reference-sample T076_L `
  --output-root output/pipeline_runs/full28_T076_20260715
```

上面命令未另传 `--run_dir`，因此该 `output-root` 同时容纳所有 canonical、W2、QC、Weld、Alignment、PCA、汇总、日志和 manifest 产物：

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
  whole_ear_r24/{weld_repaired,aligned_gpa,aligned_reference_T076_L}/
  pca_gpa_r24/
  pca_reference_T076_L_r24/
```

固定参考耳目录名跟随实际的 `--reference-sample`：隔离模式使用 `aligned_reference_<reference-sample>` 与 `pca_reference_<reference-sample>_r24`。上面的 `T076_L` 是正式示例；未选择其他参考样本时，目录名仍以 `T076_L` 为默认形式。

不传 `--output-root` 时，所有阶段继续使用原有固定 `output/...` 目录；`--run_dir` 仍只控制批次汇总目录，不会重定向各阶段输出，旧命令与 `--run_dir` 工作流保持不变。传入 `--output-root` 时只能省略 `--run_dir`，或让两者解析为同一路径；不同的 `--run_dir` 会被拒绝，manifest、CSV 汇总、日志和全部阶段产物都必须位于同一隔离根。桌面软件必须传 `--output-root`，不能依赖旧的共享输出模式。

W3 不应再读取原始高密度 mesh，也不应重新做 remesh。正式整耳 PCA 的可信输入必须与运行模式对应。

桌面软件隔离模式（传入 `--output-root`）读取：

```text
<output-root>/whole_ear_r24/aligned_gpa/<sample>_aligned_whole_ear_points.csv
<output-root>/whole_ear_r24/aligned_gpa/<sample>_aligned_whole_ear_faces.csv
<output-root>/whole_ear_r24/aligned_gpa/alignment_qc_summary.csv

<output-root>/whole_ear_r24/aligned_reference_T076_L/<sample>_aligned_whole_ear_points.csv
<output-root>/whole_ear_r24/aligned_reference_T076_L/<sample>_aligned_whole_ear_faces.csv
<output-root>/whole_ear_r24/aligned_reference_T076_L/alignment_qc_summary.csv
```

未传 `--output-root` 的 legacy CLI 模式才读取原有固定路径：

```text
output/whole_ear_r24/aligned_weld_repaired/<sample>_aligned_whole_ear_points.csv
output/whole_ear_r24/aligned_weld_repaired/<sample>_aligned_whole_ear_faces.csv
output/whole_ear_r24/aligned_weld_repaired/alignment_qc_summary.csv
```

其中 legacy CLI 的固定参考耳分支对应读取：

```text
output/whole_ear_r24/aligned_reference_weld_repaired/<sample>_aligned_whole_ear_points.csv
output/whole_ear_r24/aligned_reference_weld_repaired/<sample>_aligned_whole_ear_faces.csv
output/whole_ear_r24/aligned_reference_weld_repaired/alignment_qc_summary.csv
```

GPA 坐标系适用于群体 PCA 与平均耳；固定参考耳坐标系适用于工程展示、测量和对齐标准敏感性比较。两条路径均只使用旋转和平移。

固定参考耳目录还会为每个样本额外导出同坐标的 `*_aligned_whole_ear.obj` 与 `*_aligned_whole_ear.stl`，供工程软件查看；PCA 仍读取 points/faces CSV。

只有上游 `weld_repaired` 的 `weld_qc_summary.csv` 中 `pca_ready=True`、`input_layer=weld_repaired`，且对齐 QC 为 PASS 的样本可以进入正式 PCA。W3 还会逐样本验证有限坐标、`global_vertex_id` 点序和 faces 完全一致；不合格样本会记录到 `pca_input_manifest.csv`，不会静默混入。

单独重跑 PCA 时也必须保持同一模式。隔离模式使用本次运行的 `<output-root>`，不能写回共享目录：

```powershell
python scripts/build_average_ear.py --aligned_dir <output-root>/whole_ear_r24/aligned_gpa --weld_dir <output-root>/whole_ear_r24/weld_repaired --out_dir <output-root>/pca_gpa_r24 --variance_threshold 0.75
```

固定参考耳分支将上例的 `aligned_gpa` 与 `pca_gpa_r24` 分别替换为 `aligned_reference_<reference-sample>` 与 `pca_reference_<reference-sample>_r24`；正式 `T076_L` 示例对应 `aligned_reference_T076_L` 与 `pca_reference_T076_L_r24`。以下命令仅用于未传 `--output-root` 的 legacy CLI 模式：

```powershell
python scripts/build_average_ear.py --aligned_dir output/whole_ear_r24/aligned_weld_repaired --weld_dir output/whole_ear_r24/weld_repaired --out_dir output/w3_pca_r24 --variance_threshold 0.75
```

本次首轮真实运行纳入 11 个样本，输出 4453 顶点、8640 面的平均耳 `output/w3_pca_r24/mean_whole_ear.ply`。前三个主成分累计解释 75.35% 的差异，因此按 75% 阈值保留 3 个主成分。样本量仍处于流程验证阶段，不应将当前模式解释为稳定总体模型。

W3 技术路线详见：

```text
docs/W3 PCA 与平均耳技术路线.md
```

## 15. 文档维护规则

每次代码调整、功能开发、数据流程变化或 QC 结论变化后，都应同步更新：

1. `README.md`：记录当前项目真实状态、主命令、当前结论。
2. `docs/W2 Remesh 使用说明.md`：记录 W2 使用方法、QC 判定和诊断流程。
3. `docs/0711-Remesh QC 可视化与 Region Table 优化策略.md`：记录 QC 证据、region table 调整策略。
4. `docs/W3 PCA 与平均耳技术路线.md`：记录 W3 输入契约、命令、输出和实际结果。

不要让 README 停留在旧样本、旧 region table 或旧结论上。
# CLI 全流程运行（新版 MQ 输入）

在项目根目录运行。`--parallel-workers 0` 为自动并行（最多 4），也可明确指定
`1`、`2` 或 `4`；固定参考耳使用 `MQ_S068L`。

```powershell
python scripts\run_full_pipeline.py `
  --mesh_dir data\clean_mesh `
  --landmarks_dir data\landmarks `
  --regions config\region_table.csv `
  --parallel-workers 4 `
  --reference-sample MQ_S068L `
  --output-root output\runs\mq_full_20260722
```

`--output-root` 必须是不存在或空目录。运行完成后，该目录包含 manifest、日志、QC、
整耳、配准和 PCA 结果。
