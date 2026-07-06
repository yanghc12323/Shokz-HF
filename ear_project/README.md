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
A = \lVert\vec{S}\rVert
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

#### 步骤 2 机制澄清与局限性分析

**Q: 重心坐标筛选的具体规则是什么？**

当前方案使用的是**暴力三维→二维平面投影法**，流程分三步：

1. **取 mesh 顶点**：从完整耳 mesh 中读取所有顶点（若超过 5000 个则随机采样 5000 个）。
2. **正交投影**：对每个顶点 **P**，沿三角形平面的法向量方向做正交投影，落在平面上的投影点为 **P'**。详见步骤 3 的法方程求解过程。
3. **重心坐标范围判定**：计算 **P'** 在三角形 (**A**, **B**, **C**) 中的重心坐标 $\lambda_a, \lambda_b, \lambda_c$。若三个分量均落在 $[-0.15, 1.15]$ 区间内，则该顶点被纳入"源点"集合。

换句话说，**筛选的是"正交投影脚印落在三角形内部（含边界容差）"的三维 mesh 顶点**。筛选过程的示意图：

```
    耳 mesh 顶点 (分布在曲面上)
    ·  ·  ·  ·  ·  ·  ·  ·  ·
     ·  ·  ·  P1  ·  ·  P2·
      ·  ·  ↓投影  ·  ·  ↓投影
       ·  ·  ·  ·  ·  ·  ·  ·
        ─────────────────────  ← 三角形平面 (A,B,C 张成)
         P1'✓(在三角形内)   P2'✗(在三角形外)
```

**Q: 有没有更合适的方法？**

有。组员调研文档中的方法更精确，但工程复杂度更高：

| 维度 | 当前方案（正交投影 + tolerance） | 更优方案（geodesic 路径 + flood fill） |
|:---|:---|:---|
| **边界定义** | 在三维空间中，以三角形平面为基准，用 tolerance=0.15 做软边界 | 在 mesh **表面** 沿 landmark 之间的最短路径（geodesic path）走，形成精确的闭合边界 |
| **区域内点判定** | 投影到平面后判断重心坐标是否在 [−τ, 1+τ] 内 | 三条 geodesic 边界在 mesh 表面围成的连通面片集合（flood fill） |
| **优点** | 实现简单，不依赖 mesh 拓扑质量 | 边界语义精确，不会误纳相邻解剖结构（如耳轮内侧的顶点混入耳甲腔区域） |
| **缺点** | tolerance 是经验值，无法保证不误纳相邻结构的顶点；且投影到平面后再判断，丢失了曲面法向信息 | 需要 mesh 无孔洞/非流形边；geodesic 路径计算需要 libigl 等 C++ 依赖；实现和调试成本高 |
| **适用场景** | 快速原型、区域划分较细（三角形较小）时平面近似可接受 | 生产级精度要求、mesh 质量有保证、区域划分较粗时 |

**当前方案选择平面投影+tolerance 的权衡理由**：
- 你目前还没有拿到真实数据，mesh 质量和 landmark 精度未知
- 先用简单方法跑通流程，生成初步 PCA 结果看主成分是否合理
- 如果后续发现源点裁剪质量差（例如 QC 显示某些区域 fallback_ratio 过高，或 PCA 结果显示区域间混淆），再升级为 geodesic 路径方案

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

最小化残差平方和 $\lVert\mathbf{r}\rVert^2$（即正交投影），对 $u, v$ 求偏导并令其为 0，得到法方程：

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

#### 步骤 3 机制澄清：投影方式、求解过程与二维平面的真实面貌

**Q: 步骤 3 是直接做投影吗？是哪种投影？**

是的，步骤 3 对每个三维点 **P** 做的是**正交投影**（orthogonal projection）：沿三角形平面的法向量方向，将 **P** 垂直 "丢" 到平面上，落点 **P'** 是平面上离 **P** 最近的点。这不同于透视投影或沿任意方向的斜投影。

```
     ● P (三维空间中的 mesh 顶点)
     |\
     | \  ← 残差向量 r = P − P'（必然垂直于平面）
     |  \
     |   \
  ───●────●──  ← 三角形平面
     P'  A
```

投影方向由三角形平面唯一确定（法向量 $\mathbf{n} = \mathbf{e}_1 \times \mathbf{e}_2$）。所有源点都是沿这个方向投影的，因此不同源点的投影距离不同——离平面越远的点，投影后"移动"越大。

**Q: u 和 v 具体是如何算出来的？**

上面 3.2 节给出了法方程的矩阵形式 $\mathbf{G} \begin{bmatrix}u \\ v\end{bmatrix} = \mathbf{r}$，下面展开一步步计算：

**第 1 步：构建 Gram 矩阵 G（2×2）**

$$
\mathbf{G} = \begin{bmatrix}
\mathbf{e}_1 \cdot \mathbf{e}_1 & \mathbf{e}_1 \cdot \mathbf{e}_2 \\
\mathbf{e}_1 \cdot \mathbf{e}_2 & \mathbf{e}_2 \cdot \mathbf{e}_2
\end{bmatrix}
$$

