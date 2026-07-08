# 3D Ear Cross-Parameterisation with Patch-Based Remesh

> 当前主线：论文式 patch-based remesh  
> 当前阶段：W2 已形成可运行闭环，W3 PCA 平均耳待实现  
> 更新时间：2026-07-08

## 1. 项目目标

本项目用于将不同受试者的 3D 耳朵模型转换为可跨样本统计分析的统一表达。

核心问题是：不同人的耳朵 mesh 顶点数、面片拓扑和局部形态都不同，不能直接把原始 mesh 顶点堆叠后做 PCA。项目当前采用论文式 remesh 路线：

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

这样每个样本、每个区域都有相同数量、相同顺序、相同拓扑关系的采样点，可用于后续 PCA、平均耳和形态特征分析。

## 2. 当前状态

### W2 已完成

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
11. 用 QC 判断 region 是否可进入 W3。

### W3 待实现

W3 任务是：

> 对所有模型进行 PCA 计算，选取能够解释 75% 方差的特征值，计算平均值，从 2D 平面映射回 3D，得到平均耳。

W3 技术路线详见：

```text
docs/w3_pca_average_ear_technical_route.md
```

## 3. 推荐快速开始

### 3.1 安装依赖

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

### 3.2 准备输入

当前真实测试数据示例：

```text
data/clean_mesh/T001_L.ply
data/landmarks/T001_L_landmarks.csv
config/region_table.csv
```

说明：当前 T001 是左耳数据，因此文件名、运行参数和输出都统一使用 `T001_L`。

`landmarks` 必须至少包含：

```text
landmark_id,x,y,z
```

`region_table.csv` 必须包含：

```text
region_id,region_name,lm_a,lm_b,lm_c,resolution,use_for_pca
```

当前 `config/region_table.csv` 示例：

```csv
region_id,region_name,lm_a,lm_b,lm_c,resolution,use_for_pca
T001,test,L9,L16,L18,8,1
```

### 3.3 运行 W2 remesh

在项目根目录运行：

```powershell
python scripts/parameterize_ear_remesh.py --sample_id T001 --side L --mesh data/clean_mesh/T001_L.ply --landmarks data/landmarks/T001_L_landmarks.csv
```

默认参数：

```text
--regions config/region_table.csv
--out_dir output/parameterized_points
--mesh_out_dir output/remesh
```

### 3.4 查看输出

运行后生成：

```text
output/parameterized_points/T001_L_remesh_points.csv
output/parameterized_points/T001_L_remesh_faces.csv
output/parameterized_points/T001_L_region_features.csv
output/parameterized_points/T001_L_remesh_qc.csv
output/remesh/T001_L/T001_remesh.ply
```

当前 T001_L 实测结果：

```text
sample_point_count = 45
expected_point_count = 45
remesh_face_count = 64
unmapped_count = 0
degenerate_faces = 0
status = PASS
```

## 4. 输出文件说明

### 4.1 remesh points

路径：

```text
output/parameterized_points/<sample>_<side>_remesh_points.csv
```

主要字段：

| 字段 | 含义 |
|---|---|
| `point_id` | 样本级点 ID |
| `sample_id` | 样本编号 |
| `side` | 左右耳标记 |
| `region_id` | 区域编号 |
| `region_name` | 区域名称 |
| `region_point_id` | 区域内部固定点序 |
| `lambda_a/lambda_b/lambda_c` | 标准三角域重心坐标 |
| `u/v` | 标准 2D 参数坐标 |
| `source_face_index` | 该点落入的源 UV face |
| `is_unmapped` | 是否未成功映射 |
| `x/y/z` | 映射回 3D 后的坐标 |

W3 PCA 必须使用 `region_id + region_point_id` 对齐不同样本的点。

### 4.2 remesh faces

路径：

```text
output/parameterized_points/<sample>_<side>_remesh_faces.csv
```

主要字段：

| 字段 | 含义 |
|---|---|
| `face_id` | 区域内 remesh face 编号 |
| `local_v0/local_v1/local_v2` | 区域内部顶点索引 |
| `global_v0/global_v1/global_v2` | 样本级全局顶点索引 |

