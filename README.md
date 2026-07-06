# 3D 耳模型跨模型参数化 — 参数化采样模块(2026-07-06)

> 技术依据：《人头给你了-3D 耳模型跨模型参数化与特征值计算技术执行文档-v0.0》第 3 章

## 项目概述

本模块完成**三维三角区域 → 二维平面投影 → 均匀降采样 → 插值重建**的完整流水线。

核心思路：将 3D 耳 mesh 上由 3 个解剖特征点（landmark）定义的三角形区域，通过**重心坐标（λa, λb, λc）** 映射到二维参数域，在参数域中按固定分辨率均匀采样，再由三角区域内的源点插值重建出每个采样点的三维坐标。所有区域的采样点数统一、结构化，为后续 PCA 特征值分析提供标准化输入。

---

## 输入

| 输入项 | 格式 | 说明 | 示例 |
|--------|------|------|------|
| **耳 mesh** | `.ply` / `.obj` / `.stl` | 单个耳朵的三角形网格，包含顶点坐标和面片索引 | `data/clean_mesh/S001_R.ply` |
| **特征点 (landmarks)** | `.csv` | 解剖标志点的三维坐标，含 `landmark_id, x, y, z` 列 | `data/landmarks/S001_R_landmarks.csv` |
| **区域定义表** | `.csv` | 指定每个三角区域的三个顶点 landmark、采样分辨率 | `config/region_table.csv` |

### 区域定义表 (`config/region_table.csv`)

| 字段 | 说明 |
|------|------|
| `region_id` | 区域唯一编号（如 `T001`） |
| `region_name` | 区域中文名称（如 `耳甲腔上区`） |
| `lm_a, lm_b, lm_c` | 三角形三个顶点的 landmark ID |
| `resolution` | 采样分辨率，点数 = (resolution+1)×(resolution+2)/2 |
| `use_for_pca` | 1=用于 PCA，0=仅辅助 |

当前定义 5 个区域：

| 区域 | 顶点 | resolution | 采样点数 |
|------|------|:---:|:---:|
| T001 耳甲腔上区 | L10-L29-L28 | 8 | 45 |
| T002 耳甲腔下区 | L10-L31-L30 | 8 | 45 |
| T003 耳甲腔前区 | L10-L28-L30 | 8 | 45 |
| T004 耳屏区 | L19-L21-L28 | 8 | 45 |
| T005 对耳屏区 | L20-L21-L15 | 8 | 45 |
| **合计** | | | **225** |

---

## 输出

| 输出项 | 格式 | 说明 |
|--------|------|------|
| **采样点文件** | `.csv` | 每个样本一份，包含所有 225 个采样点的坐标和元数据 |
| **QC 报告** | `.csv` | 每个样本一份，每个区域的采样质量评估（PASS/WARNING/FAIL） |
| **运行日志** | `.log` | 每个样本一份，记录完整的调试信息 |

### 采样点文件字段说明

| 字段 | 说明 |
|------|------|
| `sample_id` | 样本编号 |
| `side` | 左右侧（R/L） |
| `region_id` | 区域编号 |
| `region_name` | 区域名称 |
| `point_id_global` | 全局采样点编号（0-224） |
| `point_id_region` | 区域内采样点编号（从 0 开始） |
| `x, y, z` | 采样点三维坐标（在 mesh 表面上） |
| `u, v` | 二维展开坐标（预留，当前为 NaN） |
| `lambda_a, lambda_b, lambda_c` | 重心坐标，λa+λb+λc=1，可溯源 |
| `lm_a, lm_b, lm_c` | 三角形顶点 landmark ID |

### QC 报告字段说明

| 字段 | 说明 |
|------|------|
| `region_id` | 区域编号 |
| `region_name` | 区域名称 |
| `source_point_count` | 三角区域内的源点数量 |
| `sample_point_count` | 实际采样点数 |
| `expected_point_count` | 预期采样点数 |
| `fallback_ratio` | 最近邻兜底比例 |
| `interpolator` | 使用的插值器 |
| `status` | PASS / WARNING / FAIL |

---

