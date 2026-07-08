# W2 Patch-Based Remesh 使用说明

> 适用阶段：W2 真实样本 remesh、QC 与 region table 优化  
> 更新时间：2026-07-08  
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

当前每个 region 的 `resolution=8`，所以每区：

```text
sample_point_count = 45
remesh_face_count = 64
```

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
output/parameterized_points/
output/remesh/
```

每个样本会输出：

```text
<sample>_<side>_remesh_points.csv
<sample>_<side>_remesh_faces.csv
<sample>_<side>_region_features.csv
<sample>_<side>_remesh_qc.csv
```

只有 `unmapped_count == 0` 的 region 会输出 PLY。

## 5. 运行 QC 可视化

生成所有 region 的 QC 图：

```powershell
python scripts/visualize_remesh_qc.py --samples T013_L T076_L T077_L T078_L
```

只看重点区域：

```powershell
python scripts/visualize_remesh_qc.py --samples T013_L T076_L T077_L T078_L --region_ids T005 T009
```

输出：

```text
output/qc_visualizations/<sample_tag>/<region_id>_qc.png
output/qc_visualizations/qc_visualization_summary.csv
```

每张图包括：

1. 3D patch faces。
2. 三条 boundary path。
3. 三个 landmark 点。
4. 2D UV patch。
5. template sample 点。
6. 红色 unmapped 点。

QC 图的用途是定位问题原因，而不是直接调阈值。

## 6. 当前四样本 QC 结果

本次四个真实样本都已完成 remesh 和 QC 可视化：

```text
T013_L: PASS=2, WARNING=10, FAIL=1
T076_L: PASS=2, WARNING=11, FAIL=0
T077_L: PASS=3, WARNING=10, FAIL=0
T078_L: PASS=0, WARNING=0,  FAIL=13
共同 PASS region: 0
完全无 FAIL region: 0
```

注意：普通 remesh CLI 中 `T078_L / T005` 为 `WARNING`，但 QC 可视化汇总中为 `FAIL`，原因是它存在 `degenerate_faces=1`。进入 W3 前应使用更严格的 QC 可视化汇总。

T078 的关键异常：

```text
多数 region: patch_face_count=1, unmapped_count=45, degenerate_faces=1
T005: patch_face_count=1215, unmapped_count=2, degenerate_faces=1
T009: patch_face_count=161, unmapped_count=16, degenerate_faces=0
```

T078 的 landmark 到 mesh 最近距离正常，因此不优先判断为坐标系整体错配。更可能的问题是当前 region table 在 T078 形态上不稳定，或最短路径 boundary 围出了错误或退化 patch。

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
