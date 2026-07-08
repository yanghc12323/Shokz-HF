# 3D 耳模型跨模型参数化 — 参数化采样与降采样模块

> 技术依据：《人头给你了-3D 耳模型跨模型参数化与特征值计算技术执行文档-v0.0》第 3 章  
> 最后更新：2026-07-07

---

## 目录

1. [背景与问题的提出](#背景与问题的提出)
2. [项目概述](#项目概述)
3. [数学原理](#数学原理)
4. [项目结构](#项目结构)
5. [输入](#输入)
6. [输出](#输出)
7. [完整操作流程（从头到尾）](#完整操作流程从头到尾)
8. [算法详解](#算法详解)
   - [步骤 0：三角形退化检测](#步骤-0三角形退化检测)
   - [步骤 1：源点裁剪（Mesh 顶点投影筛选）](#步骤-1源点裁剪mesh-顶点投影筛选)
   - [步骤 2：重心坐标批量计算（最小二乘投影）](#步骤-2重心坐标批量计算最小二乘投影)
   - [步骤 3：固定分辨率重心坐标网格生成](#步骤-3固定分辨率重心坐标网格生成)
   - [步骤 4：源面片构建（保留原始 mesh 拓扑）](#步骤-4源面片构建保留原始-mesh-拓扑)
   - [步骤 5：插值重建采样点三维坐标](#步骤-5插值重建采样点三维坐标)
   - [步骤 6：QC 质量评估](#步骤-6qc-质量评估)
9. [执行入口说明](#执行入口说明)
10. [日志系统](#日志系统)
11. [配置参数速查](#配置参数速查)
12. [模拟数据说明](#模拟数据说明)
13. [FAQ & 常见问题](#faq--常见问题)
14. [下一步工作](#下一步工作)

---

## 背景与问题的提出

### 1. 我们要干什么？

我们有多个不同人的 3D 耳朵 mesh（三角形网格），每个耳朵的形状不同，顶点数量、面片拓扑都不同。我们希望在耳朵上定义若干**三角区域**（以解剖标志点为顶点），在每个区域内采样**固定数量**的均匀分布点，使得不同样本的采样点一一对应，便于跨样本统计分析（如 PCA 特征值分析）。

### 2. 核心挑战

| 挑战 | 说明 |
|------|------|
| **顶点数量不统一** | 不同样本的 mesh 顶点数不同（几百到几万不等），不能直接放在一个矩阵里 |
| **拓扑不一致** | 每个 mesh 的三角面片连接关系不同，无法按面片索引对齐 |
| **需要固定样点** | PCA 要求所有样本的同一特征位置有对应值，即每个区域的采样点数必须完全相同 |
| **保留曲面信息** | 采样点必须落在耳朵曲面上，不能是纯平面三角形内插值 |

### 3. 解决方案

将所有三角形区域通过**重心坐标**（Barycentric Coordinates）投影到一个统一的二维参数空间，在参数空间中生成固定分辨率网格，再利用**KDTree 局部加权最小二乘插值**（含共线性检测与 Tier1/Tier2 双模式降级），稳健重建出每个网格点的三维坐标。

---

## 项目概述

### 一句话总结

> 将 3D 耳 mesh 上由解剖 landmark 定义的三角形区域投影至重心坐标参数平面，在参数平面上按固定分辨率采样，再借助原始 mesh 面片拓扑插值重建三维坐标，输出每样本固定数量、固定顺序的采样点集。

### 核心流程图

```
┌──────────────────────────────────────────────────────────────────┐
│                        输入                                      │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐       │
│  │ 耳 Mesh      │  │ Landmarks    │  │ 区域定义表         │       │
│  │ (.ply)       │  │ (.csv)       │  │ region_table.csv   │       │
│  └──────┬──────┘  └──────┬───────┘  └────────┬──────────┘       │
│         │                │                    │                  │
│         └────────────────┼────────────────────┘                  │
│                          ▼                                       │
│            ┌─────────────────────────┐                           │
│            │  process_region()  × 5  │   ← 每个三角区域独立处理  │
│            │  (core.py)              │                           │
│            │                         │                           │
│            │  ① 退化检测             │                           │
│            │  ② 顶点采样 + 重心投影  │                           │
│            │  ③ 裁剪源点             │                           │
│            │  ④ 构建源面片           │                           │
│            │  ⑤ 生成网格 + 插值重建  │                           │
│            │  ⑥ QC 评估              │                           │
│            └────────────┬────────────┘                           │
│                         ▼                                        │
│                     输     出                                    │
│  ┌────────────────┐  ┌───────────┐  ┌────────────────┐          │
│  │ 采样点 CSV      │  │ QC 报告   │  │ 运行日志 .log   │          │
│  │ (225 点/样本)   │  │ (.csv)    │  │                │          │
│  └────────────────┘  └───────────┘  └────────────────┘          │
└──────────────────────────────────────────────────────────────────┘
```

### 为什么需要这一步？

| 问题 | 解决方式 |
|------|----------|
| 不同样本顶点数不同 | 统一采样为固定点数（如每区 45 点，5 区共 225 点） |
| 不同样本拓扑不同 | 采样点在参数空间的位置（重心坐标）是固定的，跨样本可对齐 |
| 需要曲面信息 | v3.0 使用 KDTree 加权最小二乘插值，在参数空间中稳健重建三维坐标 |
| 需要可溯源性 | 每个采样点记录了所用的三个 landmark 和重心坐标 λ_a, λ_b, λ_c |

---

## 数学原理

### 1. 重心坐标 (Barycentric Coordinates)

对于空间三角形 ΔABC，其平面上任意一点 P 可表示为：

```
P = λ_a·A + λ_b·B + λ_c·C
```

其中 λ_a + λ_b + λ_c = 1，且当点 P 在三角形内部时有 0 ≤ λ_a, λ_b, λ_c ≤ 1。

### 2. 3D 点到三角形平面的最小二乘投影

给定三角形顶点 A、B、C 和一个 3D 点 P：

1. 在三角形平面中建立局部坐标系，以 A 为原点，u⃗ = B − A、v⃗ = C − A 为基向量。
2. 将 P − A 投影到 (u⃗, v⃗) 张成的子空间，解得坐标 (u, v)。
3. 由 u, v 反算重心坐标：λ_b = u，λ_c = v，λ_a = 1 − λ_b − λ_c。

这就是**二维参数化**：每个 3D 点映射到一个 (λ_b, λ_c) 二维坐标，共面点保距（仿射变换）。

### 3. 固定分辨率采样网格

在重心坐标参数空间 [0, 1]² 中，以分辨率 r 等间距采样。对于 r = 8，步长 = 1/8，在三角形区域（满足 λ_a + λ_b + λ_c = 1 且 λ_i ≥ 0）内，总采样点数：

```
N = (r + 1)(r + 2) / 2 = 9 × 10 / 2 = 45
```

### 4. KDTree 局部加权最小二乘插值 (v3.0)

不再使用 Qhull 全局插值器（v1.0 中共线性导致崩溃 + 外插数值不稳定），也不使用面片感知 Point-in-Triangle 插值（v2.0），而是采用 **KDTree 局部加权最小二乘**：

1. 对每个目标网格点，在参数空间 (λ_b, λ_c) 中用 KDTree 查询 **k 个最近邻源点**（默认 k=12）。
2. 检查 k 个近邻的 (λ_b, λ_c) 是否**共线性**（条件数 > `COLLINEARITY_THRESHOLD`）。
3. **Tier 1（共线性安全）**：对 3D 空间中 k 个近邻做高斯加权最小二乘（权重 = exp(-d²/σ²)），直接解得 3D 坐标。
4. **Tier 2（共线性不安全或拟合失败）**：退化为三角形顶点重心线性插值（永远不崩溃的兜底方案）。
5. 结果通过 `np.isfinite` 校验，若出现 NaN/Inf 则自动降级。

---

## 项目结构

```
（项目根目录）/
│
├── README.md                    ← 本文件
├── requirements.txt             ← Python 依赖
├── .gitignore                   ← Git 忽略规则
│
├── config/
│   └── region_table.csv         ← 区域定义表（5 个三角区域）
│
├── ear_param/                   ← 核心 Python 包
│   ├── __init__.py              ← 包初始化
│   ├── config.py                ← 全局配置常量
│   ├── core.py                  ← ★ 核心算法（退化检测/投影/插值/QC/UV 展开）
│   ├── synthetic.py             ← 模拟数据生成
│   ├── io_utils.py              ← 文件 I/O 与日志系统
│   ├── visualization.py         ← 可视化（网格图/散点图/3D 概览/QC 热力图/Atlas 总图）
│   └── run.py                   ← 流程编排（模拟模式 + 单样本模式）
│
├── tests/                       ← 单元测试套件 (73 个测试)
│   ├── __init__.py
│   ├── conftest.py              ← 共享 fixtures
│   └── test_core.py             ← core.py 全覆盖测试
│
├── scripts/
│   └── parameterize_ear.py      ← ★ 命令行入口
│
├── data/                        ← 输入数据目录（运行时自动创建）
│   ├── clean_mesh/              ←   耳 mesh 文件 (.ply)
│   └── landmarks/               ←   特征点文件 (.csv)
│
└── output/                      ← 输出目录（运行时自动创建）
    ├── parameterized_points/    ←   采样点 CSV
    ├── qc/                      ←   QC 报告 CSV
    ├── figures/                 ←   可视化图片 (.png)
    └── logs/                    ←   运行日志 .log
```

### 各模块职责

| 文件 | 行数 | 职责 |
|------|:---:|------|
| `ear_param/core.py` | 838 | 全部数学运算：退化检测、重心投影、KDTree 加权最小二乘插值、QC 评估、UV 展开 |
| `ear_param/run.py` | 580 | 将 core.py 各函数编排成完整流水线，提供模拟模式和单样本模式两个入口 |
| `ear_param/synthetic.py` | 325 | 生成三组模拟耳 mesh + landmarks，用于无真实数据时测试流水线 |
| `ear_param/visualization.py` | 480 | 可视化：各区域散点图、3D 概览图、QC 热力图、Atlas 全局展开图 |
| `ear_param/io_utils.py` | 338 | CSV 多编码读取、mesh 加载/保存、双通道日志配置 |
| `ear_param/config.py` | 89 | 所有可调参数集中管理（含 KDTree 插值参数共 4 个新项） |
| `tests/test_core.py` | 980 | 73 个单元测试：退化检测、重心坐标、Atlas UV、KDTree 插值、端到端流程、回归测试 |
| `scripts/parameterize_ear.py` | 65 | 命令行参数解析 + 路由到 run.py |
| `config/region_table.csv` | 6 行 | 5 个三角区域的定义（顶点 landmark、分辨率） |

---

## 输入

### 1. 耳 Mesh（`.ply`）

- 单只耳朵的三角网格，包含顶点坐标 `(x, y, z)` 和面片索引。
- 格式：PLY（推荐）/ OBJ / STL。
- 示例命名：`S001_R.ply`（样本 S001，右耳）。

### 2. 特征点 Landmarks（`.csv`）

- 解剖标志点的三维坐标。
- 必需列：`landmark_id, x, y, z`。
- 示例命名：`S001_R_landmarks.csv`。

### 3. 区域定义表 `config/region_table.csv`

| 字段 | 类型 | 说明 |
|------|------|------|
| `region_id` | str | 区域唯一编号（如 `T001`） |
| `region_name` | str | 区域中文名称（如 `耳甲腔上区`） |
| `lm_a` | str | 三角形顶点 A 的 landmark ID |
| `lm_b` | str | 三角形顶点 B 的 landmark ID |
| `lm_c` | str | 三角形顶点 C 的 landmark ID |
| `resolution` | int | 采样分辨率（点数 = (r+1)(r+2)/2） |
| `use_for_pca` | int | 1 = 用于 PCA，0 = 仅辅助/可视化 |

当前定义的 5 个区域：

| 区域 | 名称 | 顶点 | resolution | 采样点数 |
|------|------|------|:---:|:---:|
| T001 | 耳甲腔上区 | L10–L29–L28 | 8 | 45 |
| T002 | 耳甲腔下区 | L10–L31–L30 | 8 | 45 |
| T003 | 耳甲腔前区 | L10–L28–L30 | 8 | 45 |
| T004 | 耳屏区 | L19–L21–L28 | 8 | 45 |
| T005 | 对耳屏区 | L20–L21–L15 | 8 | 45 |
| **合计** | | | | **225** |

### 4. 所需的 Landmark 子集

区域定义表中引用了以下 9 个 landmark（来自论文 31 个特征点的子集）：

| ID | 解剖位置 |
|:---|------|
| L10 | 耳甲腔中心 |
| L15 | 对耳屏边缘 |
| L19 | 耳屏上方 |
| L20 | 对耳屏上方 |
| L21 | 耳屏-对耳屏交界 |
| L28 | 耳甲腔上缘 |
| L29 | 耳甲腔上外缘 |
| L30 | 耳甲腔前下缘 |
| L31 | 耳甲腔下缘 |

---

## 输出

### 1. 采样点 CSV（`output/parameterized_points/S001_R_points.csv`）

每行一个采样点，包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `sample_id` | str | 样本编号 |
| `side` | str | 左右侧 (R/L) |
| `region_id` | str | 区域编号 |
| `region_name` | str | 区域中文名称 |
| `point_id_global` | int | 全局采样点编号（跨区域连续） |
| `point_id_region` | int | 区域内采样点编号（0 起） |
| `x, y, z` | float | 重建的三维坐标 |
| `u, v` | float | 二维 UV 展开坐标（基于重心坐标 λ_b、λ_c 的仿射变换，已实际计算） |
| `lambda_a, lambda_b, lambda_c` | float | 重心坐标（可溯源） |
| `lm_a, lm_b, lm_c` | str | 三角形顶点 landmark ID |

### 2. QC 报告（`output/qc/S001_R_qc.csv`）

| 字段 | 说明 |
|------|------|
| `region_id` | 区域编号 |
| `region_name` | 区域名称 |
| `used_patch_file` | 是否使用了补丁文件 |
| `source_point_count` | 三角区域内的源点数 |
| `source_face_count` | 三角区域内的源面片数 |
| `sample_point_count` | 输出的采样点数 |
| `expected_point_count` | 期望的采样点数 |
| `fallback_ratio` | 兜底插值比例 |
| `interpolator` | 使用的插值器类型 |
| `status` | QC 状态：PASS / WARNING / FAIL |

**QC 判定标准：**

- `fallback_ratio ≤ 5%` → **PASS** ✅
- `5% < fallback_ratio ≤ 20%` → **WARNING** ⚠️
- `fallback_ratio > 20%` → **FAIL** ❌

### 3. 运行日志（`output/logs/`）

- 文件命名：`{sample_id}_{side}_parameterize_{时间戳}.log`
- 双通道输出：
  - **控制台**：INFO 级别（关键步骤摘要）
  - **日志文件**：DEBUG 级别（含所有中间变量的详细记录）

---

## 完整操作流程（从头到尾）

### 前置条件

1. **Python 环境**
   ```bash
   Python >= 3.10
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

   `requirements.txt` 内容：
   ```
   numpy>=1.24
   pandas>=1.5
   trimesh>=4.0
   scipy>=1.10
   ```

3. **确认目录结构正确**（见[项目结构](#项目结构)）。

---

### 方式 A：模拟模式（无真实数据时）

这是**一键运行**模式，程序自动生成三组模拟的耳朵 mesh 和 landmarks，然后执行完整的参数化流水线。

```bash
python scripts/parameterize_ear.py
```

**执行流程图解：**

```
┌─────────────────────────────────────────────────────────────────┐
│  python scripts/parameterize_ear.py  (无任何参数)                │
│                                                                  │
│  ┌───────────────────────┐                                      │
│  │ 1. CLI 解析参数        │  → 无参数 → mode = "simulation"      │
│  │    parameterize_ear.py │                                      │
│  └──────────┬────────────┘                                      │
│             ▼                                                    │
│  ┌───────────────────────┐                                      │
│  │ 2. run_simulation()    │  → run.py                            │
│  │    ┌─────────────────┐ │                                      │
│  │    │ 2a. 创建目录     │ │  data/clean_mesh/                   │
│  │    │                │ │  data/landmarks/                     │
│  │    │                │ │  output/parameterized_points/        │
│  │    │                │ │  output/qc/                          │
│  │    │                │ │  output/logs/                        │
│  │    ├─────────────────┤ │                                      │
│  │    │ 2b. 生成模拟数据  │ │  synthetic.py → 3 个 .ply + 3 个   │
│  │    │   (S001~S003)   │ │  _landmarks.csv                     │
│  │    ├─────────────────┤ │                                      │
│  │    │ 2c. 加载区域表    │ │  config/region_table.csv            │
│  │    ├─────────────────┤ │                                      │
│  │    │ 2d. 批量参数化    │ │  _batch_parameterize()              │
│  │    │   对每个样本:     │ │                                      │
│  │    │   → load_mesh    │ │  io_utils.py                        │
│  │    │   → load_lms     │ │  io_utils.py                        │
│  │    │   → 逐区域处理    │ │  core.py / process_region() × 5     │
│  │    │   → 保存结果      │ │                                      │
│  │    └─────────────────┘ │                                      │
│  └────────────────────────┘                                      │
│                                                                  │
│  ┌───────────────────────┐                                      │
│  │ 3. 单区域处理详解       │  core.py / process_region()          │
│  │    (每个区域执行一次)   │                                      │
│  │                        │                                      │
│  │  ① 取三个 landmark    │  A = lms["L10"], B = lms["L29"],     │
│  │     三维坐标          │  C = lms["L28"]                      │
│  │  ② 退化检测           │  _is_triangle_degenerate()            │
│  │                        │  面积 ≈ 0 → 抛异常                   │
│  │  ③ 顶点采样           │  随机抽 5000 个 mesh 顶点             │
│  │  ④ 重心投影           │  _barycentric_batch()                 │
│  │  ⑤ 裁剪源点           │  _clip_points_to_triangle()           │
│  │                        │  保留 λ_i ∈ [-0.15, 1.15] 的点      │
│  │  ⑥ 构建源面片         │  _build_source_faces()               │
│  │                        │  提取完整落在区域内的 mesh 面片       │
│  │  ⑦ 生成目标网格       │  make_barycentric_grid(r=8)          │
│  │                        │  → 45 个重心坐标点                    │
│  │  ⑧ 插值重建           │  _interpolate_sample_points()         │
│  │                        │  KDTree 加权最小二乘 + 共线性降级    │
│  │  ⑨ QC 评估            │  计算 fallback_ratio → PASS/WARN/FAIL│
│  │  ⑩ 组装 DataFrame     │  输出 45 行 × 15 列                   │
│  └───────────────────────┘                                      │
│                                                                  │
│  ┌───────────────────────┐                                      │
│  │ 4. 最终摘要            │  打印每个样本的 PASS/WARN/FAIL 统计   │
│  │    _print_final_summary│                                      │
│  └───────────────────────┘                                      │
└─────────────────────────────────────────────────────────────────┘
```

**预期输出文件：**

```
output/
├── logs/
│   ├── SIMULATION_ALL_parameterize_20260706_HHMMSS.log   ← 主日志
│   ├── S001_R_parameterize_20260706_HHMMSS.log           ← S001 详细日志
│   ├── S002_R_parameterize_20260706_HHMMSS.log           ← S002 详细日志
│   └── S003_R_parameterize_20260706_HHMMSS.log           ← S003 详细日志
├── parameterized_points/
│   ├── S001_R_points.csv  (225 行)
│   ├── S002_R_points.csv  (225 行)
│   └── S003_R_points.csv  (225 行)
└── qc/
    ├── S001_R_qc.csv  (5 行)
    ├── S002_R_qc.csv  (5 行)
    └── S003_R_qc.csv  (5 行)
```

**预期控制台输出示例：**

```
2026-07-06 10:00:00 | INFO    | ============================================================
2026-07-06 10:00:00 | INFO    | 开始一键模拟流程
2026-07-06 10:00:00 | INFO    | 项目根目录: D:\YHC\人头项目
2026-07-06 10:00:00 | INFO    | ============================================================
2026-07-06 10:00:00 | INFO    | 
2026-07-06 10:00:00 | INFO    | ============================================================
2026-07-06 10:00:00 | INFO    | 开始生成模拟数据 (3 组)...
2026-07-06 10:00:01 | INFO    |   生成 S001: 1500 vertices, noise=0.25, seed=42
2026-07-06 10:00:01 | INFO    |   生成 S002: 1500 vertices, noise=0.35, seed=123
2026-07-06 10:00:01 | INFO    |   生成 S003: 1500 vertices, noise=0.28, seed=999
2026-07-06 10:00:01 | INFO    | 模拟数据生成完成.
2026-07-06 10:00:01 | INFO    | 区域表: 5 个区域
2026-07-06 10:00:01 | INFO    |   T001: 耳甲腔上区, resolution=8, 预期点数=45, PCA=是
2026-07-06 10:00:01 | INFO    |   T002: 耳甲腔下区, resolution=8, 预期点数=45, PCA=是
2026-07-06 10:00:01 | INFO    |   T003: 耳甲腔前区, resolution=8, 预期点数=45, PCA=是
2026-07-06 10:00:01 | INFO    |   T004: 耳屏区, resolution=8, 预期点数=45, PCA=否
2026-07-06 10:00:01 | INFO    |   T005: 对耳屏区, resolution=8, 预期点数=45, PCA=否
2026-07-06 10:00:01 | INFO    | 
2026-07-06 10:00:01 | INFO    | ============================================================
2026-07-06 10:00:01 | INFO    | 开始批量参数化...
2026-07-06 10:00:01 | INFO    |   [S001_R] 处理区域 T001: 耳甲腔上区
2026-07-06 10:00:01 | INFO    |     -> 源点=264, 源面片=150, 采样点=45, 兜底=0(0.0%), 状态=PASS
2026-07-06 10:00:01 | INFO    |   [S001_R] 处理区域 T002: 耳甲腔下区
2026-07-06 10:00:01 | INFO    |     -> 源点=200, 源面片=120, 采样点=45, 兜底=2(4.4%), 状态=PASS
... (省略中间区域)
2026-07-06 10:00:01 | INFO    |   [S001] 完成: 总点数=225, QC: PASS=5 WARNING=0 FAIL=0
...
2026-07-06 10:00:02 | INFO    | ============================================================
2026-07-06 10:00:02 | INFO    | 批量参数化完成 - 最终摘要
2026-07-06 10:00:02 | INFO    |   OK S001_R: 总点=225, PASS=5, WARN=0, FAIL=0
2026-07-06 10:00:02 | INFO    |   OK S002_R: 总点=225, PASS=5, WARN=0, FAIL=0
2026-07-06 10:00:02 | INFO    |   OK S003_R: 总点=225, PASS=5, WARN=0, FAIL=0
2026-07-06 10:00:02 | INFO    | 
2026-07-06 10:00:02 | INFO    | 输出目录:
2026-07-06 10:00:02 | INFO    |   点云: output/parameterized_points
2026-07-06 10:00:02 | INFO    |   QC:   output/qc
2026-07-06 10:00:02 | INFO    |   日志: output/logs
2026-07-06 10:00:02 | INFO    | ============================================================
```

---

### 方式 B：单样本模式（有真实数据时）

当你有真实的 mesh 和 landmarks 文件后，使用此模式：

```bash
python scripts/parameterize_ear.py \
    --sample_id S001 \
    --side R \
    --mesh data/clean_mesh/S001_R.ply \
    --landmarks data/landmarks/S001_R_landmarks.csv
```

**可选参数：**

| 参数 | 必需 | 默认值 | 说明 |
|------|:---:|------|------|
| `--sample_id` | 是 | — | 样本编号 |
| `--side` | 是 | — | 左右侧（R 或 L） |
| `--mesh` | 是 | — | mesh 文件路径 |
| `--landmarks` | 是 | — | landmarks CSV 文件路径 |
| `--regions` | 否 | `config/region_table.csv` | 区域表路径 |
| `--out_points` | 否 | `output/parameterized_points/{sample_id}_{side}_points.csv` | 输出路径 |
| `--out_qc` | 否 | `output/qc/{sample_id}_{side}_qc.csv` | QC 输出路径 |
| `--log_dir` | 否 | `output/logs` | 日志目录 |

**示例：处理一个真实样本**

```bash
# 将你的 .ply 文件和 landmarks.csv 放到对应目录后运行：
python scripts/parameterize_ear.py \
    --sample_id REAL001 \
    --side R \
    --mesh data/clean_mesh/REAL001_R.ply \
    --landmarks data/landmarks/REAL001_R_landmarks.csv
```

---

### 方式 C：Python 代码直接调用

```python
from pathlib import Path
from ear_param.run import run_simulation, run_single_sample

# 模拟模式
run_simulation()

# 单样本模式
run_single_sample(
    sample_id="S001",
    side="R",
    mesh_path=Path("data/clean_mesh/S001_R.ply"),
    landmarks_path=Path("data/landmarks/S001_R_landmarks.csv"),
    regions_csv=Path("config/region_table.csv"),
    out_points=Path("output/parameterized_points/S001_R_points.csv"),
    out_qc=Path("output/qc/S001_R_qc.csv"),
    log_dir=Path("output/logs"),
)
```

---

## 算法详解

以下按 `core.py` 中 `process_region()` 的执行顺序，逐步解释每个子步骤的数学原理和代码逻辑。

### 步骤 0：三角形退化检测

**函数**：`_is_triangle_degenerate(a, b, c, eps=1e-6)`

```python
ab = b - a
ac = c - a
area_vec = np.cross(ab, ac)
area = float(np.linalg.norm(area_vec))
return area < eps
```

- 计算三角形面积 = |(B−A) × (C−A)| / 2。
- 若面积 < 1e-6，判定为退化（三点共线），无法建立投影平面，直接抛异常。
- 正常三角形面积远大于此阈值（耳甲腔区域面积约 1~2 cm² = 100~200 mm²）。

### 步骤 1：源点裁剪（Mesh 顶点投影筛选）

**函数**：`_clip_points_to_triangle(points, a, b, c, tolerance=0.15)`

**流程：**

1. 调用 `_barycentric_batch()` 对每个 mesh 顶点计算重心坐标 (λ_a, λ_b, λ_c)。
2. 筛选条件：每个 λ_i ∈ [−tolerance, 1+tolerance]，即允许顶点略微超出三角形边界。
3. 返回裁剪后的顶点坐标和布尔掩码。

**为什么需要 tolerance？**

- 真实耳朵是曲面，mesh 顶点不完全落在三角形平面上。
- 重心坐标由最小二乘投影计算，有数值误差。
- 允许 vertices 略微超出三角形边界（如 λ_a = −0.02）可以避免丢失边缘上的有效点。
- 当前 tolerance = 0.15（较宽松），可在 `config.py` 中调整。

**采样优化：**

- 若 mesh 顶点数 > 5000，随机抽取 5000 个顶点做重心计算（避免 O(N²) 耗时）。
- 抽样使用固定种子（seed=42），保证可复现。

### 步骤 2：重心坐标批量计算（最小二乘投影）

**函数**：`_barycentric_batch(points, a, b, c)`

**数学推导：**

1. 以 A 为原点，建立局部坐标系：u⃗ = B − A，v⃗ = C − A。
2. 对每个点 P_i，P_i − A 在 (u⃗, v⃗) 子空间的最小二乘投影坐标 (u_i, v_i) 满足 Gram 矩阵方程：

```
[ u⃗·u⃗   u⃗·v⃗ ] [ u_i ]   [ (P_i−A)·u⃗ ]
[ u⃗·v⃗   v⃗·v⃗ ] [ v_i ] = [ (P_i−A)·v⃗ ]
```

3. 求解得 u_i, v_i，则：
   - λ_b = u_i
   - λ_c = v_i
   - λ_a = 1 − λ_b − λ_c

4. 若 Gram 矩阵行列式 ≈ 0（退化三角形），返回等重心坐标 (1/3, 1/3, 1/3)。

**复杂度：** O(N)，使用矩阵运算一次处理所有点。

### 步骤 3：固定分辨率重心坐标网格生成

**函数**：`make_barycentric_grid(resolution)`

```
对 resolution = 8:
  i 从 0 到 8:
    j 从 0 到 8−i:
      λ_b = i / 8
      λ_c = j / 8
      λ_a = 1 − λ_b − λ_c
      保存 [λ_a, λ_b, λ_c]

共 (8+1)×(8+2)/2 = 45 个点
```

**采样点排列顺序（行优先，j 变化快于 i）：**

```
i=0: (1.000, 0.000, 0.000)  (0.875, 0.000, 0.125)  ...  (0.000, 0.000, 1.000)
i=1: (0.875, 0.125, 0.000)  (0.750, 0.125, 0.125)  ...  (0.000, 0.125, 0.875)
...
i=8: (0.000, 1.000, 0.000)
```

所有样本的所有区域使用**完全相同**的网格点，这是跨样本对齐的关键。

### 步骤 4：源面片构建（保留原始 mesh 拓扑）

**函数**：`_build_source_faces(sampled_vertices, sampled_lambdas, clip_mask, global_indices, full_faces, logger)`

**流程：**

1. 建立映射表：`global_vertex_index → clipped_local_index`（仅保留 clip_mask=True 的顶点）。
2. 遍历原始 mesh 的所有面片（顶点三元组）。
3. 若面片的三个顶点都出现在映射表中（即都被裁剪保留），则：
   - 记录该面片三个顶点的 3D 坐标 → `face_triangles_3d`
   - 记录该面片三个顶点的 (λ_b, λ_c) 参数坐标 → `face_triangles_2d`
4. 返回两组数据。

**为什么需要源面片？**

v2.0 升级的关键。以前用 LinearNDInterpolator 在参数空间做 Delaunay 三角剖分再插值，但 Delaunay 会重新划分拓扑，可能导致跨解剖结构的错误插值。保留原始 mesh 面片就保证了插值严格在原始曲面拓扑内进行。

### 步骤 5：KDTree 局部加权最小二乘插值 (v3.0)

**函数**：`_interpolate_sample_points(source_points, source_lambdas, target_grid, triangle_vertices)`

**v3.0 核心升级：彻底移除 Qhull 依赖，采用 KDTree + 高斯加权最小二乘。**

#### 设计动机

v2.0 使用的 `scipy.interpolate.LinearNDInterpolator` 底层依赖 Qhull (Delaunay 三角剖分)。在高分辨率网格（如 DENSE_SAMPLE_COUNT=5000）下存在两个严重问题：

| 问题 | 影响 |
|------|------|
| Qhull Delaunay 构建 O(N log N) | 大样本下成为性能瓶颈 |
| Qhull 精度错误时直接抛异常 | 无 Python 层 try/except，导致流水线崩溃 |

v3.0 方案用 `scipy.spatial.KDTree` 替代 Qhull，配合逐点共线性检测 + 降级策略，彻底消除崩溃风险。

#### 两层插值策略

**Tier 1：KDTree + 高斯加权最小二乘（主路径）**

对每个目标网格点 `(λ_a, λ_b, λ_c)`：

1. 在 `(λ_b, λ_c)` 参数空间用 KDTree 查询 `k = KNN_K` 个最近邻源点（默认 k=12）。
2. **共线性检测**：对近邻集的 `(λ_b, λ_c)` 坐标做 SVD（奇异值分解），计算第二/第一奇异值方差比：
   - 若方差比 < `COLLINEARITY_THRESHOLD`（默认 1e-8），判定近邻近似共线 → 降级到 Tier 2。
   - 若 SVD 本身失败 → 降级到 Tier 2。
3. **高斯加权**：以近邻距离的中位数 × 2 为 σ，构建高斯权重矩阵 `w_i = exp(-d_i²/σ²)`。
4. **加权最小二乘**：对 x, y, z 三个维度分别拟合线性模型 `β₀ + β₁·λ_b + β₂·λ_c`，用目标点的重心坐标预测 3D 坐标。
5. **结果校验**：检查拟合结果是否有限（`np.isfinite`），若出 NaN/Inf → 降级到 Tier 2。

**Tier 2：三角形顶点重心线性插值（降级）**

当 Tier 1 的任何步骤失败时，直接用目标点的重心坐标和三角形三个顶点的 3D 坐标做线性重建：

```
P_3d = λ_a·A + λ_b·B + λ_c·C
```

这是最保守但永远不崩溃的兜底方案。

#### 参数配置

| 参数 | 默认值 | 说明 |
|------|:---:|------|
| `KNN_K` | 12 | KDTree 近邻数（2D 空间平衡点） |
| `COLLINEARITY_THRESHOLD` | 1e-8 | 共线性检测阈值 |
| `LSQ_RCOND` | 1e-12 | lstsq 截断阈值 |
| `USE_KD_TREE_INTERPOLATION` | True | 是否启用 KDTree 插值 |

#### 降级比例监控

每个区域处理完成后会 log 降级比例，QC 报告中也会体现。高降级比例通常意味着：
- 区域内源点稀疏（面片覆盖率低）
- 三角形 landmark 位置定义与 mesh 实际覆盖范围偏差大
- 可在 QC 报告 `fallback_ratio` 字段中查看具体数值

### 步骤 6：QC 质量评估

**判定逻辑：**

```
fallback_ratio = n_fallback / n_target

if fallback_ratio ≤ 0.05:    → PASS   ✅  面片覆盖良好
elif fallback_ratio ≤ 0.20:  → WARN   ⚠️  边缘区域覆盖不足
else:                        → FAIL   ❌  三角形区域可能定义不当或 mesh 质量差
```

QC 记录中额外记录了 `source_point_count`（区域内源点数）和 `source_face_count`（区域内源面片数），便于回溯诊断。

---

## 执行入口说明

`scripts/parameterize_ear.py` 是整个项目的唯一命令行入口。

```python
# 无参数 → 模拟模式
python scripts/parameterize_ear.py

# 带参数 → 单样本模式
python scripts/parameterize_ear.py --sample_id S001 --side R --mesh ... --landmarks ...
```

**调用链：**

```
scripts/parameterize_ear.py
  │
  ├─ 无参数 ──▶ ear_param/run.py → run_simulation()
  │                ├── ear_param/synthetic.py → generate_all_simulated_data()
  │                ├── ear_param/io_utils.py  → load_mesh(), load_landmarks(), read_csv_robust()
  │                └── ear_param/core.py      → process_region() × 区域数 × 样本数
  │
  └─ 有参数 ──▶ ear_param/run.py → run_single_sample()
                   ├── ear_param/io_utils.py  → load_mesh(), load_landmarks()
                   └── ear_param/core.py      → process_region() × 区域数
```

---

## 日志系统

### 设计思路

- **双通道输出**：控制台看关键进展（INFO），文件记录全部细节（DEBUG）。
- **每样本独立日志**：不同样本的日志写入不同文件，互不干扰。
- **时间戳命名**：`{sample_id}_{side}_parameterize_{YYYYMMDD}_{HHMMSS}.log`，不会覆盖历史日志。

### 日志格式

```
2026-07-06 10:00:01 | INFO    | [S001_R] 处理区域 T001: 耳甲腔上区
2026-07-06 10:00:01 | DEBUG   |     三角形顶点: A(L10)=[12.3, -5.1, 8.7], ...
2026-07-06 10:00:01 | DEBUG   |     源点数: 264 (从 1500 个顶点中裁剪)
2026-07-06 10:00:01 | DEBUG   |     源面片数: 150
2026-07-06 10:00:01 | DEBUG   |     目标采样网格: resolution=8, 点数=45
2026-07-06 10:00:01 | DEBUG   |     point-in-triangle: 45/45 成功, 0 个点使用最近邻兜底
2026-07-06 10:00:01 | INFO    |     -> 源点=264, 源面片=150, 采样点=45, 兜底=0(0.0%), 状态=PASS
```

### 日志查找指南

| 想看什么 | 去哪里 |
|----------|--------|
| 整体运行状态 | `SIMULATION_ALL_*.log`（INFO 级别即可） |
| 某个样本为什么 FAIL | 该样本的 `{sample_id}_R_*.log`，搜索 "FAIL" 或 "兜底" |
| 某个区域的具体源点数 | 搜索 "源点数" |
| 兜底插值详情 | 搜索 "最近邻兜底" |

---

## 配置参数速查

所有参数集中在 `ear_param/config.py`：

| 参数 | 默认值 | 说明 | 调参建议 |
|------|:---:|------|------|
| `PROJECTION_TOL` | 0.15 | 裁剪容差（允许 λ 超出 [0,1] 的幅度） | 源点太少 → 增大；误入太多 → 减小 |
| `FALLBACK_WARNING_THRESHOLD` | 0.05 | 兜底比例 WARNING 线 | — |
| `FALLBACK_FAIL_THRESHOLD` | 0.20 | 兜底比例 FAIL 线 | — |
| `MIN_SOURCE_POINTS` | 5 | 最小源点数（低于此走退化方案） | 视 mesh 精度而定 |
| `DENSE_SAMPLE_COUNT` | 5000 | 大 mesh 的随机采样上限 | 性能 vs 精度权衡 |
| `USE_KD_TREE_INTERPOLATION` | True | 启用 KDTree 插值 (v3.0) | 代替 Qhull LinearNDInterpolator |
| `KNN_K` | 12 | KDTree 近邻数 | 2D 空间最优平衡点 |
| `COLLINEARITY_THRESHOLD` | 1e-8 | PCA 方差比共线性阈值 | 低于此值降级到顶点插值 |
| `LSQ_RCOND` | 1e-12 | lstsq 截断阈值 | 奇异值过滤 |
| `SIMULATED_SAMPLES` | ["S001","S002","S003"] | 模拟样本数 | 增减以测试不同场景 |
| `SIMULATED_NOISE_LEVELS` | [0.25,0.35,0.28] | 各样本噪声幅度（mm） | 模拟个体差异程度 |

---

## 模拟数据说明

### 耳朵参数曲面

`synthetic.py` 使用参数曲面 `F(u, v) → (x, y, z)` 生成模拟耳朵，包含以下解剖结构：

| 结构 | 参数范围 | 效果 |
|------|----------|------|
| 基础椭圆 | u,v ∈ [0,1] | 耳朵基础外形（35mm × 60mm） |
| 耳甲腔凹陷 | u∈[0.3,0.7], v∈[0.4,0.7] | 中央深度凹陷 |
| 耳屏突起 | u∈[0.6,0.75], v∈[0.3,0.5] | 前方小突起 |
| 三角窝凹陷 | u∈[0.35,0.65], v∈[0.65,0.85] | 上方凹陷 |
| 耳垂 | u∈[0.35,0.65], v∈[0.0,0.15] | 下方圆润突起 |

### 样本间差异

| 参数 | S001 | S002 | S003 |
|------|:---:|:---:|:---:|
| seed | 42 | 123 | 999 |
| noise_level | 0.25 | 0.35 | 0.28 |
| 顶点数 | 1500 | 1500 | 1500 |

三个样本共享相同的 landmark 位置（在参数空间中的预定义 (u, v) 坐标），但曲面本身因 seed 不同而形状各异。

### Landmarks 在参数空间中的位置

```
L10: (0.50, 0.55)  ← 耳甲腔中心（三角形公共顶点）
L15: (0.52, 0.20)  ← 对耳屏边缘
L19: (0.72, 0.45)  ← 耳屏上方
L20: (0.68, 0.38)  ← 对耳屏上方
L21: (0.70, 0.42)  ← 耳屏-对耳屏交界
L28: (0.38, 0.65)  ← 耳甲腔上缘
L29: (0.30, 0.72)  ← 耳甲腔上外缘
L30: (0.35, 0.40)  ← 耳甲腔前下缘
L31: (0.50, 0.35)  ← 耳甲腔下缘
```

---

## FAQ & 常见问题

### Q1：程序报 `特征点缺失: {...}` 错误？

区域定义表引用的 landmark ID 在 landmarks CSV 中不存在。检查：
- landmarks CSV 的 `landmark_id` 列是否包含所有 9 个所需 ID。
- 确保 CSV 格式正确（逗号分隔，UTF-8 编码）。

### Q2：某个区域的状态是 FAIL，怎么办？

FAIL 表示兜底插值比例超过 20%。可能原因和解决方案：

| 原因 | 诊断方法 | 解决 |
|------|----------|------|
| 三角形区域定义的 landmark 位置不准 | 检查 landmark 的 3D 坐标是否合理 | 修正 landmark 标注 |
| Mesh 在该区域面片稀疏 | 查看 `source_face_count` 是否 < 10 | 提高 mesh 分辨率 |
| 三角形区域过大 | 查看区域长度是否 > 40mm | 拆分区域或降低 resolution |
| 容差太小 | 查看 `source_point_count` 是否很低 | 增大 `PROJECTION_TOL` |

### Q3：为什么采样点数和预期不一样？

正常情况下 `sample_point_count == expected_point_count`。若不等，可能是源点不足导致走了退化方案（此时会输出一条 warning 日志）。

### Q4：模拟模式生成的 mesh 和 landmarks 在哪儿？

- Mesh：`data/clean_mesh/S00X_R.ply`
- Landmarks：`data/landmarks/S00X_R_landmarks.csv`

模拟模式每次运行都会**覆盖**这些文件。

### Q5：如何添加新的三角区域？

编辑 `config/region_table.csv`，新增一行即可：

```csv
region_id,region_name,lm_a,lm_b,lm_c,resolution,use_for_pca
T006,新区域名,L10,L20,L15,8,1
```

无需修改任何代码。

### Q6：如何调整采样密度？

修改 `config/region_table.csv` 中对应区域的 `resolution` 即可：

| resolution | 采样点数 |
|:---:|:---:|
| 4 | 15 |
| 6 | 28 |
| 8 | 45 |
| 10 | 66 |
| 12 | 91 |
| 16 | 153 |

### Q7：各版本有什么区别？

| 方面 | v1.0 | v2.0 | v3.0 |
|------|------|------|------|
| 插值器 | LinearNDInterpolator（Delaunay 重建） | Point-in-Triangle（原始 mesh 面片） | KDTree + 高斯加权最小二乘 |
| 拓扑保留 | 否（Delaunay 重建拓扑） | 是（严格使用原始面片） | 是（参数空间近邻局部拟合） |
| 兜底策略 | 3D 最近邻 | 参数空间最近邻 | 三角形顶点重心线性插值 |
| 跨结构映射风险 | 有（3D 最近邻可能跳区） | 无（参数空间最近邻） | 无（局部加权 + 共线性检测） |
| Qhull 依赖 | 有 | 有 | 无（纯 KDTree） |

---

## 下一步工作

1. ~~**二维展开 (UV Unwrapping)**~~ ✅ 已完成（2026-07-06）
2. ~~**Qhull 性能瓶颈消除**~~ ✅ 已完成（2026-07-07）：`_interpolate_sample_points` 彻底替换为 KDTree + 高斯加权最小二乘，移除所有 Qhull 依赖
3. ~~**可视化模块**~~ ✅ 已完成（2026-07-07）：`visualization.py` 支持各区域散点图、3D 概览、QC 热力图、Atlas 全局展开图
4. ~~**单元测试套件**~~ ✅ 已完成（2026-07-07）：73 个测试覆盖退化检测、重心坐标、插值降级、端到端流程、回归测试
5. **PCA 特征值分析**：堆叠所有样本的采样点为数据矩阵，执行 PCA 降维。
6. **区域补丁文件支持**：允许用独立的 patch mesh 替代三角形裁剪（处理 landmark 定义无法完全覆盖目标区域的情况）。
7. **并行化**：不同样本的参数化完全独立，可用 multiprocessing 并行处理。
8. **文档目录**：添加 `docs/` 目录，包括环境搭建指南、真实数据目录约定、区域表扩展方法。

---

## 版本历史

| 日期 | 版本 | 主要变更 |
|------|:---:|------|
| 2026-07-03 | v1.0 | 初始流水线：Qhull (LinearNDInterpolator) + 3D 最近邻兜底 |
| 2026-07-06 | v2.0 | Point-in-Triangle 面片感知插值 + 参数空间最近邻兜底；UV 展开；项目结构扁平化 |
| 2026-07-07 | v3.0 | **KDTree + 高斯加权最小二乘插值**，彻底移除 Qhull 依赖；新增可视化模块 (480 行)；新增 73 个单元测试（全部通过）；QC 报告修复与增强 |