## 算法流程（对应文档第 3 章）

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  3D 耳 Mesh   │────▶│ 三角区域裁剪   │────▶│ 重心坐标投影  │
│  + landmarks │     │ (λ ∈ [0,1])  │     │ (λa, λb, λc) │
└──────────────┘     └──────────────┘     └──────────────┘
                                                 │
                                                 ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  CSV + QC    │◀────│  插值重建3D   │◀────│ 均匀采样网格  │
│  输出        │     │  + cKDTree   │     │ resolution=8  │
└──────────────┘     └──────────────┘     └──────────────┘
```

1. **三角形退化检测** — 三点共线或面积 ≈ 0 则报错
2. **源点裁剪** — 将 mesh 顶点投影到三角形平面，筛选 λ∈[0,1] 的点
3. **重心坐标网格** — 按 resolution 生成等间距 (λa, λb, λc) 网格
4. **插值重建** — LinearNDInterpolator 在参数空间插值，NaN 用 cKDTree 兜底
5. **QC 评估** — 兜底比例 <5% → PASS，5%~20% → WARNING，>20% → FAIL

---

## 项目结构

```
ear_project/
├── README.md                        ← 本文件
├── requirements.txt                 ← Python 依赖
├── config/
│   └── region_table.csv             ← 区域定义表（用户编辑）
├── ear_param/                       ← 核心包
│   ├── __init__.py
│   ├── config.py                    ← 全局配置与常量
│   ├── core.py                      ← 核心算法（裁剪/投影/采样/插值）
│   ├── io_utils.py                  ← 文件 IO 与日志
│   ├── synthetic.py                 ← 模拟数据生成
│   └── run.py                       ← 流程编排（批量/单样本）
├── scripts/
│   └── parameterize_ear.py          ← 命令行入口
├── data/                            ← 自动生成（模拟模式）
│   ├── clean_mesh/                  ← 耳 mesh (.ply)
│   └── landmarks/                   ← 特征点 (.csv)
└── output/                          ← 自动生成
    ├── parameterized_points/        ← 采样点 (.csv)
    ├── qc/                          ← QC 报告 (.csv)
    └── logs/                        ← 运行日志 (.log)
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

依赖：`numpy`, `pandas`, `scipy`, `trimesh`

### 2. 模拟模式（无真实数据时测试）

```bash
cd ear_project
python scripts/parameterize_ear.py
```

自动生成 3 个模拟样本（S001-S003），完成参数化，输出到 `output/` 目录。

### 3. 真实数据模式（拿到数据后）

```bash
python scripts/parameterize_ear.py \
    --sample_id S001 --side R \
    --mesh data/clean_mesh/S001_R.ply \
    --landmarks data/landmarks/S001_R_landmarks.csv \
    --regions config/region_table.csv \
    --out_points output/parameterized_points/S001_R_points.csv \
    --out_qc output/qc/S001_R_qc.csv
```

---

## 下一步工作

当你拿到真实数据后，需要准备：

1. **耳 mesh 文件** — 命名规范 `{sample_id}_{side}.ply`，放在 `data/clean_mesh/` 下
2. **特征点 CSV** — 必须包含列 `landmark_id, x, y, z`，命名 `{sample_id}_{side}_landmarks.csv`
3. **检查 landmark 覆盖** — 确保文件包含 `config/region_table.csv` 中所有引用的 landmark（当前需要 L10, L15, L19, L20, L21, L28, L29, L30, L31）
4. **如需自定义区域** — 编辑 `config/region_table.csv`，增减行即可
5. **如需调参** — 编辑 `ear_param/config.py` 中的容差和阈值

然后按真实数据模式运行即可，每个样本生成一份采样点 CSV + QC 报告。

---

## 配置参数速查（`ear_param/config.py`）

| 参数 | 默认值 | 说明 |
|------|:---:|------|
| `PROJECTION_TOL` | 0.15 | 重心坐标允许超出 [0,1] 的容差 |
| `FALLBACK_WARNING_THRESHOLD` | 0.05 | 兜底比例 >5% 触发 WARNING |
| `FALLBACK_FAIL_THRESHOLD` | 0.20 | 兜底比例 >20% 触发 FAIL |
| `MIN_SOURCE_POINTS` | 5 | 三角区域内源点最小数量 |
| `DENSE_SAMPLE_COUNT` | 5000 | mesh 顶点采样上限（性能优化） |