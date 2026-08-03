# PCA 形态极值、自动聚类与极端个体分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变既有 PCA 数值和任一 QC 门禁的前提下，输出四个 PC 极值形态、真实极值被试、自动形态聚类、候选极端个体、可复核 CSV/PLY/PNG，并在桌面端提供独立查看页。

**Architecture:** 将所有新计算放在 `ear_param/pca_morphology.py`：它只读取已成功的 `PcaInput` 与 `PcaResult`，返回结构化的后处理结果，再由专门写出函数创建 CSV、聚类平均耳和 PNG。`build_average_ear.py` 在原 PCA 输出完成后调用它；桌面端索引这些可选产物，并以 `ResultWorkbench` 内的独立标签页展示，不破坏旧运行的加载与现有复核页布局。

**Tech Stack:** Python 3.11、NumPy、Pandas、SciPy（Ward 层次聚类）、Matplotlib（Agg 后端）、Trimesh、PySide6、PyVista、pytest、pytest-qt。

**Execution status:** 已于 2026-08-03 完成。核心计算、CLI 产物、桌面端独立标签页、README 与主项目回归测试均已完成；完整仓库 `pytest` 另包含未安装的独立 `modules/ear-coordinate-transform` 子项目，因此该两项模块测试需在其独立环境中运行。

## Global Constraints

- 新增分析只消费已通过 Weld + 对齐门禁、已纳入 PCA 的数据；不得改变 Remesh、Salvage、Weld、配准、PCA 输入纳入或失败状态。
- `components.npy`、`scores.csv`、`explained_variance.csv`、平均耳和原 `pca_summary.csv` 的已有数值语义保持不变。
- 聚类仅作描述性分析；候选极端个体不触发任何 PASS/FAIL 变更。
- 不增加 scikit-learn 或联网依赖；仅使用现有 `requirements.txt` 中的 NumPy、SciPy、Pandas、Matplotlib、Trimesh。
- K 自动选择范围固定为 `2..min(6, n_samples-1)`，选择最高平均 silhouette score；并列选择较小 K。
- 聚类特征是达到 `variance_threshold` 的保留 PCA scores，每列 Z-score 后输入 Ward 层次聚类。
- 对同一输入、参数、排序，所有 CSV 顺序、极值选择和聚类编号必须可重复。
- PC 正负方向只表示当次 PCA 的统计正负；任何中文 UI 都必须区分“理论形态”和“真实被试”。
- 输出文件使用 UTF-8 CSV；桌面端读取失败或旧运行缺少该目录时显示“本次运行未生成 PCA 形态分析”，不能报错。

---

## File structure

| 路径 | 变更 | 职责 |
| --- | --- | --- |
| `ear_param/pca_morphology.py` | 新建 | PCA 后处理计算、确定性聚类、极值表、聚类平均耳、CSV/PNG/PLY 写出 |
| `ear_param/pca_average.py` | 修改 | 对 PC01/PC02 均存在的运行保证写出四个 `±2SD` 模式模型，原 PCA 数值不变 |
| `scripts/build_average_ear.py` | 修改 | 在原 PCA 成功后调用形态分析写出函数；打印简洁状态 |
| `desktop_app/artifact_indexer.py` | 修改 | 安全索引 PCA 根目录下可选的 `pca_morphology` CSV/PNG 产物 |
| `desktop_app/models.py` | 修改 | 增加 `LayerName.PCA_MORPHOLOGY`，供独立页面加载 PLY |
| `desktop_app/ui/pca_morphology_page.py` | 新建 | PCA 形态分析子页：摘要、表格、散点图、三维模型选择 |
| `desktop_app/ui/result_workbench.py` | 修改 | 在保持原结果复核布局的同时，以 `QTabWidget` 加入 PCA 形态分析页，并向其转交 `ArtifactIndex` |
| `desktop_app/ui/main_window.py` | 修改 | 为 PCA 形态分析页添加可读的工程风格样式 |
| `tests/test_pca_morphology.py` | 新建 | 纯计算、边界条件、产物和不改变原 PCA 输出的测试 |
| `tests/test_pca_average.py` | 修改 | 验证 PC02 即使未达到 75% 阈值也会作为形态展示模型写出 |
| `tests/test_desktop_artifact_indexer.py` | 修改 | 验证新旧 PCA 目录的安全索引和可选产物回退 |
| `tests/test_desktop_pca_morphology_page.py` | 新建 | 验证桌面端显示、无产物提示和模型选择 |
| `tests/test_desktop_result_workbench.py` | 修改 | 验证结果复核包含新的独立标签页且不移动旧 PCA score/查看器 |
| `README.md` | 修改 | 记录新增输出、统计口径、运行命令不变和解释限制 |

