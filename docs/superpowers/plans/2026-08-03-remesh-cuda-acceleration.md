# Remesh CUDA 混合加速实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Remesh 提供可选 CUDA UV 求解、UV 定位/映射加速和可审计的 CPU 最短路缓存；CPU 默认行为与工程门禁不变。

**Architecture:** 新建 `ear_param/remesh_backend.py` 封装 CPU/CUDA 后端、CUDA 探测和 GPU 互斥锁。`ear_param/remesh.py` 通过后端执行 UV 求解、定位、三维映射，并在 `RemeshContext` 缓存 Dijkstra 前驱树。CLI 和桌面软件传递同一参数，运行记录写入实际后端和回退原因。

**Tech Stack:** Python 3.14、NumPy、SciPy、CuPy CUDA 12（可选）、trimesh、PySide6、pytest。

## Global Constraints

- CPU 是默认后端；CuPy/CUDA 不存在时，CLI、桌面软件和 EXE 仍可运行。
- CUDA 结果必须满足三维点最大绝对误差 `<= 1e-8 mm`，region QC、Weld、对齐与 PCA 入组完全一致。
- 不使用 WSL2、cuGraph、Docker 或自定义 CUDA Dijkstra。
- 样本可继续 CPU 并行，但每次只能有一个 region 使用 GPU。
- GPU 依赖不进入 `requirements.txt`。

---

## 文件边界

- Create: `ear_param/remesh_backend.py`、`tests/test_remesh_backend.py`、`requirements-gpu.txt`、`docs/GPU_ACCELERATION_OFFLINE.md`。
- Modify: `ear_param/remesh.py`、`scripts/parameterize_ear_remesh.py`、`ear_param/pipeline.py`、`scripts/run_full_pipeline.py`、`ear_param/run_manifest.py`。
- Modify: `desktop_app/models.py`、`desktop_app/run_controller.py`、`desktop_app/ui/project_wizard.py`。
- Modify: `tests/test_remesh.py`、`tests/test_pipeline.py`、`tests/test_run_manifest.py`、`tests/test_desktop_cli_parity.py`、`tests/test_desktop_run_controller.py`、`README.md`。

### Task 1: 按起点缓存 Dijkstra 前驱树

**Files:**
- Modify: `ear_param/remesh.py:92-99, 840-878, 1131-1148`
- Test: `tests/test_remesh.py`

**Interfaces:**
- `RemeshContext.shortest_path_trees: dict[int, tuple[np.ndarray, np.ndarray]]`。
- `_shortest_path_from_tree(start, end, distances, predecessors) -> list[int]`。

- [ ] **Step 1: 写入失败测试**

```python
def test_remesh_context_reuses_one_dijkstra_tree_for_multiple_paths(monkeypatch, center_patch_mesh, triangle_landmarks):
    calls = []
    original = remesh.dijkstra
    def tracked(graph, *, directed, indices, return_predecessors):
        calls.append(int(indices))
        return original(graph, directed=directed, indices=indices, return_predecessors=return_predecessors)
    monkeypatch.setattr(remesh, "dijkstra", tracked)
    regions = [
        {"region_id": "R1", "region_name": "one", "lm_a": "A", "lm_b": "B", "lm_c": "C", "resolution": 2},
        {"region_id": "R2", "region_name": "two", "lm_a": "A", "lm_b": "C", "lm_c": "B", "resolution": 2},
    ]
    context = remesh.prepare_remesh_context(center_patch_mesh, triangle_landmarks, regions)
    [remesh.build_region_remesh(center_patch_mesh, triangle_landmarks, item, context) for item in regions]
    assert calls.count(context.snapped_landmarks["A"].vertex_id) == 1
```

- [ ] **Step 2: 确认红灯**

Run: `python -m pytest --basetemp .test_artifacts\pytest-dijkstra-red -p no:cacheprovider tests/test_remesh.py::test_remesh_context_reuses_one_dijkstra_tree_for_multiple_paths -q`

Expected: FAIL，A 顶点对应的 Dijkstra 调用次数大于 1。

- [ ] **Step 3: 最小实现**

在 `RemeshContext` 添加 `shortest_path_trees`；第一次请求起点时调用原有 `dijkstra(adjacency, directed=False, indices=start, return_predecessors=True)`，缓存结果；从前驱数组恢复终点路径。反向边继续对同一无向路径做 `reversed`，不改权重、起点选择或 face 逻辑。

