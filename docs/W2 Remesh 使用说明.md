# W2 Patch-Based Remesh 使用说明

> 适用阶段：W2 真实样本 remesh、QC 与 region table 优化
> 更新时间：2026-07-14
> 主入口：`scripts/parameterize_ear_remesh.py`
> QC 可视化入口：`scripts/visualize_remesh_qc.py`

## 1. 当前目标

W2 的目标是将 landmark 定义的三角区域从原始 3D mesh 中提取出来，参数化到统一 2D 标准三角域，在固定 template 上采样，再映射回 3D。最终每个合格 region 都应具有：

```text
固定点数
固定点序
固定 template faces
无 unmapped 点
可跨样本对齐
```

当前代码已经实现完整 remesh 主流程。当前工作重点是：用真实样本验证 `region_table.csv` 的稳定性，并修复不稳定 region。

## 2. 当前有效样本

当前主线以 `data/clean_mesh/` 与 `data/landmarks/` 中成对存在的真实样本为准。目前已有 28 个原始 mesh/landmark 完整配对；应由正式批处理逐一完成 remesh、salvage、Weld 和对齐门禁。

```text
当前已完成 W2/Weld 的历史处理批次包含 12 个样本，其中 11 个 PCA-ready，`T049_L` 为 Weld FAIL。其余配对样本不应因文件已存在而被视为已通过 W2。
```

当前 `config/region_table.csv` 包含 15 个 region，字段为：

```text
region_id,region_name,lm_a,lm_b,lm_c,resolution,use_for_pca
```

当前每个 region 的 `resolution=24`，所以每区：

```text
sample_point_count = 325
remesh_face_count = 576
```

T100_L 已退出当前正式批次，历史上的退化面问题仅保留为诊断案例。若新样本出现 `degenerate_faces > 0`，raw 仍为 FAIL；但原始退化比例不超过 1.5% 时，salvaged 层会尝试局部 UV 修补。只有修补后 `degenerate_after=0` 且最终几何验证通过，才可能继续进入整耳与 PCA 门禁。

## 3. VSCode 命令行运行方式

1. 在 VSCode 中打开文件夹 `D:\YHC\人头项目`。
2. 打开 `Terminal -> New Terminal`。
3. 确认终端位置是项目根目录；如果不是，运行：

```powershell
cd D:\YHC\人头项目
```

4. 安装依赖：

```powershell
pip install -r requirements.txt
```

5. 运行 remesh。

### 正式隔离全流程（桌面软件）

桌面软件执行从 W2 到 W3 的正式批处理时必须使用隔离模式，不能与旧的共享 `output/...` 目录混用。`--output-root` 是 opt-in 参数，只有显式传入才生效；指定目录必须不存在，或完全为空（不能含任何文件或子目录）。进程会原子创建 `<output-root>/.pipeline-reservation` 认领该目录；崩溃后标记有意保留，目录因此不再为空，下一次必须使用新的运行目录。使用以下正式命令：

```powershell
python scripts/run_full_pipeline.py `
  --reference-sample T076_L `
  --output-root output/pipeline_runs/full28_T076_20260715
```

此命令没有额外传 `--run_dir`，因此 `<output-root>` 集中保存全部 canonical、W2、QC、Weld、Alignment、PCA、汇总、日志和 manifest 产物：

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

固定参考耳目录名跟随实际的 `--reference-sample`，即 `aligned_reference_<reference-sample>` 与 `pca_reference_<reference-sample>_r24`；上面的 `T076_L` 是正式示例，未选择其他参考样本时仍使用该默认目录名。

不传 `--output-root` 时，所有阶段继续使用原有固定 `output/...` 目录；`--run_dir` 仍只控制批次汇总目录，不会重定向 W2、QC、Weld、对齐或 PCA 的阶段目录，旧命令和 `--run_dir` 语义保持不变。传入 `--output-root` 时只能省略 `--run_dir`，或让两者解析为同一路径；不同的 `--run_dir` 会被拒绝，manifest、CSV 汇总、日志和阶段产物都位于同一隔离根。桌面软件必须传 `--output-root`，不能依赖旧的共享输出模式。