## Public interfaces

```python
# ear_param/pca_morphology.py
@dataclass(frozen=True)
class PcaMorphologyAnalysis:
    summary: pd.DataFrame
    pc_extreme_shapes: pd.DataFrame
    observed_pc_extremes: pd.DataFrame
    multivariate_extremes: pd.DataFrame
    cluster_k_selection: pd.DataFrame
    cluster_assignments: pd.DataFrame
    cluster_summary: pd.DataFrame
    cluster_mean_points: dict[str, np.ndarray]

def analyze_pca_morphology(
    inputs: PcaInput,
    result: PcaResult,
    *,
    variance_threshold: float,
    aligned_dir: Path,
) -> PcaMorphologyAnalysis

def write_pca_morphology_outputs(
    inputs: PcaInput,
    result: PcaResult,
    analysis: PcaMorphologyAnalysis,
    *,
    out_dir: Path,
) -> Path  # 返回 out_dir / "pca_morphology"
```

`ArtifactIndex` 增加以下可选字段，全部缺省为 `pd.DataFrame()` 或 `None`：

```python
pca_morphology_dir: Path | None
pca_morphology_summary: pd.DataFrame
pc_extreme_shapes: pd.DataFrame
observed_pc_extremes: pd.DataFrame
multivariate_extremes: pd.DataFrame
cluster_k_selection: pd.DataFrame
cluster_assignments: pd.DataFrame
cluster_summary: pd.DataFrame
pc1_pc2_clusters_figure: Path | None
pc_variance_scree_figure: Path | None
```

### Task 1: 创建确定性 PCA 形态后处理核心

**Files:**
- Create: `ear_param/pca_morphology.py`
- Create: `tests/test_pca_morphology.py`

**Interfaces:**
- Consumes: `ear_param.pca_average.PcaInput`, `ear_param.pca_average.PcaResult`。
- Produces: `PcaMorphologyAnalysis`, `analyze_pca_morphology()`；后续任务通过它写出产物。

- [ ] **Step 1: 写入会失败的极值与聚类测试**

在 `tests/test_pca_morphology.py` 创建一个 8 样本、2 个明确可分组形态变化的 `PcaInput` fixture；复用 `PcaInput` 的公共顶点和面。先声明期望接口：

```python
def test_analysis_selects_directional_extremes_and_auto_cluster_count():
    analysis = analyze_pca_morphology(inputs, result, variance_threshold=0.75, aligned_dir=tmp_path)

    assert set(analysis.observed_pc_extremes["direction"]) == {"plus", "minus"}
    assert set(analysis.observed_pc_extremes["component"]) == {"PC01", "PC02"}
    assert analysis.summary.loc[0, "cluster_status"] == "PASS"
    assert analysis.summary.loc[0, "selected_cluster_count"] == 2
    assert analysis.cluster_assignments["cluster_id"].nunique() == 2
```

增加两个边界测试：3 个样本得到 `cluster_status == "insufficient_sample_count"`；同分数时方向极值的 `sample_tag` 按字典序取第一个且 `tie_count` 正确。

- [ ] **Step 2: 运行测试，确认因模块不存在而失败**

Run: `pytest tests/test_pca_morphology.py -q`
Expected: FAIL，提示 `ModuleNotFoundError: No module named 'ear_param.pca_morphology'`。

- [ ] **Step 3: 实现数据模型、方向极值和特征选择**

在新模块中实现不可变 dataclass 和下列辅助函数。`component_count` 必须是 `min(result.n_components_75, len(result.components))`；若只有 1 个非零组件，PC02 表以不可用记录表示，不访问不存在的列。

