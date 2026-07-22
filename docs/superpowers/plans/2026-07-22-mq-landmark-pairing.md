# MQ Landmark Pairing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `MQ_S###L/R.ply` 与 `T###_L/R_landmarks.csv` 在 CLI 和桌面项目中稳定配对，同时保留旧同名输入兼容性。

**Architecture:** 在 `ear_param.pipeline` 建立唯一的样本解析与文件路径来源；批处理、manifest、canonicalization 与 QC 脚本调用该接口，而不再自行拼接原始输入路径。输出样本标签始终采用模型文件主体。

**Tech Stack:** Python 3、pandas、pytest、PySide6。

## Global Constraints

- 不重命名、写入或复制原始模型和 landmark 数据。
- 不改变 Remesh、修复、整耳、刚性配准或 PCA 算法。
- MQ 映射仅接受 `MQ_S###L/R` → `T###_L/R_landmarks.csv`。
- 保持旧 `T001_L.ply` + `T001_L_landmarks.csv` 支持。

---

### Task 1: 集中样本输入解析

**Files:**
- Modify: `ear_param/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces `SampleInput(sample_tag, sample_id, side, mesh_path, landmarks_path)`。
- Produces `discover_sample_inputs(mesh_dir, landmarks_dir)`，并由 `discover_samples` 保持原 DataFrame 契约。

- [ ] **Step 1: 写失败测试**

```python
def test_discover_samples_pairs_mq_mesh_with_t_landmarks(tmp_path):
    mesh_dir, landmarks_dir = tmp_path / "mesh", tmp_path / "landmarks"
    mesh_dir.mkdir(); landmarks_dir.mkdir()
    (mesh_dir / "MQ_S001L.ply").write_text("ply\n")
    (landmarks_dir / "T001_L_landmarks.csv").write_text("landmark_id,x,y,z\n")
    result = discover_samples(mesh_dir, landmarks_dir)
    assert result.to_dict("records") == [{"sample_tag": "MQ_S001L", "discovery": "READY", "reason": ""}]
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest -q tests/test_pipeline.py -k mq_mesh`

Expected: `READY` 断言失败，因为当前严格同名配对返回两个不完整样本。

- [ ] **Step 3: 实现最小解析器**

```python
def _mq_landmark_name(mesh_tag: str) -> str | None:
    match = re.fullmatch(r"MQ_S(\d{3})([LR])", mesh_tag)
    return f"T{match.group(1)}_{match.group(2)}_landmarks.csv" if match else None
```

解析器优先返回真实存在的 MQ 对，旧命名仍按同名规则处理；`discover_samples`
仅将解析结果投影为既有三列。

- [ ] **Step 4: 运行通过测试**

Run: `pytest -q tests/test_pipeline.py -k mq_mesh`

Expected: `1 passed`。

### Task 2: 用真实路径替换输入路径拼接，并兼容 MQ 侧别

**Files:**
- Modify: `ear_param/pipeline.py`
- Modify: `ear_param/canonicalization.py`
- Modify: `ear_param/run_manifest.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_canonicalization.py`
- Test: `tests/test_run_manifest.py`

**Interfaces:**
- Consumes `SampleInput`。
- `sample_identity(sample_tag)` 返回 `("MQ_S001", "L")` 或旧标签的等价结果。

- [ ] **Step 1: 写失败测试**

```python
def test_canonicalize_sample_accepts_mq_right_side(...):
    result = canonicalize_sample("MQ_S001R", mesh_path, landmark_path, out_dir)
    assert result.source_side == "R"
    assert result.mirrored is True
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest -q tests/test_canonicalization.py -k mq_right`

Expected: 失败，错误提示当前要求 `_L` 或 `_R`。

- [ ] **Step 3: 实现最小替换**

将 pipeline canonicalization 与 manifest 改为使用解析器输出的实际路径；将
MQ/legacy 样本标识解析集中为单一函数。canonical 输出仍以模型 `sample_tag`
命名。

- [ ] **Step 4: 运行通过测试**

Run: `pytest -q tests/test_canonicalization.py tests/test_run_manifest.py tests/test_pipeline.py -k 'mq or canonicalization or manifest'`

Expected: 全部通过。

### Task 3: 直连 QC、桌面校验与文案

**Files:**
- Modify: `scripts/visualize_remesh_qc.py`
- Modify: `desktop_app/validation_service.py`
- Modify: `desktop_app/ui/project_wizard.py`
- Modify: `scripts/run_full_pipeline.py`
- Test: `tests/test_visualize_remesh_qc.py`
- Test: `tests/test_desktop_validation_service.py`

**Interfaces:**
- QC 直接运行时根据 MQ 标签定位实际 landmark。
- 桌面校验通过 `discover_samples` 得到新版 READY 状态，不复制或改名输入。

- [ ] **Step 1: 写失败测试**

```python
def test_discover_qc_tags_supports_mq_names(...):
    assert _split_sample_tag("MQ_S001L") == ("MQ_S001", "L")
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest -q tests/test_visualize_remesh_qc.py -k mq`

Expected: 因现有下划线解析规则而失败。

- [ ] **Step 3: 实现并更新示例**

复用 pipeline 的解析函数；更新 CLI 和桌面固定参考耳示例为 `MQ_S001L`。

- [ ] **Step 4: 回归验证**

Run: `pytest -q tests/test_pipeline.py tests/test_canonicalization.py tests/test_run_manifest.py tests/test_visualize_remesh_qc.py tests/test_desktop_project_service.py tests/test_desktop_validation_service.py tests/test_desktop_cli_parity.py`

Expected: 全部通过。

### Task 4: 全量验证与数据契约检查

**Files:**
- Test only: existing test suite

- [ ] **Step 1: 运行完整测试集**

Run: `pytest -q`

Expected: 全部通过。

- [ ] **Step 2: 对新版数据执行只读配对检查**

Run: 使用 `discover_samples(data/clean_mesh, data/landmarks)` 检查 130 条均为 `READY`。

Expected: `READY=130`，无缺失配对。
