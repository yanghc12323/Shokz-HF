# Daily Report - 2026/07/03 (Thu)

## 负责人 / Author

杨皓臣 (yanghc)

---

## 核心任务

基于技术文档《人头给你了-3D 耳模型跨模型参数化与特征值计算技术执行文档 v0.0》，搭建 **3D 耳模型参数化处理流水线（parameterize_ear.py）**，核心目标是 **将划分的三维三角区域投影至二维平面，进行降采样处理，限定每个区域的采样点数量相同**。

### 关键算法流程

1. **三角区域分包** （依据 `config/region_table.csv` 中 A/B/C 三个 landmark）
2. **重心坐标平面投影** — 将三维源点映射到以 landmark 定义的三角形参数平面
3. **固定分辨率降采样** — 在标准三角形上按等间距网格生成固定数量采样点，**跨模型同名区域采样点数完全一致**
4. **插值重建三维坐标** — LinearNDInterpolator + cKDTree 兜底

---

## 当前进展 / Deliverables

### 1. 项目结构

```
ear_project/
├── scripts/
│   └── parameterize_ear.py          # 主脚本（一键运行）
├── config/
│   └── region_table.csv             # 区域定义表（5 个区域）
├── data/
│   ├── clean_mesh/                  # 模拟 .ply mesh（3 个样本）
│   └── landmarks/                   # 模拟 landmarks.csv
├── output/
│   ├── parameterized_points/        # 结果点云 CSV
│   ├── qc/                          # QC 报告 CSV
│   └── logs/                        # 运行日志
├── requirements.txt
├── .gitignore
└── Daily_Report_2026-07-03.md
```

### 2. 模拟数据

| 样本 | 区域数 | 每个样本总采样点 | QC PASS | QC FAIL |
|------|--------|-----------------|---------|----------|
| S001_R | 5 | **167** | 5 | 0 |
| S002_R | 5 | **167** | 5 | 0 |
| S003_R | 5 | **167** | 5 | 0 |

### 3. 各区域采样配置

| 区域 ID | 名称 | resolution | 固定采样点数 | 用途 |
|---------|------|-----------|-------------|------|
| T001 | 耳甲腔上区 | 8 | 45 | PCA |
| T002 | 耳甲腔前下区 | 8 | 45 | PCA |
| T003 | 耳屏对耳屏区 | 6 | 28 | PCA |
| T004 | 耳道入口区 | 5 | 21 | PCA |
| T005 | 耳根上后区 | 6 | 28 | 参考 |

### 4. 一键运行

```bash
cd ear_project
python scripts/parameterize_ear.py
# 无参数 = 自动进入模拟模式，生成数据 → 参数化 → 输出
# python scripts/parameterize_ear.py --help 可查看真实数据对接方式
```

---

## 遇到的问题与解决

| # | 问题 | 根因 | 解决方案 |
|---|------|------|---------|
| 1 | `RegularGridInterpolator` 维度不匹配 | `Z.T` 转置错误，形状变为 `(v_vals, u_vals)` 而非 `(u_vals, v_vals)` | 移除错误的 `.T`，`meshgrid` 已用 `indexing="ij"` |
| 2 | `region_table.csv` 中文无法读取 | CSV 文件为 GBK 编码，pandas 默认 UTF-8 | 新增 `read_csv_robust()` 自动尝试多编码 |
| 3 | 耳道入口区源点不足（8 < 10） | `MIN_SOURCE_POINTS` 设置为 10 过严 | 降至 5（极小解剖区域合理） |
| 4 | Windows GBK 控制台 Unicode 报错 | 摘要中使用 `✓/✗` 字符 | 替换为纯 ASCII `OK/FAIL` |

---

## 下一步 / TODO

- [ ] **等待真实数据到位** — 将模拟数据替换为扫描/分割的三维 mesh
- [ ] 接入真实 patch mesh（`data/patches/` 目录），验证 `--patch_dir` 参数通路
- [ ] 添加 `--side L` 左耳支持
- [ ] 实现 PCA 子空间嵌入与统计特征提取（phase 2）

---

## Git 仓库

- 远程仓库: https://github.com/yanghc12323/Shokz-HF.git
- 本地路径: `d:\YHC\人头项目\ear_project`
- **Push 操作指南：**

```bash
cd d:\YHC\人头项目\ear_project

# 初始化（首次）
git init
git remote add origin https://github.com/yanghc12323/Shokz-HF.git

# 提交并推送
git add .
git commit -m "Initial commit: 3D ear parameterization pipeline"
git push -u origin main
```

> 注意：需先安装 Git for Windows (`winget install --id Git.Git`) 才能执行 push。
> `.gitignore` 已配置排除 output/ 和 data/ 下的生成文件，只提交代码与配置。