```python
def _retained_scores(result: PcaResult) -> tuple[list[str], np.ndarray]:
    count = min(result.n_components_75, len(result.components))
    return [f"PC{index:02d}" for index in range(1, count + 1)], result.scores[:, :count]

def _directional_extremes(sample_tags: tuple[str, ...], scores: np.ndarray, names: list[str]) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for component_index, component in enumerate(("PC01", "PC02")):
        if component_index >= len(names):
            for direction in ("plus", "minus"):
                records.append({"component": component, "direction": direction,
                                "status": "unavailable_insufficient_nonzero_components"})
            continue
        values = scores[:, component_index]
        for direction, target in (("plus", values.max()), ("minus", values.min())):
            tied = sorted(tag for tag, value in zip(sample_tags, values) if np.isclose(value, target))
            records.append({"component": component, "direction": direction, "sample_tag": tied[0],
                            "score": float(target), "tie_count": len(tied),
                            "tied_sample_tags": ";".join(tied), "status": "available"})
    return pd.DataFrame(records)
```

所有输入 `sample_tags` 先排序并对 points/scores 使用同一重排索引，消除文件发现顺序差异。

- [ ] **Step 4: 实现 Ward 聚类与 silhouette 选 K**

只使用 SciPy，不添加新的 requirements。对 score 每列执行 `z = (x - mean) / std`；标准差为 0 的列丢弃并将列名写入摘要。使用 `scipy.cluster.hierarchy.linkage(features, method="ward")` 及 `fcluster(linkage_matrix, K, criterion="maxclust")`。用成对欧氏距离矩阵手写平均 silhouette：样本 `i` 的类内均距为 `a(i)`，到其他每个类的最小平均距离为 `b(i)`，样本分数为 `(b-a)/max(a,b)`；单样本类的分数定义为 0。

```python
def _average_silhouette(features: np.ndarray, labels: np.ndarray) -> float:
    distances = squareform(pdist(features, metric="euclidean"))
    values: list[float] = []
    for index, label in enumerate(labels):
        own = np.flatnonzero(labels == label)
        if len(own) <= 1:
            values.append(0.0)
            continue
        a = float(distances[index, own[own != index]].mean())
        b = min(float(distances[index, labels == other].mean())
                for other in np.unique(labels) if other != label)
        values.append((b - a) / max(a, b) if max(a, b) else 0.0)
    return float(np.mean(values))
```

枚举 `K=2..min(6, n-1)`，为每个 K 生成一行 `cluster_k_selection`。选择最高有限 score；以 `(-score, K)` 排序完成较小 K 的 tie-break。随后按类的 PC01 平均 score 从小到大重新编号为 `Cluster 01` 至 `Cluster 06`。

- [ ] **Step 5: 实现综合极端距离、聚类摘要和平均耳数据**

对标准化特征计算 `distance_to_center = np.linalg.norm(features, axis=1)`，用 `rank(method="min", ascending=False)` 及 `rank(pct=True)` 写出全部样本。候选标志为距离大于或等于其 95 百分位。对于每个最终 `cluster_id`，按成员行号对 `inputs.points` 求均值，保存至 `cluster_mean_points`，并写出成员以 `;` 串联的 `cluster_summary`。

`observed_pc_extremes` 中的可用记录通过 `sample_tag` join `cluster_assignments`，并补充 `score_z`、`aligned_mesh_path`（相对 PCA 根目录的规范相对路径）。不可用记录保留但这些字段为空。

- [ ] **Step 6: 运行核心测试，确认通过**

Run: `pytest tests/test_pca_morphology.py -q`
Expected: PASS；测试覆盖自动 K、确定性并列、样本不足、候选极端距离与聚类平均 points 的形状。

- [ ] **Step 7: 提交核心计算**

```powershell
git add ear_param/pca_morphology.py tests/test_pca_morphology.py
git commit -m "feat: analyze PCA morphology extremes and clusters"
```

### Task 2: 写出 PLY、CSV 与可读 PNG，并接入 CLI