- [ ] **Step 4: 验证并提交**

Run: `python -m pytest --basetemp .test_artifacts\pytest-dijkstra-green -p no:cacheprovider tests/test_remesh.py -q`

Expected: PASS。

    git add ear_param/remesh.py tests/test_remesh.py
    git commit -m "perf: cache Dijkstra predecessor trees per sample"

### Task 2: 引入可插拔 CPU 后端

**Files:**
- Create: `ear_param/remesh_backend.py`, `tests/test_remesh_backend.py`
- Modify: `ear_param/remesh.py:646-678, 906-933, 972-1122, 1286-1317`

**Interfaces:**

```python
class RemeshBackend(Protocol):
    name: str
    requested: str
    fallback_reason: str
    def solve_harmonic(self, matrix: csr_matrix, rhs: np.ndarray) -> np.ndarray:
        raise NotImplementedError
    def locate(self, uv: np.ndarray, faces: np.ndarray, sample_uv: np.ndarray, tol: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        raise NotImplementedError
    def map_to_3d(self, vertices: np.ndarray, faces: np.ndarray, face_ids: np.ndarray, barycentric: np.ndarray) -> np.ndarray:
        raise NotImplementedError

def resolve_remesh_backend(requested: Literal["cpu", "cuda", "auto"]) -> RemeshBackend:
    raise NotImplementedError
```

- [ ] **Step 1: 写入 CPU 等价与 auto 回退失败测试**

```python
def test_auto_backend_falls_back_to_cpu_when_cuda_probe_reports_unavailable(monkeypatch):
    monkeypatch.setattr("ear_param.remesh_backend._probe_cuda", lambda: (False, "CuPy unavailable"))
    backend = resolve_remesh_backend("auto")
    assert (backend.name, backend.requested, backend.fallback_reason) == ("cpu", "auto", "CuPy unavailable")

def test_cpu_backend_matches_reference_uv_locator():
    source, target = make_subdivision_template(6), make_subdivision_template(24)
    ids, bary, unmapped = resolve_remesh_backend("cpu").locate(source.uv, source.faces, target.uv, 1e-9)
    expected = locate_uv_samples_in_faces(source.uv, source.faces, target.uv)
    np.testing.assert_array_equal(ids, expected.face_indices)
    np.testing.assert_allclose(bary, expected.barycentric, atol=0.0, rtol=0.0)
    np.testing.assert_array_equal(unmapped, expected.unmapped_mask)
```

- [ ] **Step 2: 确认红灯**

Run: `python -m pytest --basetemp .test_artifacts\pytest-backend-red -p no:cacheprovider tests/test_remesh_backend.py -q`

Expected: FAIL，`ear_param.remesh_backend` 尚不存在。

- [ ] **Step 3: 实现 CPU 后端并接入 Remesh**

`CpuRemeshBackend` 原样调用当前 SciPy `spsolve`、`locate_uv_samples_in_faces`、`map_samples_to_3d` 的核心逻辑。将 `build_region_remesh(mesh, landmarks, region, context, backend=None)`、`harmonic_parameterize_patch(mesh, patch, boundary_paths, backend)` 和 `_solve_harmonic_uv(local_faces, uv, boundary_uv, internal_ids, backend)` 串联；`None` 一律解析为 CPU 后端。

- [ ] **Step 4: 验证并提交**

Run: `python -m pytest --basetemp .test_artifacts\pytest-backend-green -p no:cacheprovider tests/test_remesh.py tests/test_remesh_backend.py -q`

Expected: PASS。

    git add ear_param/remesh_backend.py ear_param/remesh.py tests/test_remesh.py tests/test_remesh_backend.py
    git commit -m "feat: add pluggable CPU remesh backend"

### Task 3: 实现 CUDA UV 算子和数值门禁

**Files:**
- Modify: `ear_param/remesh_backend.py`
- Test: `tests/test_remesh_backend.py`

**Interfaces:**
- `CudaRemeshBackend` 在模块级 `threading.Lock` 内执行 GPU 工作；每次 region 完成后释放 CuPy memory pool。
- `cuda_available() -> tuple[bool, str]`；`backend_diagnostics(requested: str) -> dict[str, object]`。

- [ ] **Step 1: 写入 CUDA/CPU 一致性失败测试**