## 4. 运行 Remesh

单样本运行：

```powershell
python scripts/parameterize_ear_remesh.py --sample_id T013 --side L --mesh data/clean_mesh/T013_L.ply --landmarks data/landmarks/T013_L_landmarks.csv
python scripts/parameterize_ear_remesh.py --sample_id T076 --side L --mesh data/clean_mesh/T076_L.ply --landmarks data/landmarks/T076_L_landmarks.csv
python scripts/parameterize_ear_remesh.py --sample_id T077 --side L --mesh data/clean_mesh/T077_L.ply --landmarks data/landmarks/T077_L_landmarks.csv
python scripts/parameterize_ear_remesh.py --sample_id T078 --side L --mesh data/clean_mesh/T078_L.ply --landmarks data/landmarks/T078_L_landmarks.csv
```

批量运行：

```powershell
$samples = "T013","T076","T077","T078"
foreach ($s in $samples) {
  python scripts/parameterize_ear_remesh.py --sample_id $s --side L --mesh "data/clean_mesh/${s}_L.ply" --landmarks "data/landmarks/${s}_L_landmarks.csv"
}
```

每次脚本结束时会打印本次样本的统计，并额外扫描输出目录里已有的全部 `*_remesh_qc.csv`，输出按样本汇总表。批量跑完最后一个样本后，终端最后的三张表就是当前批次的 raw、repaired、salvaged 总览：

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

输出目录：

```text
output/parameterized_points_r24/raw/
output/parameterized_points_r24/repaired/
output/parameterized_points_r24/salvaged/
output/remesh_r24/raw/
output/remesh_r24/repaired/
output/remesh_r24/salvaged/
```

每个样本会输出：

```text
<sample>_<side>_remesh_points.csv
<sample>_<side>_remesh_faces.csv
<sample>_<side>_region_features.csv
<sample>_<side>_remesh_qc.csv
```

raw 目录保留原始映射结果；repaired 目录保留 raw WARNING 补点后的结果；salvaged 目录保留对 raw FAIL 的保守抢救结果。raw PASS 直接导出 PLY；raw WARNING 在补点成功后导出 repaired PLY；满足安全限制的 raw FAIL 会在 salvaged 层尝试导出。

salvage 默认限制：

```text
--max_salvage_unmapped_ratio 0.35
--max_salvage_degenerate_ratio 0.015
raw degenerate ratio > 1.5% 时不尝试 UV 修补
unmapped 比例超过 0.35 时不 salvage
退化面数量不设绝对门槛；比例合格后在 salvaged 层修补
salvage_accepted=True 表示无 unmapped、degenerate_after=0、r24 最终面有效且 r48 覆盖验证通过，不等同于 raw PASS
```

## 5. 运行 QC 可视化

生成所有 region 的 QC 图：

```powershell
python scripts/visualize_remesh_qc.py --samples T013_L T076_L T077_L T078_L
```

只看重点区域：

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

每个 region 会输出 raw、repaired 和 salvaged 三张图：

1. raw 图显示未修补前的原始映射状态，红色叉号表示 raw unmapped 点。
2. repaired 图显示补点后的状态，橙色三角表示 repaired 点，红色叉号表示仍未修补点。
3. salvaged 图显示 raw FAIL 保守抢救后的状态；若进行了 UV 修补，标题会显示 `degenerate=修补前->修补后`，右侧为修补后的 UV 图。

正式批处理默认也遵循此诊断原则：即使一个样本的最终 `salvaged` 状态为 FAIL，仍会生成该样本的三层 QC 图。该 FAIL 状态只阻止样本进入后续 Weld、刚体对齐和 PCA，不应阻止失败原因的可视化。
4. 三张图都包含 3D patch faces、三条 boundary path、三个 landmark 点、2D UV patch 和 template sample 点。