**Files:**
- Modify: `ear_param/pca_average.py:161-221`
- Modify: `scripts/build_average_ear.py:15-53`
- Modify: `ear_param/pca_morphology.py`
- Modify: `tests/test_pca_average.py`
- Modify: `tests/test_pca_morphology.py`

**Interfaces:**
- Consumes: Task 1 的 `analyze_pca_morphology()` 与 `PcaMorphologyAnalysis`。
- Produces: PCA 根目录下 `pca_morphology/` 的 7 个 CSV、聚类平均耳 PLY 和 2 个 PNG；旧 CLI 参数保持不变。

- [ ] **Step 1: 写入会失败的产物测试**

新增测试调用原来的 `write_pca_outputs()` 后再调用形态写出函数，验证：

```python
morphology_dir = write_pca_morphology_outputs(inputs, result, analysis, out_dir=out_dir)
assert (morphology_dir / "pc_extreme_shapes.csv").is_file()
assert (morphology_dir / "observed_pc_extremes.csv").is_file()
assert (morphology_dir / "cluster_k_selection.csv").is_file()
assert (morphology_dir / "cluster_means" / "Cluster_01_mean.ply").is_file()
assert (morphology_dir / "figures" / "pc1_pc2_clusters.png").is_file()
assert (morphology_dir / "figures" / "pc_variance_scree.png").is_file()
```

另建一个 3 样本、2 非零 PC fixture，令 75% 阈值只保留 PC01；断言 `pc_modes/PC02_plus_2sd.ply` 和 `PC02_minus_2sd.ply` 均存在。

- [ ] **Step 2: 运行测试，确认缺少写出功能导致失败**

Run: `pytest tests/test_pca_average.py tests/test_pca_morphology.py -q`
Expected: FAIL，缺少 `write_pca_morphology_outputs` 或 PC02 PLY。

- [ ] **Step 3: 扩展 PCA 模式 PLY 写出规则，但不触及 PCA 数值**

在 `write_pca_outputs()` 中将模式写出数量设为：

```python
mode_count = min(
    len(result.components),
    max(result.n_components_75, 2),
)
for component_index in range(mode_count):
    displacement = result.components[component_index].reshape(result.mean_points.shape)
    scale = 2.0 * np.sqrt(result.explained_variance[component_index])
    mode_name = f"PC{component_index + 1:02d}"
    _export_mesh(mode_dir / f"{mode_name}_plus_2sd.ply", result.mean_points + scale * displacement, inputs.faces)
    _export_mesh(mode_dir / f"{mode_name}_minus_2sd.ply", result.mean_points - scale * displacement, inputs.faces)
```

这只会在原 75% 阈值不足两个 PC 时额外生成 PC02 的可视化 PLY；不修改 components、scores、解释方差或 `retained_component_count`。

- [ ] **Step 4: 实现稳定的写出与画图函数**

在 `pca_morphology.py` 中，`write_pca_morphology_outputs()` 必须：

1. 创建 `out_dir / "pca_morphology"`、`cluster_means`、`figures`；
2. 以固定列顺序写入设计文档列出的 CSV；
3. 对 `cluster_mean_points` 执行 `mesh_path = cluster_dir / f"{cluster_id}_mean.ply"`，再以 `trimesh.Trimesh(vertices=points, faces=inputs.faces, process=False).export(mesh_path)` 写 PLY；
4. 设置 `matplotlib.use("Agg", force=True)` 后绘图；
5. 画 PC1-PC2 图时，无聚类状态使用中性灰点；有聚类时按 `Cluster 01` 至 `Cluster 06` 的固定颜色循环；只标注四个可用方向极值；坐标轴格式包含对应解释方差百分比；
6. 画 Scree 图时以柱图显示解释方差、折线显示累计方差、虚线表示 `variance_threshold`，并标记 `result.n_components_75`；
7. 对 PC01/PC02 写 `pc_extreme_shapes.csv`，路径统一相对 PCA 根目录，例如 `pc_modes/PC01_plus_2sd.ply`；不存在组件时写状态而非不存在路径。

`pca_morphology_summary.csv` 至少写入 `status`、`reason`、`included_sample_count`、`feature_component_count`、`cluster_status`、`selected_cluster_count`、`extreme_percentile_threshold`。