faces 是固定 template faces，不应在 W3 中重新 triangulate。

### 4.3 region features

路径：

```text
output/parameterized_points/<sample>_<side>_region_features.csv
```

主要字段：

| 字段 | 含义 |
|---|---|
| `lm_a/lm_b/lm_c` | region 使用的三个 landmark |
| `edge_ab/edge_bc/edge_ca` | landmark 三角形三边长 |
| `perimeter` | 周长 |
| `triangle_area` | 三角形面积 |
| `angle_a_deg/angle_b_deg/angle_c_deg` | 三角形内角 |
| `centroid_x/y/z` | 三角形质心 |
| `normal_x/y/z` | 三角形法向 |
| `snap_distance_*` | landmark 吸附到 mesh 顶点的距离 |

该表满足 W2 “根据选取的特征点计算相关特征值”的交付要求。

### 4.4 QC

路径：

```text
output/parameterized_points/<sample>_<side>_remesh_qc.csv
```

关键字段：

| 字段 | 合格要求 |
|---|---|
| `sample_point_count` | 等于 `expected_point_count` |
| `unmapped_count` | 等于 0 |
| `degenerate_faces` | 等于 0 |
| `mesh_exported` | True |
| `status` | PASS |

只有 `status == PASS` 的 region 才建议进入 W3 PCA。

### 4.5 PLY patch

路径：

```text
output/remesh/<sample>_<side>/<region_id>_remesh.ply
```

当前示例：

```text
output/remesh/T001_L/T001_remesh.ply
```

该 PLY 使用固定采样点和固定 template faces 组成，可用于快速查看 remesh patch。

## 5. 算法流程

核心入口：

```python
from ear_param.remesh import build_region_remesh
```

单 region 处理流程：

```text
build_region_remesh(mesh, landmarks, region)
  -> snap_landmarks_to_vertices
  -> build_mesh_adjacency
  -> build_triangle_boundary_paths
  -> extract_patch_faces
  -> harmonic_parameterize_patch
  -> make_subdivision_template
  -> locate_uv_samples_in_faces
  -> map_samples_to_3d
```

结果对象：

```python
result.sample_points_3d
result.template.faces
result.template.barycentric
result.template.uv
result.located_samples
result.parameterization
result.patch
result.snapped_landmarks
```

组装 mesh：

```python
from ear_param.remesh import build_region_remesh_mesh

mesh = build_region_remesh_mesh(result)
```

计算 landmark 特征值：

```python
from ear_param.remesh import compute_region_feature_values

features = compute_region_feature_values(
    landmarks,
    result.snapped_landmarks,
    region["lm_a"],
    region["lm_b"],
    region["lm_c"],
)
```

## 6. 项目结构

```text
.
├── README.md
├── requirements.txt
├── config/
│   └── region_table.csv
├── data/
│   ├── clean_mesh/
│   │   └── T001_L.ply
│   └── landmarks/
│       └── T001_L_landmarks.csv
├── docs/
│   ├── remesh_usage_w2.md
│   ├── w3_pca_average_ear_technical_route.md
│   └── non_remesh_code_assessment.md
├── ear_param/
│   ├── remesh.py
│   ├── io_utils.py
│   ├── config.py
│   ├── core.py
│   ├── run.py
│   ├── synthetic.py
│   └── visualization.py
├── scripts/
│   ├── parameterize_ear_remesh.py
│   ├── parameterize_ear.py
│   └── validate_data.py
├── tests/
│   ├── test_remesh.py
│   └── test_core.py
└── output/
    ├── parameterized_points/
    └── remesh/
```

## 7. 当前主线文件

| 文件 | 作用 |
|---|---|
| `ear_param/remesh.py` | 论文式 remesh 核心算法 |
| `scripts/parameterize_ear_remesh.py` | 当前推荐命令行入口 |
| `tests/test_remesh.py` | remesh 单元测试 |
| `docs/remesh_usage_w2.md` | W2 使用说明 |
| `docs/w3_pca_average_ear_technical_route.md` | W3 PCA 平均耳技术路线 |

## 8. Legacy 代码说明

仓库中仍保留早期参数化采样/KDTree 插值路线：

