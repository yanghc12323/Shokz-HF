# Shokz-HF — 3D 耳模型跨模型参数化与特征值计算（2026-07-03 下班！）

基于技术文档《3D 耳模型跨模型参数化与特征值计算技术执行文档 v0.0》，将划分的三维三角区域投影至二维平面，进行降采样处理，限定每个区域的采样点数量相同。

## 关键算法

1. **三角区域分包** — 依据 `config/region_table.csv` 中 A/B/C 三个 landmark 定义区域
2. **重心坐标平面投影** — 三维源点映射到 landmark 定义的三角形参数平面
3. **固定分辨率降采样** — 在标准三角形上按等间距网格生成固定数量采样点，跨模型同名区域采样点数完全一致
4. **插值重建三维坐标** — `LinearNDInterpolator` + `cKDTree` 兜底

## 项目结构

```
ear_project/
├── scripts/
│   └── parameterize_ear.py      # 主脚本（一键运行）
├── config/
│   └── region_table.csv         # 区域定义表（5 个区域）
├── data/
│   ├── clean_mesh/              # .ply mesh 文件（模拟或真实数据）
│   └── landmarks/               # landmarks.csv
├── output/
│   ├── parameterized_points/    # 结果点云 CSV
│   ├── qc/                      # QC 报告 CSV
│   └── logs/                    # 运行日志
├── requirements.txt
├── .gitignore
└── README.md
```

## 快速开始

### 环境要求

- Python ≥ 3.10
- 依赖: `numpy`, `pandas`, `scipy`, `trimesh`

```bash
pip install -r requirements.txt
```

### 一键运行（模拟模式）

无需任何数据，自动生成模拟耳 mesh 并完成参数化：

```bash
cd ear_project
python scripts/parameterize_ear.py
```

### 真实数据模式

```bash
python scripts/parameterize_ear.py \
  --sample_id S001 --side R \
  --mesh data/clean_mesh/S001_R.ply \
  --landmarks data/landmarks/S001_R_landmarks.csv \
  --regions config/region_table.csv \
  --out_points output/parameterized_points/S001_R_points.csv \
  --out_qc output/qc/S001_R_qc.csv
```

可选的 `--patch_dir` 参数支持使用预分割的区域 patch mesh：

```bash
python scripts/parameterize_ear.py ... --patch_dir data/patches/S001_R
```

## 输出格式

### 点云 CSV (`output/parameterized_points/`)

| 字段 | 说明 |
|------|------|
| `sample_id` | 样本编号 |
| `side` | 左右侧 (R/L) |
| `region_id` | 区域编号 (T001–T005) |
| `region_name` | 区域名称 |
| `point_id_global` | 全局采样点编号 |
| `point_id_region` | 区域内采样点编号 |
| `x, y, z` | 三维坐标 (mm) |
| `u, v` | 二维参数坐标 |
| `lambda_a, lambda_b, lambda_c` | 重心坐标 |
| `lm_a, lm_b, lm_c` | 对应的 landmark |

### QC 报告 (`output/qc/`)

| 字段 | 说明 |
|------|------|
| `source_point_count` | 源点数量 |
| `sample_point_count` | 实际采样点数 |
| `expected_point_count` | 预期采样点数 |
| `fallback_ratio` | 最近邻兜底比例 |
| `status` | PASS / WARNING / FAIL |

## 区域配置

| 区域 ID | 名称 | resolution | 固定采样点数 | 用于 PCA |
|---------|------|-----------|-------------|----------|
| T001 | 耳甲腔上区 | 8 | 45 | ✓ |
| T002 | 耳甲腔前下区 | 8 | 45 | ✓ |
| T003 | 耳屏对耳屏区 | 6 | 28 | ✓ |
| T004 | 耳道入口区 | 5 | 21 | ✓ |
| T005 | 耳根上后区 | 6 | 28 | ✗ |

## 模拟运行结果

| 样本 | 区域数 | 总采样点 | QC PASS | QC FAIL |
|------|--------|---------|---------|----------|
| S001_R | 5 | **167** | 5 | 0 |
| S002_R | 5 | **167** | 5 | 0 |
| S003_R | 5 | **167** | 5 | 0 |

## TODO

- [ ] 接入真实扫描/分割的三维 mesh 数据
- [ ] 验证 `--patch_dir` 参数通路
- [ ] 左耳 (`--side L`) 支持
- [ ] PCA 子空间嵌入与统计特征提取 (Phase 2)