即：
- $g_{11} = \lVert \mathbf{B} - \mathbf{A} \rVert^2$（AB 边长度的平方）
- $g_{22} = \lVert \mathbf{C} - \mathbf{A} \rVert^2$（AC 边长度的平方）
- $g_{12} = g_{21} = (\mathbf{B} - \mathbf{A}) \cdot (\mathbf{C} - \mathbf{A})$（两边夹角的余弦 × 两边长度乘积）

**第 2 步：构建右端向量 r（2×1）**

$$
\mathbf{r} = \begin{bmatrix}
(\mathbf{P} - \mathbf{A}) \cdot \mathbf{e}_1 \\
(\mathbf{P} - \mathbf{A}) \cdot \mathbf{e}_2
\end{bmatrix}
$$

这是点 **P** 在 $\mathbf{e}_1$ 和 $\mathbf{e}_2$ 方向上的投影长度。

**第 3 步：解 2×2 线性方程组得到 u, v**

手动求解（Cramer 法则）：

$$
\det(\mathbf{G}) = g_{11} \cdot g_{22} - g_{12}^2 = \lVert \mathbf{e}_1 \times \mathbf{e}_2 \rVert^2 = (2 \cdot \text{三角形面积})^2
$$

$$
u = \frac{r_1 \cdot g_{22} - r_2 \cdot g_{12}}{\det(\mathbf{G})}, \qquad
v = \frac{r_2 \cdot g_{11} - r_1 \cdot g_{12}}{\det(\mathbf{G})}
$$

**代码实现**：`numpy.linalg.solve(G, r)` 直接求解，比手动 Cramer 法则更数值稳定。

**第 4 步：得到重心坐标**

$$
\lambda_b = u, \quad \lambda_c = v, \quad \lambda_a = 1 - u - v
$$

**Q: 投影下来的二维平面是什么样的？**

这是一个容易被忽视的关键点。投影下来的 "2D 平面" 是**三角形 A、B、C 在 3D 空间中实际张成的物理平面**。在这个平面上，我们建立了一个以 A 为原点、$\mathbf{e}_1$（即 $\overrightarrow{AB}$）和 $\mathbf{e}_2$（即 $\overrightarrow{AC}$）为坐标轴的**斜角坐标系**。

```
           C = (0,1) in (u,v) coords
           /\
          /  \
         /    \
        /  ●P' \
       /        \
      /          \
  A=(0,0)──────B=(1,0)
         e₁
```

**关键事实：$\mathbf{e}_1$ 和 $\mathbf{e}_2$ 通常不是正交的，长度也未必相等。**

这意味着：

| 特征 | 说明 |
|:---|:---|
| **坐标系原点** | A（三维 landmark 的位置） |
| **u 轴（水平方向）** | 沿 $\overrightarrow{AB}$ 方向，单位长度 = $\|\mathbf{e}_1\|$（即 AB 边长） |
| **v 轴（斜向上方向）** | 沿 $\overrightarrow{AC}$ 方向，单位长度 = $\|\mathbf{e}_2\|$（即 AC 边长） |
| **u 轴和 v 轴的夹角** | 等于 AB 和 AC 在实际 3D 空间中的夹角（通常不是 90°） |
| **坐标范围** | (u, v) 在三角形内部 = u ≥ 0, v ≥ 0, u+v ≤ 1 |
| **(u, v) 到 3D 点的映射** | $\mathbf{P}' = \mathbf{A} + u \cdot \overrightarrow{AB} + v \cdot \overrightarrow{AC}$ |

**这个斜角坐标系带来的重要后果**：在 (u, v) 参数空间中，两点之间的欧氏距离不等于它们在 3D 三角形平面上的欧氏距离。例如：

- 当 AB 远长于 AC 时，u 方向每变化 0.1 对应的 3D 实际距离远大于 v 方向变化 0.1 的距离
- 后续步骤 5 中 `LinearNDInterpolator` 在 (u, v) 空间中做 Delaunay 三角剖分和插值时，使用的距离度量是 (u, v) 上的欧氏距离，**不等于 3D 平面上的实际距离**

**与组员方案（Harmonic 参数化）的根本区别**：

| 维度 | 当前方案（正交投影 + (u,v) 斜角坐标） | 组员方案（Harmonic / UV 参数化） |
|:---|:---|:---|
| **投影方式** | 正交投影到三角形平面（每个点沿法向量方向投影） | 不做投影；在 mesh 表面求解 Laplacian 方程，为每个顶点分配 UV |
| **2D 域** | 三角形 A、B、C 张成的物理 3D 平面 + 斜角坐标系 | 标准 UV 正方形或三角形，边界固定在标准位置上 |
| **距离保真** | 差。斜角坐标系中 (u,v) 的欧氏距离 ≠ 3D 实际距离 | 好。Harmonic 最小化边拉伸能量，尽量保持局部相对距离 |
| **适用条件** | 三角形区域近似平坦（曲率小）时误差可接受 | 不依赖平坦假设，曲率大的区域也能处理 |