```text
ear_param/core.py
ear_param/run.py
ear_param/synthetic.py
ear_param/visualization.py
scripts/parameterize_ear.py
tests/test_core.py
```

这些代码不是当前论文式 remesh 主线，但暂时不建议直接删除。

原因：

1. 它们保留了历史算法对照。
2. `synthetic.py` 仍可用于无真实数据时造模拟样本。
3. `tests/test_core.py` 仍保护旧数值工具，删除会影响全量测试。
4. W3 PCA 尚未完成，过早清理会增加回退成本。

详细评估见：

```text
docs/non_remesh_code_assessment.md
```

推荐策略：现在标记为 legacy，等 W3 PCA 平均耳流程完成并稳定后，再单独做清理任务。

## 9. 测试

运行全部测试：

```powershell
python -m pytest -q
```

当前验证结果：

```text
83 passed
```

备注：可能出现 `.pytest_cache` warning，这是本地缓存目录问题，不影响测试通过。

## 10. W3 实现指南摘要

W3 不应再读取原始高密度 mesh，也不应重新做 remesh。W3 的可信输入是 W2 合格输出：

```text
*_remesh_points.csv
*_remesh_faces.csv
*_remesh_qc.csv
```

推荐 W3 路线：

1. 读取所有样本的 remesh 输出。
2. 根据 QC 过滤 `PASS` region。
3. 按 `region_id` 分组。
4. 对每个 region，按 `region_point_id` 排序。
5. 将每个样本的 `(P, 3)` 坐标展平为 `(P*3,)`。
6. 堆叠成矩阵 `X.shape == (N, P*3)`。
7. 用 SVD/PCA 计算主成分。
8. 选择累计解释方差达到 75% 的主成分数。
9. 用均值向量 reshape 成平均 patch 点。
10. 使用 W2 的 fixed faces 生成平均 patch / 平均耳 PLY。

详细实现、测试、交付标准见：

```text
docs/w3_pca_average_ear_technical_route.md
```

## 11. 常见问题

### Q1: 现在应该运行哪个脚本？

运行：

```powershell
python scripts/parameterize_ear_remesh.py --sample_id T001 --side L --mesh data/clean_mesh/T001_L.ply --landmarks data/landmarks/T001_L_landmarks.csv
```

不要优先使用旧的 `scripts/parameterize_ear.py`，它属于 legacy 路线。

### Q2: `flipped_faces` 很大是否一定失败？

不一定。当前 T001_L 中 `flipped_faces=7437`，但 `unmapped_count=0`、`degenerate_faces=0`，因此 QC 为 PASS。`flipped_faces` 更多反映 UV face 方向与标准方向关系，应结合 unmapped 和 degenerate 一起判断。

### Q3: 为什么现在只有一个真实样本不能做 PCA？

PCA 至少需要两个合格样本。单样本只能验证 W2 输出、均值重建和 W3 文件读取流程，不能得到可靠主成分。

### Q4: 后续多个样本如何命名？

建议：

```text
data/clean_mesh/<sample_id>_<side>.ply
data/landmarks/<sample_id>_<side>_landmarks.csv
```

例如：

```text
data/clean_mesh/T002_R.ply
data/landmarks/T002_R_landmarks.csv
```

运行：

```powershell
python scripts/parameterize_ear_remesh.py --sample_id T002 --side R --mesh data/clean_mesh/T002_R.ply --landmarks data/landmarks/T002_R_landmarks.csv
```

### Q5: 可以删除旧代码吗？

现在不建议。它们不是当前主线，但不是完全无用代码。等 W3 完成后再做专门清理更安全。

## 12. 下一步

优先级最高：

1. 收集更多真实样本。
2. 对每个样本运行 `scripts/parameterize_ear_remesh.py`。
3. 确保每个 region 的 QC 为 PASS。
4. 实现 `ear_param/pca_average.py`。
5. 实现 `scripts/build_average_ear.py`。
6. 输出平均 patch 和平均耳 PLY。

建议新增 W3 输出目录：

```text
output/pca_average/
```

建议 W3 命令：

```powershell
python scripts/build_average_ear.py --points_dir output/parameterized_points --out_dir output/pca_average
```

