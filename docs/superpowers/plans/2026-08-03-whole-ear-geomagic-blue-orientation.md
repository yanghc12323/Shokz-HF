# 整耳 PLY 的 Geomagic 蓝色外侧朝向实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使 whole-ear PLY 在 Geomagic 中将耳廓外侧显示为蓝色，同时保持网格坐标、Weld/QC 和 PCA 数值不变。

**Architecture:** `assemble_whole_ear` 保留 `_normalize_face_winding` 的局部一致化，再调用纯函数统一交换每个三角面的 `global_v1`、`global_v2`。CSV、PLY 与 QC 图继续共享同一份 `WholeEarResult.faces`。

**Tech Stack:** Python 3、NumPy、pandas、trimesh、pytest。

## Global Constraints

- 不改变顶点坐标、区域点、面集合、区域表、重网格或拼接阈值。
- 不新增 CLI 参数、桌面软件界面或第三方依赖。
- 只影响 whole-ear 输出；不影响 raw、repaired、salvaged 区域输出。
- 以当前 Geomagic 的颜色约定为准：耳廓外侧为蓝色。

---

## 文件边界

- `ear_param/whole_ear.py`：在局部面绕序一致化之后施加固定全局反转，并在 Weld 汇总表记录策略。
- `tests/test_whole_ear.py`：验证反转不改变顶点或无序面集合，并验证 CLI 导出的 PLY、CSV 面表完全一致。

### Task 1: 写出固定朝向的失败测试

**Files:**
- Modify: `tests/test_whole_ear.py:78-101, 565-605`

**Interfaces:**
- Consumes: `ear_param.whole_ear._normalize_face_winding(faces) -> tuple[pd.DataFrame, FaceWindingDiagnostics]`。
- Produces: `ear_param.whole_ear._orient_whole_ear_for_geomagic(faces) -> pd.DataFrame`，它返回独立表，面由 `[v0, v1, v2]` 变为 `[v0, v2, v1]`。

- [ ] **Step 1: 添加全局面反转单元测试**

```python
def test_geomagic_blue_orientation_reverses_every_face_without_changing_geometry():
    from ear_param.whole_ear import _orient_whole_ear_for_geomagic
    faces = pd.DataFrame([
        {"global_face_id": 0, "global_v0": 0, "global_v1": 1, "global_v2": 2},
        {"global_face_id": 1, "global_v0": 2, "global_v1": 1, "global_v2": 3},
    ])
    oriented = _orient_whole_ear_for_geomagic(faces)
    assert oriented[["global_v0", "global_v1", "global_v2"]].to_numpy().tolist() == [[0, 2, 1], [2, 3, 1]]
    assert np.array_equal(
        np.sort(oriented[["global_v0", "global_v1", "global_v2"]].to_numpy(), axis=1),
        np.sort(faces[["global_v0", "global_v1", "global_v2"]].to_numpy(), axis=1),
    )
    pd.testing.assert_frame_equal(faces, pd.DataFrame([
        {"global_face_id": 0, "global_v0": 0, "global_v1": 1, "global_v2": 2},
        {"global_face_id": 1, "global_v0": 2, "global_v1": 1, "global_v2": 3},
    ]))
```

- [ ] **Step 2: 运行测试，确认函数尚不存在**

Run: `python -m pytest --basetemp .test_artifacts\pytest-geomagic-orientation-red -p no:cacheprovider tests/test_whole_ear.py::test_geomagic_blue_orientation_reverses_every_face_without_changing_geometry -q`

Expected: FAIL，提示无法导入 `_orient_whole_ear_for_geomagic`。

- [ ] **Step 3: 扩展既有 CLI 导出测试**

在 `test_build_whole_ear_cli_exports_csv_ply_and_qc_figure` 的文件存在性断言后加入：