- [ ] **Step 5: 在 CLI 中调用后处理并保留原命令兼容**

在 `scripts/build_average_ear.py` 的原三行 PCA 调用后加入：

```python
from ear_param.pca_morphology import analyze_pca_morphology, write_pca_morphology_outputs

analysis = analyze_pca_morphology(
    inputs, result,
    variance_threshold=args.variance_threshold,
    aligned_dir=Path(args.aligned_dir),
)
morphology_dir = write_pca_morphology_outputs(inputs, result, analysis, out_dir=Path(args.out_dir))
print(f"[W3 PCA] Morphology analysis: {analysis.summary.loc[0, 'status']}")
print(f"[W3 PCA] Morphology output: {morphology_dir}")
```

不得增加必填 CLI 参数；现有 `run_full_pipeline.py` 通过既有 PCA 子命令自动得到新产物。

- [ ] **Step 6: 运行产物与 CLI 回归测试**

Run: `pytest tests/test_pca_average.py tests/test_pca_morphology.py tests/test_pipeline.py -q`
Expected: PASS。额外运行：

```powershell
python scripts/build_average_ear.py --help
```

Expected: 显示原有 4 个参数，未增加新的必填参数。

- [ ] **Step 7: 提交 CLI 与输出产物**

```powershell
git add ear_param/pca_average.py ear_param/pca_morphology.py scripts/build_average_ear.py tests/test_pca_average.py tests/test_pca_morphology.py
git commit -m "feat: export PCA morphology artifacts and figures"
```

### Task 3: 安全索引 PCA 形态分析产物

**Files:**
- Modify: `desktop_app/artifact_indexer.py:16-116`
- Modify: `tests/test_desktop_artifact_indexer.py`

**Interfaces:**
- Consumes: Task 2 的 `selected_pca_dir / pca_morphology` 内固定文件名。
- Produces: 扩展的 `ArtifactIndex`；Task 4 仅通过这些字段读取形态结果，不直接信任 CSV 中的路径。

- [ ] **Step 1: 写入新旧运行索引测试**

在桌面索引 fixture 中添加 `pca_gpa_r24/pca_morphology/` 和最小合法 CSV，断言：

```python
index = ArtifactIndexer().index(attempt)
assert index.pca_morphology_dir == pca_dir / "pca_morphology"
assert index.cluster_assignments.loc[0, "cluster_id"] == "Cluster 01"
assert index.pc1_pc2_clusters_figure == pca_dir / "pca_morphology" / "figures" / "pc1_pc2_clusters.png"
```

保留没有 `pca_morphology` 目录的 fixture，断言所有新增 DataFrame 为空、路径为 `None`，且 `index()` 不抛错。

- [ ] **Step 2: 运行索引测试，确认 dataclass 缺少字段而失败**

Run: `pytest tests/test_desktop_artifact_indexer.py -q`
Expected: FAIL，提示 `ArtifactIndex` 尚无 `pca_morphology_dir`。

- [ ] **Step 3: 扩展 ArtifactIndex 与安全可选读取**

在 `ArtifactIndex` 增加计划开头定义的字段。加入私有方法：

```python
def _optional_child_dir(parent: Path | None, name: str) -> Path | None:
    candidate = None if parent is None else parent / name
    return candidate if candidate is not None and candidate.is_dir() else None

def _optional_csv(directory: Path | None, name: str) -> pd.DataFrame:
    return ArtifactIndexer._read_csv(None if directory is None else directory / name)
```

只从已通过 `_selected_output_dir()` 和 `_output_dirs()` 验证的 PCA 根目录派生路径；不得将 CSV 内任意路径解析为桌面端可访问文件。对存在的 CSV 和 PNG 加入 `evidence`，标签分别为“PCA 形态汇总”“聚类分配”“PC1-PC2 聚类图”“PCA 方差图”。

- [ ] **Step 4: 运行索引测试，确认通过**

Run: `pytest tests/test_desktop_artifact_indexer.py -q`
Expected: PASS。

- [ ] **Step 5: 提交索引功能**