```python
@pytest.mark.skipif(not cuda_available()[0], reason="CUDA backend unavailable")
def test_cuda_backend_matches_cpu_within_tolerance(center_patch_mesh):
    source, target = make_subdivision_template(10), make_subdivision_template(24)
    cpu, cuda = resolve_remesh_backend("cpu"), resolve_remesh_backend("cuda")
    cpu_ids, cpu_bary, cpu_unmapped = cpu.locate(source.uv, source.faces, target.uv, 1e-9)
    gpu_ids, gpu_bary, gpu_unmapped = cuda.locate(source.uv, source.faces, target.uv, 1e-9)
    np.testing.assert_array_equal(gpu_ids, cpu_ids)
    np.testing.assert_array_equal(gpu_unmapped, cpu_unmapped)
    np.testing.assert_allclose(gpu_bary, cpu_bary, atol=1e-12, rtol=0.0)
    np.testing.assert_allclose(
        cuda.map_to_3d(center_patch_mesh.vertices, source.faces, gpu_ids, gpu_bary),
        cpu.map_to_3d(center_patch_mesh.vertices, source.faces, cpu_ids, cpu_bary),
        atol=1e-8, rtol=0.0,
    )
```

- [ ] **Step 2: 确认红灯或无 GPU 跳过**

Run: `python -m pytest --basetemp .test_artifacts\pytest-cuda-red -p no:cacheprovider tests/test_remesh_backend.py -q`

Expected: RTX 3050 环境在 CUDA 实现前 FAIL；无 GPU 环境 CUDA 用例 SKIPPED。

- [ ] **Step 3: 实现 CUDA 后端**

以 `float64` 将 CSR 和 RHS 上传 GPU，使用 `cupyx.scipy.sparse.linalg.spsolve` 分别求 U、V 后合并返回。UV 定位按 64 个样本、4096 个面分块计算重心坐标，按升序 face ID 选择第一个合法面；三维映射对有效 face ID 批量重心插值。CUDA 异常、非有限值或内部结构校验失败时，`auto` 回退 CPU，`cuda` 抛出带诊断的 `RuntimeError`。

- [ ] **Step 4: 验证并提交**

Run: `python -m pytest --basetemp .test_artifacts\pytest-cuda-green -p no:cacheprovider tests/test_remesh.py tests/test_remesh_backend.py -q`

Expected: CPU 环境 PASS/SKIPPED；RTX 3050 环境 CUDA 对照误差 `<=1e-8`。

    git add ear_param/remesh_backend.py tests/test_remesh_backend.py
    git commit -m "feat: accelerate remesh UV operations with CUDA"

### Task 4: 传递 CLI、manifest 与桌面参数

**Files:**
- Modify: `scripts/parameterize_ear_remesh.py`, `ear_param/pipeline.py`, `scripts/run_full_pipeline.py`, `ear_param/run_manifest.py`
- Modify: `desktop_app/models.py`, `desktop_app/run_controller.py`, `desktop_app/ui/project_wizard.py`
- Test: `tests/test_pipeline.py`, `tests/test_run_manifest.py`, `tests/test_desktop_cli_parity.py`, `tests/test_desktop_run_controller.py`

**Interfaces:** `--remesh-backend {cpu,cuda,auto}` 默认 `cpu`；`PipelineConfig.remesh_backend` 和 `RunOptions.remesh_backend` 同名同值；每个 Remesh 结果含 `backend_diagnostics`，`PipelineResult` 汇总为 `remesh_backend_summary`；manifest 记录 requested、effective、fallback_reason 和 GPU 内存峰值。

- [ ] **Step 1: 写入参数传递失败测试**

```python
def test_desktop_command_passes_selected_remesh_backend(tmp_path):
    controller = RunController(process_factory=FakeProcess)
    controller.start(project_with_copied_inputs(tmp_path), RunOptions(remesh_backend="auto"))
    config, _, _ = build_pipeline_config(build_parser().parse_args(controller.last_command[2:]))
    assert config.remesh_backend == "auto"
    assert controller.last_command[controller.last_command.index("--remesh-backend") + 1] == "auto"

def test_manifest_records_requested_and_effective_remesh_backend(tmp_path):
    mesh_dir, landmarks_dir, region_path = tmp_path / "mesh", tmp_path / "landmarks", tmp_path / "regions.csv"
    mesh_dir.mkdir()
    landmarks_dir.mkdir()
    region_path.write_text("region_id,resolution\nR1,24\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    manifest = create_run_manifest(
        config=PipelineConfig(mesh_dir=mesh_dir, landmarks_dir=landmarks_dir, regions=region_path, remesh_backend="auto"),
        run_dir=run_dir, output_root=None, project_root=tmp_path, argv=[],
    )
    manifest_path = run_dir / "manifest.json"
    write_manifest(manifest_path, manifest)
    result = PipelineResult(
        records=pd.DataFrame(), pca_status="SKIPPED", pca_result={},
        remesh_backend_summary={"effective": "cpu", "fallback_reason": "CuPy unavailable", "gpu_peak_bytes": 0},
    )
    saved = finish_manifest(manifest_path, status="COMPLETED", result=result)
    assert saved["parameters"]["remesh_backend_requested"] == "auto"
    assert saved["parameters"]["remesh_backend_effective"] == "cpu"
    assert saved["parameters"]["remesh_backend_fallback_reason"] == "CuPy unavailable"
```

