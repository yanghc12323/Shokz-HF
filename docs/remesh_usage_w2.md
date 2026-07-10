# W2 Patch-Based Remesh 使用说明

> 适用阶段：W2 真实样本 remesh、QC 与 region table 优化  
> 更新时间：2026-07-10  
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

当前主线使用：

```text
T013_L
T076_L
T077_L
T078_L
```

当前 `config/region_table.csv` 包含 13 个 region，字段为：

```text
region_id,region_name,lm_a,lm_b,lm_c,resolution,use_for_pca
```

当前每个 region 的 `resolution=24`，所以每区：

```text
sample_point_count = 325
remesh_face_count = 576
```

最新 `region_table.csv` 已将 T009 的特征点组合调整为 `L18-L29-L30`，用于解决旧版 T009 在 r24 下持续 FAIL 的问题。

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

输出目录：

```text
output/parameterized_points_r24/raw/
output/parameterized_points_r24/repaired/
output/remesh_r24/raw/
output/remesh_r24/repaired/
```

每个样本会输出：

```text
<sample>_<side>_remesh_points.csv
<sample>_<side>_remesh_faces.csv
<sample>_<side>_region_features.csv
<sample>_<side>_remesh_qc.csv
```

raw 目录保留原始映射结果；repaired 目录保留补点后的结果。raw PASS 直接导出 PLY；raw WARNING 在补点成功后导出 repaired PLY；raw FAIL 不补点、不导出。

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
```

每个 region 会输出 raw 和 repaired 两张图：

1. raw 图显示未修补前的原始映射状态，红色叉号表示 raw unmapped 点。
2. repaired 图显示补点后的状态，橙色三角表示 repaired 点，红色叉号表示仍未修补点。
3. 两张图都包含 3D patch faces、三条 boundary path、三个 landmark 点、2D UV patch 和 template sample 点。

QC 图的用途是定位问题原因，而不是直接调阈值。

## 6. 当前 QC 结果

历史 r8 四样本 baseline：

```text
T013_L: PASS=2, WARNING=10, FAIL=1
T076_L: PASS=2, WARNING=11, FAIL=0
T077_L: PASS=3, WARNING=10, FAIL=0
T078_L: PASS=3, WARNING=9,  FAIL=1
共同 PASS region: 0
完全无 FAIL region: 12
```

当前 r24 四样本结果：

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

注意：remesh CLI 与 QC 可视化使用同一套 raw PASS/WARNING/FAIL 判定规则。统一规则为：无 unmapped 且无 degenerate 为 PASS；少量 unmapped 为 WARNING；unmapped 比例超过 20% 或存在 degenerate face 为 FAIL。repaired 层只处理 raw WARNING，不处理 raw FAIL。

关键变化：

```text
T009 新组合 L18-L29-L30:
T013_L raw unmapped=1/325,  repaired PASS
T076_L raw unmapped=4/325,  repaired PASS
T077_L raw unmapped=51/325, repaired PASS
T078_L raw unmapped=6/325,  repaired PASS

当前剩余 FAIL:
T076_L / T008: raw unmapped=113/325, repaired FAIL
```

r24 repaired 输出说明：少量 unmapped 可以通过 landmark 替换和平滑插值补齐。当前 T009 已不再是 FAIL 区域；下一步应重点诊断 `T076_L / T008`。

## 7. QC 判定规则

当前 region 可进入后续 W3 的最低条件：

```text
status == PASS
sample_point_count == expected_point_count
unmapped_count == 0
degenerate_faces == 0
```

如果 `unmapped_count > 0`，对应的 `x/y/z` 会出现 NaN，该 region 不能直接进入 PCA。

`flipped_faces` 不能单独作为失败依据。某些 PASS region 也可能有较高 `flipped_faces`，需要结合 `unmapped_count` 和 `degenerate_faces` 判断。

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

这些 region 才能作为 W3 的第一批候选输入。

## 10. 文档维护

每次发生以下变化时，必须同步更新 README 和相关 docs：

1. 新增脚本或功能。
2. 改变输入/输出文件格式。
3. 更新有效样本列表。
4. 更新 region table。
5. 得到新的 QC 结论。
6. 改变 W3 前置条件或技术路线。