QC 图的用途是定位问题原因，而不是直接调阈值。

## 6. 当前 QC 结果查看方式

注意：remesh CLI 与 QC 可视化使用同一套 raw PASS/WARNING/FAIL 判定规则。统一规则为：无 unmapped 且无 degenerate 为 PASS；少量 unmapped 为 WARNING；unmapped 比例超过 20% 或存在 degenerate face 为 FAIL。repaired 层只处理 raw WARNING；salvaged 层会在 raw unmapped 比例不超过 `--max_salvage_unmapped_ratio` 且 raw degenerate ratio 不超过 `--max_salvage_degenerate_ratio` 时，先尝试局部 UV 修补，再执行角点替换和平滑插值。

当前结果以最新 CSV 为准：

```text
output/parameterized_points_r24/raw/<sample>_L_remesh_qc.csv
output/parameterized_points_r24/repaired/<sample>_L_remesh_qc.csv
output/parameterized_points_r24/salvaged/<sample>_L_remesh_qc.csv
```

salvaged QC 中重点看：

```text
raw_status
salvaged_unmapped_count
salvage_attempted
salvage_accepted
salvage_rejection_reason
degenerate_ratio
degenerate_before
degenerate_after
degenerate_salvage_attempted
degenerate_salvage_accepted
degenerate_salvage_method
degenerate_salvage_rejection_reason
patch_face_count
mesh_exported
```

r24 repaired/salvaged 输出说明：少量 unmapped 可以通过 landmark 替换和平滑插值补齐；比例合格的 source UV 退化会在 salvaged 层先做局部 UV 松弛并重新映射。`degenerate_faces` 是原始诊断值，`degenerate_after` 是最终门禁值。`salvaged` 是 W2 不可改写的 region 级基线，不直接作为 PCA 文件；后续仍需经过整耳焊接、共享边修补、刚体对齐和相应 QC。

## 7. QC 判定规则

当前 region 可作为后续整耳构建输入的最低条件：

```text
status == PASS
sample_point_count == expected_point_count
unmapped_count == 0
degenerate_after == 0（旧输出没有该列时检查 degenerate_faces）
```

如果 `unmapped_count > 0`，对应的 `x/y/z` 会出现 NaN，该 region 不能直接进入 PCA。

`flipped_faces` 不能单独作为失败依据。某些 PASS region 也可能有较高 `flipped_faces`，需要结合 `unmapped_count`、`degenerate_after` 和最终模板面质量判断。

## 8. 当前问题判断

目前不建议优先通过调高 `resolution` 或放宽 QC 解决问题。

原因：

1. 当前失败主要是 patch 覆盖不足或 patch 退化，不是采样精度不足。
2. 如果 patch 没有覆盖完整标准三角域，提高 `resolution` 只会生成更多 template 点，可能产生更多 unmapped 点。
3. 放宽 QC 或填充 NaN 会污染 W3 PCA 输入。

当前更可能的原因：

1. `region_table.csv` 中某些 landmark 三角组合不稳定。
2. mesh 上的最短路径 boundary 可能抄近路，不等于解剖边界。
3. 三条 boundary path 可能形成过窄或退化 patch。
4. patch component 选择策略可能需要更强的面积、覆盖率或闭环约束。

## 9. 当前处理策略

按以下优先级推进：

```text
T0：继续用更多真实样本验证 region table。
T1：调整 region table，尝试增加 region、拆分 region、替换不稳定 landmark 组合。
T2：在 region 定义合理后，再调边界路径、patch 选择或其它参数。
```

短期目标：

```text
至少找到若干 region，使它们在多个真实样本上全部 PASS。
```

这些 region 才能作为整耳构建的第一批候选输入。是否进入 W3 还取决于 17 条共享边的 weld QC、共享边修补审计和刚体对齐 QC。

## 10. W2 到整耳流程的交付