**一句话总结**：当前方案的步骤 3 本质是把 3D 曲面上的采样问题，通过正交投影降维到 3D 空间中的三角形斜角平面上来处理。这在区域曲率不大时是可接受的近似，但斜角坐标系的距离失真和正交投影的"穿过空气"效应（mesh 顶点到平面的距离被忽略）是方法的核心局限。

---

### 步骤 4：固定分辨率重心坐标网格生成

**目的**：在三角形参数域内生成均匀分布的目标采样网格点。这些网格点的重心坐标是纯数学计算，与具体 mesh 无关，保证了跨样本的一致性。

**数学定义**：

设采样分辨率为 $R$（`resolution`），步长 $\Delta = 1/R$。

对于所有非负整数对 $(i, j)$ 满足 $i + j \leq R$，定义网格点的重心坐标为：

$$
\lambda_b(i, j) = i \cdot \Delta = \frac{i}{R}
\qquad
\lambda_c(i, j) = j \cdot \Delta = \frac{j}{R}
\qquad
\lambda_a(i, j) = 1 - \lambda_b - \lambda_c
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

#### 步骤 4 机制澄清：resolution 取点与"三角形边上剖面等分"的区别

**Q: resolution 是如何取点的？是在真实 3D 模型构成的三角形边上做剖面再均分 n 份进行取点吗？**

**不是。** 当前方案的采样点**不是**在 3D 三角形边或 mesh 表面上直接操作的，而是在**抽象的二维重心坐标参数域**中按纯数学规则生成的。具体来说：

1. **参数域**：一个虚拟的标准三角形，三个顶点分别对应纯重心坐标 A=(1,0,0)、B=(0,1,0)、C=(0,0,1)。这个三角形**不是 3D 空间中的几何对象**，而是重心坐标空间中的抽象坐标系。
2. **取点规则**：设 resolution = R = 8，在参数域中沿 λb 方向（从 A 到 B 的边）等分为 8 段，沿 λc 方向（从 A 到 C 的边）等分为 8 段，在三角形内部生成 `(8+1)×(8+2)/2 = 45` 个等间距网格点。
3. **与 3D 三角形的关系**：这些参数域网格点**不直接等于**三角形三个 landmark 在 3D 空间中张成的平面上的等间距点。例如，参数域中的点 (λa=0.25, λb=0.75, λc=0) 位于"从 A 到 B 的边上，离 B 更近"的参数位置，但这个位置对应的 3D 坐标是**通过后续步骤 5 的插值从源点推算出来的**，而不是简单取 3D 三角形边上 L29 到 L28 的 1/4 处。

换句话说，你关心的"在 3D 三角形边上做剖面等分"是**步骤 5（插值重建）的输出结果**，而不是步骤 4 的输入。步骤 4 只负责在参数域中生成"在哪里采样"的坐标蓝图。

**为什么不直接在 3D 三角形边上等分？**

因为在 3D 空间中沿 landmark 连线的直线做等分有一个关键缺陷：**landmark 之间的空间直线不经过 mesh 表面**。

```
  耳 mesh 表面 (有曲率)
     ╱ ╲
    ╱   ╲
  A●─────●B  ← 3D 直线 AB (穿过空气!)
    ╲   ╱
     ╲ ╱
```

三个 landmark 在 3D 空间中的连线只是空间直线段，它穿过的不是耳朵曲面而是空气。所以即便在 AB 边上等分 8 段拿到 9 个点，这些点也不在 mesh 表面上，不能直接当采样点使用——你需要额外的"投影到表面"步骤。

而当前的两阶段方法（参数域取点 → 插值回 3D）利用了 mesh 顶点本身已经落在曲面上的事实：源点 P1...Pm 就是 mesh 表面上的真实顶点，它们在参数域中的位置 (λb, λc) 记录了该顶点在三角形中的"相对位置"。用这些源点做插值，目标网格点就能落到表面上。

**总结**：

| 问题 | 答案 |
|:---|:---|
| resolution 在 3D 边上等分？ | ❌ 否。在抽象的**重心坐标参数域**中等分，不是在 3D 三角形边上操作 |
| 采样点是 mesh 表面上的点吗？ | ✅ 是。经过步骤 5 的插值重建后，输出点落在 mesh 表面上 |
| 为什么不在 3D 边上直接等分？ | 因为 3D landmark 连线是空间直线，不经过耳朵曲面，等分点不在表面上 |

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
\hat{\mathbf{P}}_t = \mathbf{P}_{k^*}, \quad \text{其中 } k^* = \mathrm{argmin}_k \; \lVert(\hat{\lambda}_{b,t}, \hat{\lambda}_{c,t}) - (\lambda_{b,k}, \lambda_{c,k})\rVert
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