```powershell
git add desktop_app/artifact_indexer.py tests/test_desktop_artifact_indexer.py
git commit -m "feat: index PCA morphology artifacts"
```

### Task 4: 在结果复核中增加独立 PCA 形态分析页

**Files:**
- Modify: `desktop_app/models.py:25-31`
- Create: `desktop_app/ui/pca_morphology_page.py`
- Modify: `desktop_app/ui/result_workbench.py:41-270`
- Modify: `desktop_app/ui/main_window.py:223-271`
- Create: `tests/test_desktop_pca_morphology_page.py`
- Modify: `tests/test_desktop_result_workbench.py`
- Modify: `tests/test_desktop_ui_flow.py`

**Interfaces:**
- Consumes: Task 3 的扩展 `ArtifactIndex`，以及 `selected_alignment_dir` 中可信的 `{sample_tag}_aligned_whole_ear.ply`。
- Produces: `PcaMorphologyPage.set_attempt(index: ArtifactIndex)`；它在独立标签页中显示图表和表格，并将选中的 PLY 加载到自身 `MeshViewer`。

- [ ] **Step 1: 写入形态页失败测试**

创建 `tests/test_desktop_pca_morphology_page.py`，从现有 `artifact_index()` fixture 派生一个具备最小形态 CSV/PNG/PLY 的索引。测试：

```python
page.set_attempt(index)
assert page.status_label.text() == "PCA 形态分析已生成"
assert page.cluster_table.item(0, 0).text() == "Cluster 01"
assert page.observed_extremes_table.item(0, 2).text() == "T049_L"

page.set_attempt(old_index_without_morphology)
assert "未生成" in page.status_label.text()
assert not page.model_selector.isEnabled()
```

为模型加载选择测试注入假的 `MeshViewer`，验证选择 `PC01_plus_2sd.ply` 或 `Cluster_01_mean.ply` 时调用 `load_layer(LayerName.PCA_MORPHOLOGY, ArtifactRef("PCA 形态模型", model_path))`。真实被试使用安全构建的 `selected_alignment_dir / f"{sample_tag}_aligned_whole_ear.ply"`，不读取 CSV 中的路径。

- [ ] **Step 2: 运行桌面测试，确认页面尚不存在**

Run: `pytest tests/test_desktop_pca_morphology_page.py -q`
Expected: FAIL，提示 `desktop_app.ui.pca_morphology_page` 不存在。

- [ ] **Step 3: 实现 PCA 形态分析子页**

在 `desktop_app/models.py` 新增：

```python
class LayerName(StrEnum):
    # 保留现有值
    PCA_MORPHOLOGY = "PCA_MORPHOLOGY"
```

在新页面构建三栏布局：左栏为状态、自动 K、聚类摘要、真实方向极值和综合极端个体表；右上为只读 `QLabel` 图像区（优先 `pc1_pc2_clusters.png`，无图时说明原因）；右下是模型下拉框和独立 `MeshViewer`。模型列表文字必须带类别前缀：

```text
理论形态｜PC01 +2SD
理论形态｜PC01 -2SD
真实被试｜PC01+｜T049_L
聚类平均耳｜Cluster 01
```

所有文字采用深色，表格不可编辑、行选择；缺少产物时禁用选择器并给出“本次运行未生成 PCA 形态分析（旧运行或 PCA 后处理未完成）”。不在页面中将候选极端个体显示为失败或异常 QC。

- [ ] **Step 4: 将子页嵌入现有结果复核而不破坏旧布局**

在 `ResultWorkbench._build_ui()` 创建 `self.result_tabs = QTabWidget()`；将当前完整的左右 `layout` 移入“结果复核”标签；实例化 `self.pca_morphology_page` 为“PCA 形态分析”标签。保留 `result_scroll_area`、`pca_scores_panel`、`viewer_panel` 及其父子关系，以保持现有结果复核测试和使用习惯。

在 `set_attempt()` 的最后调用：

```python
self.pca_morphology_page.set_attempt(index)
```

为 `#pcaMorphologyPage`、其 `QTableWidget`、状态标签、模型下拉框和图像区添加与现有浅色工程界面一致的深色文字、白底、低饱和边框样式；不得使用与背景接近的白色文字。

