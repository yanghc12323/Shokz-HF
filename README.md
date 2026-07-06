# 3D 耳模型跨模型参数化 — 参数化采样模块（2026-07-06）

> 技术依据：《人头给你了-3D 耳模型跨模型参数化与特征值计算技术执行文档-v0.0》第 3 章

---

## 目录

1. [项目概述](#项目概述)
2. [输入](#输入)
3. [输出](#输出)
4. [算法详解](#算法详解)
   - [步骤 1：三角形退化检测](#步骤-1三角形退化检测)
   - [步骤 2：源点裁剪（Mesh 顶点投影筛选）](#步骤-2源点裁剪mesh-顶点投影筛选)
   - [步骤 3：重心坐标批量计算（最小二乘投影）](#步骤-3重心坐标批量计算最小二乘投影)
   - [步骤 4：固定分辨率重心坐标网格生成](#步骤-4固定分辨率重心坐标网格生成)
   - [步骤 5：插值重建采样点三维坐标](#步骤-5插值重建采样点三维坐标)
   - [步骤 6：QC 质量评估](#步骤-6qc-质量评估)
5. [项目结构](#项目结构)
6. [快速开始](#快速开始)
7. [配置参数速查](#配置参数速查)
8. [下一步工作](#下一步工作)

---

## 项目概述

本模块实现**三维三角区域 → 二维平面投影 → 均匀降采样 → 插值重建**的完整流水线。

### 核心思路

将 3D 耳 mesh 上由 3 个解剖特征点（landmark）定义的三角形区域（如耳甲腔上区、耳屏区等），通过**重心坐标（Barycentric Coordinates）** 将区域内的所有 mesh 顶点投影到三角形确定的二维参数平面上，在参数域中按固定分辨率生成均匀分布的采样网格点，再由三角区域内的源点坐标插值重建出每个采样网格点的三维空间坐标。

### 为什么需要这一步？

不同样本（不同人的耳朵）的 mesh 顶点数量、面片拓扑、顶点分布都不同，无法直接进行跨样本的统计分析（如 PCA 特征值分析）。通过参数化采样，将每个样本的任意三角区域统一为**固定数量、固定拓扑排列**的采样点集，使得：

- 每个区域在每个样本上的采样点数**完全相同**（当前为每区 45 点，共 5 区 225 点）
- 采样点在参数空间中的位置（重心坐标）**固定且可溯源**
- 所有样本的采样点按相同顺序排列，可直接堆叠为数据矩阵进行 PCA

### 输入输出总览

```
┌──────────────────┐                          ┌──────────────────────────────┐
│  输入             │                          │  输出                         │
│                   │     ┌──────────────┐      │                              │
│  耳 Mesh (.ply)   │────▶│              │─────▶│  采样点 CSV (225 点 × N 样本) │
│  Landmarks (.csv) │────▶│  参数化流水线  │─────▶│  QC 报告 CSV                 │
│  区域定义表 (.csv) │────▶│              │─────▶│  运行日志 .log               │
│                   │     └──────────────┘      │                              │
└──────────────────┘                          └──────────────────────────────┘
```

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
| `use_for_pca` | 1 = 用于 PCA 分析，0 = 仅辅助/可视化 |

当前定义 5 个区域：

| 区域 | 顶点 | resolution | 采样点数 |
|------|------|:---:|:---:|
| T001 耳甲腔上区 | L10–L29–L28 | 8 | 45 |
| T002 耳甲腔下区 | L10–L31–L30 | 8 | 45 |
| T003 耳甲腔前区 | L10–L28–L30 | 8 | 45 |
| T004 耳屏区 | L19–L21–L28 | 8 | 45 |
| T005 对耳屏区 | L20–L21–L15 | 8 | 45 |
| **合计** | | | **225** |

### 特征点需求

区域定义表中引用了以下 9 个 landmark（来自论文 31 个特征点子集）：

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

| 输出项 | 格式 | 目录 | 说明 |
|--------|------|------|------|
| **采样点文件** | `.csv` | `output/parameterized_points/` | 每个样本一份，包含所有 225 个采样点的坐标和元数据 |
| **QC 报告** | `.csv` | `output/qc/` | 每个样本一份，每个区域的采样质量评估（PASS / WARNING / FAIL） |
| **运行日志** | `.log` | `output/logs/` | 每个样本一份，记录完整的调试信息 |

### 采样点文件字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `sample_id` | str | 样本编号（如 `S001`） |
| `side` | str | 左右侧（`R` / `L`） |
| `region_id` | str | 区域编号（如 `T001`） |
| `region_name` | str | 区域中文名称（如 `耳甲腔上区`） |
| `point_id_global` | int | 全局采样点唯一编号（0–224） |
| `point_id_region` | int | 区域内采样点编号（从 0 开始） |
| `x, y, z` | float | 采样点在原始三维空间中的坐标（在 mesh 表面上） |
| `u, v` | float | 二维展开坐标（预留字段，当前为 NaN，后续实现 UV 展开时填充） |
| `lambda_a, lambda_b, lambda_c` | float | 重心坐标，满足 λa + λb + λc = 1，可完整溯源采样点在三角形中的位置 |
| `lm_a, lm_b, lm_c` | str | 三角形三个顶点对应的 landmark ID |

### 采样点排列顺序

全局采样点按区域顺序排列：T001(0–44) → T002(45–89) → T003(90–134) → T004(135–179) → T005(180–224)。

区域内采样点按重心坐标网格的行优先顺序排列（即 `make_barycentric_grid` 的生成顺序：i 从 0 到 resolution, j 从 0 到 resolution−i）。

### QC 报告字段说明

| 字段 | 说明 |
|------|------|
| `region_id` | 区域编号 |
| `region_name` | 区域名称 |
| `source_point_count` | 三角区域内的源点（mesh 顶点投影到三角形内部的）数量 |
| `sample_point_count` | 实际生成的采样点数 |
| `expected_point_count` | 预期采样点数（应与 sample_point_count 一致） |
| `fallback_ratio` | 最近邻兜底比例（见 [步骤 5](#步骤-5插值重建采样点三维坐标) 和 [步骤 6](#步骤-6qc-质量评估)） |
| `interpolator` | 使用的插值器名称 |
| `status` | 质量等级：`PASS` / `WARNING` / `FAIL` |

---

## 算法详解

以下是对照技术文档第 3 章，从输入到输出每一步的完整数学描述和代码实现说明。

### 步骤 1：三角形退化检测

**目的**：确保三个 landmark 确定的三角形是有效的（不共线、面积非零）。

**数学定义**：

设三角形三个顶点为 **A**, **B**, **C** ∈ ℝ³，计算：

$$
\vec{u} = \mathbf{B} - \mathbf{A}, \quad \vec{v} = \mathbf{C} - \mathbf{A}
$$

面积向量：

$$
\vec{S} = \vec{u} \times \vec{v}
$$

三角形面积（2 倍）：

$$
A = \|\vec{S}\|
$$

**退化判定**：若 $A < \varepsilon$（$\varepsilon = 10^{-6}$），则三点共线或重合，三角形退化，无法定义有效的参数域，直接抛出异常终止处理。

**代码位置**：`ear_param/core.py` → `_is_triangle_degenerate()`

---

### 步骤 2：源点裁剪（Mesh 顶点投影筛选）

**目的**：从完整耳 mesh 的顶点集中，筛选出落在三角形区域投影范围内的顶点作为"源点"，这些源点将用于后续插值。

**数学方法**：

1. **顶点采样**（性能优化）：若 mesh 顶点数超过 `DENSE_SAMPLE_COUNT`（默认 5000），随机采样 5000 个顶点参与计算。
2. **重心坐标计算**：对每个 mesh 顶点 **P** ∈ ℝ³，计算其在三角形 (**A**, **B**, **C**) 上的重心坐标 (λa, λb, λc)（计算方法详见 [步骤 3](#步骤-3重心坐标批量计算最小二乘投影)）。
3. **范围筛选**：在容差范围内检查 λ 是否满足三角形内部条件：

$$
\lambda_a \in [-\tau, 1+\tau], \quad
\lambda_b \in [-\tau, 1+\tau], \quad
\lambda_c \in [-\tau, 1+\tau]
$$

其中容差 $\tau = 0.15$（`PROJECTION_TOL`），用于包容 mesh 顶点与理想三角形平面之间的微小偏差。

**合格的源点**：满足上述范围约束的 mesh 顶点，即三维空间中投影到三角形内部（含容差边界）的点。

**代码位置**：`ear_param/core.py` → `_clip_points_to_triangle()`

> **注意**：tolerance 设为 0.15 而非 0，是因为实际 mesh 顶点不一定完全落在三角形平面上（耳朵表面有曲率），需要一定的容差来捕获三角形附近的顶点。

---

### 步骤 3：重心坐标批量计算（最小二乘投影）

**目的**：将任意三维点投影到三角形平面，并计算其在该平面上的重心坐标。这是整个参数化的数学核心，实现了 **3D → 2D 参数域** 的映射。

**数学推导**：

给定三角形顶点 **A**, **B**, **C** ∈ ℝ³，任意空间点 **P** ∈ ℝ³。

#### 3.1 建立局部坐标系

以 **A** 为原点，定义两个局部基向量：

$$
\mathbf{e}_1 = \mathbf{B} - \mathbf{A}, \quad \mathbf{e}_2 = \mathbf{C} - \mathbf{A}
$$

这两个向量张成三角形平面。

#### 3.2 最小二乘投影

设 **P** 在三角形平面上的投影点为 **P'**，其在局部坐标系中的坐标为 $(u, v)$：

$$
\mathbf{P}' = \mathbf{A} + u \cdot \mathbf{e}_1 + v \cdot \mathbf{e}_2
$$

投影残差向量：

$$
\mathbf{r} = \mathbf{P} - \mathbf{P}' = (\mathbf{P} - \mathbf{A}) - u\mathbf{e}_1 - v\mathbf{e}_2
$$

最小化残差平方和 $\|\mathbf{r}\|^2$（即正交投影），对 $u, v$ 求偏导并令其为 0，得到法方程：

$$
\begin{bmatrix}
\mathbf{e}_1 \cdot \mathbf{e}_1 & \mathbf{e}_1 \cdot \mathbf{e}_2 \\
\mathbf{e}_1 \cdot \mathbf{e}_2 & \mathbf{e}_2 \cdot \mathbf{e}_2
\end{bmatrix}
\begin{bmatrix} u \\ v \end{bmatrix}
=
\begin{bmatrix}
(\mathbf{P} - \mathbf{A}) \cdot \mathbf{e}_1 \\
(\mathbf{P} - \mathbf{A}) \cdot \mathbf{e}_2
\end{bmatrix}
$$

即 **Gu = r**，其中 G 是 2×2 的 Gram 矩阵。

#### 3.3 由 (u, v) 计算重心坐标

重心坐标与局部坐标的对应关系：

$$
\lambda_b = u, \quad \lambda_c = v, \quad \lambda_a = 1 - \lambda_b - \lambda_c
$$

恒满足 $\lambda_a + \lambda_b + \lambda_c = 1$。

#### 3.4 退化处理

当三角形退化（$\det(G) < 10^{-12}$）时，所有点退化为三角形质心：

$$
\lambda_a = \lambda_b = \lambda_c = \frac{1}{3}
$$

**代码位置**：`ear_param/core.py` → `_barycentric_batch()`, `barycentric_3d()`

---

### 步骤 4：固定分辨率重心坐标网格生成

**目的**：在三角形参数域内生成均匀分布的目标采样网格点。这些网格点的重心坐标是纯数学计算，与具体 mesh 无关，保证了跨样本的一致性。

**数学定义**：

设采样分辨率为 $R$（`resolution`），步长 $\Delta = 1/R$。

对于所有非负整数对 $(i, j)$ 满足 $i + j \leq R$，定义网格点的重心坐标为：

$$
\begin{aligned}
\lambda_b(i, j) &= i \cdot \Delta = \frac{i}{R} \\
\lambda_c(i, j) &= j \cdot \Delta = \frac{j}{R} \\
\lambda_a(i, j) &= 1 - \lambda_b - \lambda_c = 1 - \frac{i + j}{R}
\end{aligned}
$$

**网格点数**：

遍历 $i = 0, 1, \ldots, R$，对每个 $i$，$j = 0, 1, \ldots, R - i$：

$$
N_{\text{total}} = \sum_{i=0}^{R} (R - i + 1) = \frac{(R + 1)(R + 2)}{2}
$$

当 $R = 8$ 时：$N = (9 \times 10) / 2 = 45$。

**几何意义**：这些点均匀地覆盖了三角形参数域，构成了一个等间距的三角形网格：

```
        (0,R)                    λa=1
         /\
        /  \                    λb=0    λc=0
       /    \
      /      \        ← 共 (R+1)(R+2)/2 个等间距网格点
     /        \
    /__________\
 (R,0)        (0,R)

 λb=1          λc=1
```

遍历顺序为行优先（$i$ 先变化，$j$ 后变化），即先固定 $i=0$ 遍历所有 $j$，再 $i=1$，依此类推。

**代码位置**：`ear_param/core.py` → `make_barycentric_grid()`

---

### 步骤 5：插值重建采样点三维坐标

**目的**：已知源点（步骤 2 裁剪得到）的三维坐标及其重心坐标，反推出目标网格点（步骤 4 生成）在三维空间中的坐标。即 **2D 参数域 → 3D 空间** 的逆向映射。

**输入**：
- 源点三维坐标 $\{\mathbf{P}_k\}_{k=1}^{M}$，$\mathbf{P}_k \in \mathbb{R}^3$
- 源点重心坐标 $\{(\lambda_{a,k}, \lambda_{b,k}, \lambda_{c,k})\}_{k=1}^{M}$
- 目标网格重心坐标 $\{(\hat{\lambda}_{a,t}, \hat{\lambda}_{b,t}, \hat{\lambda}_{c,t})\}_{t=1}^{N}$

**输出**：目标网格点的三维坐标 $\{\hat{\mathbf{P}}_t\}_{t=1}^{N}$

#### 方法 1：LinearNDInterpolator（主要方法）

在重心坐标参数空间中，使用线性 N 维插值器。

由于重心坐标满足 $\lambda_a + \lambda_b + \lambda_c = 1$，实际只需 2 个自由度。选取 $(\lambda_b, \lambda_c)$ 作为参数空间的独立坐标（$\lambda_a$ 由约束确定），在 $(\lambda_b, \lambda_c) \in \mathbb{R}^2$ 空间中进行分段线性插值：

$$
\hat{\mathbf{P}}_t = \text{Interp}\big(\hat{\lambda}_{b,t}, \hat{\lambda}_{c,t} \mid \{(\lambda_{b,k}, \lambda_{c,k}) \to \mathbf{P}_k\}\big)
$$

**实现**：使用 `scipy.interpolate.LinearNDInterpolator`，基于 Delaunay 三角剖分在 $(\lambda_b, \lambda_c)$ 参数空间中插值。

**可能出现 NaN 的情况**：当目标网格点位于源点构成的凸包之外时（例如三角形边缘区域源点稀疏），线性插值器无法外推，返回 NaN。

#### 方法 2：cKDTree 最近邻兜底（兜底方法）

对于插值失败的 NaN 点，使用以下策略：

1. 在参数空间中，计算目标点与所有源点在 $(\lambda_b, \lambda_c)$ 空间中的欧氏距离
2. 选取距离最近的那个源点的三维坐标作为替代值

$$
\hat{\mathbf{P}}_t = \mathbf{P}_{k^*}, \quad \text{其中 } k^* = \operatorname*{argmin}_{k} \|(\hat{\lambda}_{b,t}, \hat{\lambda}_{c,t}) - (\lambda_{b,k}, \lambda_{c,k})\|
$$

**统计记录**：兜底使用的点数占总目标点数的比例称为 **fallback_ratio**，是 QC 质量评估的核心指标。

#### 方法 3：顶点直接插值（源点过少时）

当源点数量少于 `MIN_SOURCE_POINTS`（默认 5）时，无法进行有效的插值。此时使用三角形三个顶点直接线性组合：

$$
\hat{\mathbf{P}}_t = \lambda_a \cdot \mathbf{A} + \lambda_b \cdot \mathbf{B} + \lambda_c \cdot \mathbf{C}
$$

这是三角形平面上的精确点，但不一定落在 mesh 表面上（mesh 有曲率），仅作为退化的兜底方案。

**代码位置**：`ear_param/core.py` → `_interpolate_sample_points()`

---

### 步骤 6：QC 质量评估

**目的**：评估每个区域的采样质量，确保插值重建的可靠性。

**核心指标**：`fallback_ratio` — 使用了最近邻兜底（方法 2）的采样点比例。

**判定标准**：

| 条件 | 状态 | 含义 |
|------|:---:|------|
| $\text{fallback\_ratio} \leq 5\%$ | ✅ **PASS** | 绝大多数点通过线性插值成功重建，采样质量良好 |
| $5\% < \text{fallback\_ratio} \leq 20\%$ | ⚠️ **WARNING** | 较多点需要兜底，建议关注该区域源点密度 |
| $\text{fallback\_ratio} > 20\%$ | ❌ **FAIL** | 插值大面积失败，该区域采样结果不可靠 |

**阈值配置**：`ear_param/config.py` → `FALLBACK_WARNING_THRESHOLD`, `FALLBACK_FAIL_THRESHOLD`

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
│   ├── core.py                      ← 核心算法（裁剪/投影/采样/插值/QC）
│   ├── io_utils.py                  ← 文件 IO 与日志
│   ├── synthetic.py                 ← 模拟数据生成（无真实数据时使用）
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

依赖包：`numpy`, `pandas`, `scipy`, `trimesh`

### 2. 模拟模式（无真实数据时测试）

```bash
cd ear_project
python scripts/parameterize_ear.py
```

自动生成 3 个模拟样本（S001–S003），完成参数化，输出到 `output/` 目录。

模拟数据说明：
- 使用标准耳朵外形（宽 35mm、高 60mm、深 15mm）生成基础 mesh
- 每个样本使用不同的随机种子（42 / 123 / 999）引入个体差异
- 每个样本施加不同水平的噪声（0.25 / 0.35 / 0.28）模拟扫描误差
- 生成 13 个特征点（L02, L07, L10, L13, L15, L19, L20, L21, L26, L28, L29, L30, L31）

### 3. 真实数据模式（拿到数据后）

```bash
# 单样本
python scripts/parameterize_ear.py \
    --sample_id S001 --side R \
    --mesh data/clean_mesh/S001_R.ply \
    --landmarks data/landmarks/S001_R_landmarks.csv \
    --regions config/region_table.csv \
    --out_points output/parameterized_points/S001_R_points.csv \
    --out_qc output/qc/S001_R_qc.csv

# 批量处理
python scripts/parameterize_ear.py \
    --batch data/samples.csv \
    --regions config/region_table.csv
```

其中 `data/samples.csv` 格式：

```csv
sample_id,mesh_path,landmark_path,output_points,output_qc
S001,data/clean_mesh/S001_R.ply,data/landmarks/S001_R_landmarks.csv,output/parameterized_points/S001_R_points.csv,output/qc/S001_R_qc.csv
S002,data/clean_mesh/S002_R.ply,data/landmarks/S002_R_landmarks.csv,output/parameterized_points/S002_R_points.csv,output/qc/S002_R_qc.csv
```

---

## 配置参数速查（`ear_param/config.py`）

| 参数 | 默认值 | 说明 |
|------|:---:|------|
| `PROJECTION_TOL` | 0.15 | 重心坐标允许超出 [0, 1] 的容差范围。增大可捕获更多边缘源点，但可能引入三角形外的噪声 |
| `FALLBACK_WARNING_THRESHOLD` | 0.05 | 兜底比例超过 5% 触发 WARNING |
| `FALLBACK_FAIL_THRESHOLD` | 0.20 | 兜底比例超过 20% 触发 FAIL |
| `MIN_SOURCE_POINTS` | 5 | 三角区域内源点最小数量，低于此值无法进行线性插值，退化为顶点直接插值 |
| `DENSE_SAMPLE_COUNT` | 5000 | mesh 顶点采样上限，用于大 mesh 的性能优化。设为 `None` 可使用全部顶点 |
| `SIMULATED_NOISE_LEVELS` | [0.25, 0.35, 0.28] | 模拟样本的噪声水平（标准差，mm） |
| `SIMULATED_SEEDS` | [42, 123, 999] | 模拟样本的随机种子 |

---

## 下一步工作

当你拿到真实数据后，需要准备：

1. **耳 mesh 文件**
   - 格式：`.ply`（推荐）、`.obj` 或 `.stl`
   - 命名规范：`{sample_id}_{side}.ply`（如 `S001_R.ply`）
   - 放置在 `data/clean_mesh/` 目录下

2. **特征点 CSV**
   - 必须包含列：`landmark_id, x, y, z`
   - 命名规范：`{sample_id}_{side}_landmarks.csv`
   - 放置在 `data/landmarks/` 目录下

3. **检查 landmark 覆盖**
   - 确保 CSV 包含 `config/region_table.csv` 中所有引用的 landmark
   - 当前必须包含：L10, L15, L19, L20, L21, L28, L29, L30, L31

4. **如需自定义区域**
   - 编辑 `config/region_table.csv`，增减行即可
   - 每行格式：`region_id, region_name, lm_a, lm_b, lm_c, resolution, use_for_pca`
   - `resolution` 决定每区点数：`resolution=8 → 45 点`，`resolution=6 → 28 点`

5. **如需调参**
   - 编辑 `ear_param/config.py` 中的容差和阈值
   - 常见调节：若源点不足导致大量 WARNING，可适当增大 `PROJECTION_TOL`

6. **运行**
   - 按真实数据模式运行，每个样本生成一份采样点 CSV + QC 报告
   - 检查 QC 报告中 `status` 列，确保所有区域为 PASS