- [ ] **Step 2: 确认红灯并实现**

Run: `python -m pytest --basetemp .test_artifacts\pytest-backend-cli-red -p no:cacheprovider tests/test_desktop_cli_parity.py::test_desktop_command_passes_selected_remesh_backend -q`

Expected: FAIL，`RunOptions` 无该参数。

在参数页增加：`CPU（稳定，默认）=cpu`、`CUDA（实验性）=cuda`、`自动检测（GPU 工作站）=auto`。`RunController` 总是传递该 CLI 参数；参数化脚本把实际后端诊断写入事件；`PipelineResult.remesh_backend_summary` 由所有样本的诊断合并得到，`finish_manifest` 将其写入 `parameters.remesh_backend_effective`、`parameters.remesh_backend_fallback_reason` 和 `runtime.remesh_backend`。

- [ ] **Step 3: 验证并提交**

Run: `python -m pytest --basetemp .test_artifacts\pytest-backend-cli-green -p no:cacheprovider tests/test_pipeline.py tests/test_run_manifest.py tests/test_desktop_cli_parity.py tests/test_desktop_run_controller.py -q`

Expected: PASS。

    git add scripts/parameterize_ear_remesh.py ear_param/pipeline.py scripts/run_full_pipeline.py ear_param/run_manifest.py desktop_app/models.py desktop_app/run_controller.py desktop_app/ui/project_wizard.py tests/test_pipeline.py tests/test_run_manifest.py tests/test_desktop_cli_parity.py tests/test_desktop_run_controller.py
    git commit -m "feat: expose remesh backend in CLI and desktop app"

### Task 5: 离线部署与全流程对照

**Files:**
- Create: `requirements-gpu.txt`, `docs/GPU_ACCELERATION_OFFLINE.md`
- Modify: `README.md`
- Test: `tests/test_remesh_backend.py`

- [ ] **Step 1: 写入 CUDA 诊断测试**

```python
def test_auto_diagnostics_reports_cpu_fallback(monkeypatch):
    monkeypatch.setattr("ear_param.remesh_backend._probe_cuda", lambda: (False, "CuPy unavailable"))
    report = backend_diagnostics("auto")
    assert report["requested"] == "auto"
    assert report["effective"] == "cpu"
    assert report["fallback_reason"] == "CuPy unavailable"
```

- [ ] **Step 2: 写入离线安装和自检命令**

```powershell
python -m pip download -r requirements-gpu.txt -d offline_wheels\gpu
.\.venv\Scripts\python.exe -m pip install --no-index --find-links offline_wheels\gpu -r requirements-gpu.txt
.\.venv\Scripts\python.exe -c "from ear_param.remesh_backend import backend_diagnostics; print(backend_diagnostics('auto'))"
```

`requirements-gpu.txt` 仅锁定经过 RTX 3050 / CUDA 12 实测的 `cupy-cuda12x` 与必要 CUDA components。文档还须包含 GPU 与 CPU 各跑一次固定验证集、比较最大坐标差和 QC/Weld/PCA manifest 的命令。

- [ ] **Step 3: 完整验证并提交**

Run: `python -m pytest --basetemp .test_artifacts\pytest-remesh-gpu-final -p no:cacheprovider tests -q`

Expected: CPU 环境全通过，CUDA 用例跳过；RTX 3050 环境全通过且输出 CPU/CUDA 对照指标。

    git add requirements-gpu.txt docs/GPU_ACCELERATION_OFFLINE.md README.md tests/test_remesh_backend.py
    git commit -m "docs: describe offline CUDA remesh acceleration"