当前整耳构建正式使用 `salvaged` 层，而不是 raw 或 repaired 层：

```text
output/parameterized_points_r24/salvaged/<sample>_L_remesh_points.csv
output/parameterized_points_r24/salvaged/<sample>_L_remesh_faces.csv
output/parameterized_points_r24/salvaged/<sample>_L_remesh_qc.csv
```

运行整耳构建：

```powershell
python scripts/build_whole_ear.py --input_dir output/parameterized_points_r24/salvaged --regions config/region_table.csv --out_dir output/whole_ear_r24/salvaged
```

该步骤不会改变 W2 的 raw/repaired/salvaged 文件。它利用 `region_table.csv` 建立一次性的全局模板，把同一 landmark 角点和共享 landmark 边上的对应采样点绑定为唯一 `global_vertex_id`，输出 welded PLY 和焊接 QC。此命令只生成不可改写的 `output/whole_ear_r24/salvaged` 基线。

焊接 QC 不会把所有 pre-weld 距离都当作失败：当一侧是可靠 mapped 点、另一侧是 salvaged 修补点时，mapped 坐标作为权威边界，位移记入 `max_replacement_distance_mm`；只有 mapped-mapped 不一致或两侧都缺少 mapped 权威坐标时，差异才记入 `max_conflict_distance_mm` 并参与 PASS/WARNING/FAIL。

随后建立独立共享边修补层：

```powershell
python scripts/build_whole_ear.py --input_dir output/parameterized_points_r24/salvaged --regions config/region_table.csv --mesh_dir data/clean_mesh --enable_edge_repair --out_dir output/whole_ear_r24/weld_repaired
```

修补层只处理 baseline 的局部 WARNING 共享边：通常两侧 raw region 不能 FAIL、最终不能有退化面、冲突必须是 1--2 个连续的 repaired-only 点且两侧都有可信锚点。唯一例外是 raw FAIL 由低比例 UV 退化引起、且 `degenerate_salvage_accepted=True`、`degenerate_after=0` 的 region；它已在 salvaged 层完成严格验收，可参与共享边修补。程序按锚点插值、投影回原始 mesh，并同时更新两个相邻 region 的边界副本；`<sample>_edge_repair_qc.csv` 会完整记录是否修补、锚点、投影距离与拒绝原因。缺失或非有限候选坐标会写为 `non_finite_candidate`，不做自动修补。启用修补时不指定 `--out_dir` 会默认输出 `weld_repaired`，且程序拒绝覆盖 `salvaged` 基线。

历史 12 样本批次中，T066_L、T094_L 与 T097_L 的 baseline WARNING 经保守共享边修补后转为 PASS；当前 `weld_repaired` 为 11 PASS/PCA_READY、1 FAIL。T094_L 的 L20-L21 index 1（0.4135 mm）和 T097_L 的 L21-L29 index 23（0.3098 mm）均修补为 0。T049_L 的 L13-L17 因相邻 T003 raw FAIL 而保留 FAIL，不会自动纳入 PCA。28 样本全流程完成后，应以新的 batch summary 覆盖本段历史统计。

最后只对 `weld_repaired` 中 `pca_ready=True` 的整耳做刚体对齐：

```powershell
python scripts/align_whole_ear.py --whole_ear_dir output/whole_ear_r24/weld_repaired --landmarks_dir data/landmarks --out_dir output/whole_ear_r24/aligned_weld_repaired
```

后续 W3 只读取 `aligned_weld_repaired` 中 alignment PASS 的整耳点、固定 faces 与 `alignment_qc_summary.csv`。

## 11. 文档维护

每次发生以下变化时，必须同步更新 README 和相关 docs：

1. 新增脚本或功能。
2. 改变输入/输出文件格式。
3. 更新有效样本列表。
4. 更新 region table。
5. 得到新的 QC 结论。
6. 改变 W3 前置条件或技术路线。
7. 修改共享边修补规则、输出层或修补结果。