- [ ] **Step 5: 运行 UI 测试，确认通过**

Run: `pytest tests/test_desktop_pca_morphology_page.py tests/test_desktop_result_workbench.py tests/test_desktop_ui_flow.py -q`
Expected: PASS；旧运行没有形态目录时仍能打开结果复核。

- [ ] **Step 6: 提交桌面端页面**

```powershell
git add desktop_app/models.py desktop_app/ui/pca_morphology_page.py desktop_app/ui/result_workbench.py desktop_app/ui/main_window.py tests/test_desktop_pca_morphology_page.py tests/test_desktop_result_workbench.py tests/test_desktop_ui_flow.py
git commit -m "feat: display PCA morphology analysis in desktop app"
```

### Task 5: 更新使用文档并进行全量验证

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-03-pca-morphology-analysis-design.md`（仅在实现偏离已确认设计时同步事实）
- Modify: `docs/superpowers/plans/2026-08-03-pca-morphology-analysis.md`（勾选实施步骤）

**Interfaces:**
- Consumes: Task 1–4 生成的已验证输出。
- Produces: 用户可运行、可解释、可复制到离线工作站的 CLI/APP 文档说明。

- [ ] **Step 1: 写入 README 检查断言或人工可核对清单**

在 `README.md` 的 PCA 输出段落添加如下精确说明：原 `scripts\run_full_pipeline.py` 的命令行参数不变；选定 PCA 根目录下新增 `pca_morphology`；明确“理论 PC 极值形态”“真实方向极值被试”“候选极端形态个体”“自动 K 聚类”四类结果的区别；说明 Ward + 标准化 scores + silhouette 选 K，K 范围 2–6；说明低于 4 个纳入样本时跳过聚类但不判 PCA 失败；说明 `+/- PC` 不应跨批次直接赋予固定解剖语义。

- [ ] **Step 2: 运行针对性和全量测试**

Run:

```powershell
pytest tests/test_pca_average.py tests/test_pca_morphology.py tests/test_pipeline.py tests/test_desktop_artifact_indexer.py tests/test_desktop_pca_morphology_page.py tests/test_desktop_result_workbench.py tests/test_desktop_ui_flow.py -q
pytest -q
```

Expected: 两条命令均 PASS；允许既有第三方弃用警告，但不得出现失败、错误或新增 warning-as-error。


- [ ] **Step 3: 运行 CLI 参数兼容与 PCA 不变性冒烟验证**

Run:

```powershell
python scripts/build_average_ear.py --help
pytest tests/test_pca_average.py::test_write_pca_outputs_creates_mean_mesh_and_statistics tests/test_pca_morphology.py -q
```

Expected: 第一条命令仅显示既有四个参数；第二条命令 PASS，并确认 `pca_morphology` 含 7 个 CSV、2 个 PNG、聚类平均耳 PLY（样本量足够时），且原 `scores.csv`、`components.npy`、平均耳点坐标在新增后处理前后逐元素一致。

- [ ] **Step 4: 提交文档与验证记录**

```powershell
git add README.md docs/superpowers/specs/2026-08-03-pca-morphology-analysis-design.md docs/superpowers/plans/2026-08-03-pca-morphology-analysis.md
git commit -m "docs: describe PCA morphology analysis outputs"
```

## Plan self-review

- Spec coverage: Task 1 实现方向极值、自动 K、候选极端个体和聚类平均数据；Task 2 写出全部 CSV/PLY/PNG、确保四个理论形态；Task 3 提供安全索引和旧运行回退；Task 4 提供独立桌面端页面与三维加载；Task 5 更新文档、验证 PCA 不变性和全量回归。
- Placeholder scan: 已检查计划中无 `TODO`、`TBD`、未定义接口或“后续再实现”措辞；所有代码变更步骤给出了函数、字段或算法规则。
- Type consistency: `PcaMorphologyAnalysis` 由 Task 1 定义，Task 2 写出，Task 3 将其输出转为 `ArtifactIndex` 字段，Task 4 只消费这些字段；`LayerName.PCA_MORPHOLOGY` 在 Task 4 定义并只用于页面的 MeshViewer 加载。