```python
exported_faces = pd.read_csv(output_dir / "S1_L_whole_ear_faces.csv")
exported_mesh = trimesh.load(output_dir / "S1_L_whole_ear_welded.ply", force="mesh", process=False)
np.testing.assert_array_equal(exported_mesh.faces, exported_faces[["global_v0", "global_v1", "global_v2"]].to_numpy(dtype=int))
exported_summary = pd.read_csv(output_dir / "S1_L_weld_qc_summary.csv")
assert exported_summary.loc[0, "geomagic_exterior_color"] == "blue"
assert exported_summary.loc[0, "geomagic_global_orientation_flipped_face_count"] == len(exported_faces)
```

- [ ] **Step 4: 提交测试基线**

```bash
git add tests/test_whole_ear.py
git commit -m "test: cover Geomagic whole-ear orientation"
```

### Task 2: 实现固定的全局反转及审计字段

**Files:**
- Modify: `ear_param/whole_ear.py:355-406, 941-1011`
- Test: `tests/test_whole_ear.py`

**Interfaces:**
- Consumes: `_normalize_face_winding` 的输出。
- Produces: `_orient_whole_ear_for_geomagic(faces: pd.DataFrame) -> pd.DataFrame`；输出有布尔列 `geomagic_global_orientation_flipped`，所有值均为 `True`。

- [ ] **Step 1: 在局部一致化后实现全局反转**

```python
def _orient_whole_ear_for_geomagic(faces: pd.DataFrame) -> pd.DataFrame:
    """Reverse every whole-ear triangle so Geomagic renders the exterior blue."""
    oriented = faces.copy()
    if oriented.empty:
        oriented["geomagic_global_orientation_flipped"] = pd.Series(dtype=bool)
        return oriented
    values = oriented[["global_v1", "global_v2"]].to_numpy(dtype=int)
    oriented.loc[:, ["global_v1", "global_v2"]] = values[:, ::-1]
    oriented["geomagic_global_orientation_flipped"] = True
    return oriented
```

将 `assemble_whole_ear` 中的：

```python
whole_faces, winding = _normalize_face_winding(whole_faces)
```

改为：

```python
whole_faces, winding = _normalize_face_winding(whole_faces)
whole_faces = _orient_whole_ear_for_geomagic(whole_faces)
```

并在 `summary` 的 winding 字段后添加：

```python
"geomagic_exterior_color": "blue",
"geomagic_global_orientation_flipped_face_count": len(whole_faces),
```

- [ ] **Step 2: 运行针对性测试，确认通过**

Run: `python -m pytest --basetemp .test_artifacts\pytest-geomagic-orientation-green -p no:cacheprovider tests/test_whole_ear.py::test_geomagic_blue_orientation_reverses_every_face_without_changing_geometry tests/test_whole_ear.py::test_build_whole_ear_cli_exports_csv_ply_and_qc_figure -q`

Expected: `2 passed`。

- [ ] **Step 3: 运行 whole-ear 回归测试并提交**

Run: `python -m pytest --basetemp .test_artifacts\pytest-whole-ear-geomagic -p no:cacheprovider tests/test_whole_ear.py -q`

Expected: 全部通过。

```bash
git add ear_param/whole_ear.py tests/test_whole_ear.py
git commit -m "fix: orient whole-ear exterior blue in Geomagic"
```

### Task 3: 验证下游不受坐标变化影响

**Files:**
- Test: `tests/test_alignment.py`, `tests/test_pca_average.py`

**Interfaces:**
- Consumes: 全局反转后的 whole-ear 面表；顶点 ID 与顶点坐标保持原状。
- Produces: 对齐和 PCA 既有回归测试通过。

- [ ] **Step 1: 运行下游测试**

Run: `python -m pytest --basetemp .test_artifacts\pytest-geomagic-downstream -p no:cacheprovider tests/test_alignment.py tests/test_pca_average.py -q`

Expected: 全部通过。

- [ ] **Step 2: 检查改动与交付重跑说明**

Run: `git diff --check -- ear_param/whole_ear.py tests/test_whole_ear.py`

Expected: 无空白错误。历史 PLY 的最小重跑范围为 whole-ear 阶段；为统一后续产物面表版本，应从整耳拼接继续跑对齐、平均耳和 PCA。
