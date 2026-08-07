# Remesh CUDA 离线部署与验收说明

## 1. 功能边界

本项目的 GPU 加速是 **可选的 Remesh 混合加速**，不是把整条分析管线迁移到 GPU。

- GPU：harmonic UV 稀疏求解、UV 模板点定位、重心三维回映射；使用 `float64`。
- CPU：网格读取、landmark 吸附、Dijkstra 最短路径、patch 提取、退化修复、QC、Weld、刚体配准、PCA、文件读写。
- 既有 Dijkstra 已按“每样本、每起点”缓存前驱树，避免重复最短路计算；不引入 WSL2、cuGraph 或自定义 CUDA 图算法。
- 默认后端始终是 `cpu`，没有安装 CuPy 或没有 NVIDIA GPU 时，CLI 和桌面软件可照常使用。

CUDA 结果的发布门禁为：同一输入与参数下，三维点最大绝对误差不超过 `1e-8 mm`，并且 region QC、Weld 状态、刚体配准状态和 PCA 入组结果完全一致。GPU 只减少计算耗时，绝不放宽任何工程判定阈值。

## 2. 运行模式

全流程新增参数：

```text
--remesh-backend {cpu,cuda,auto}
```

| 取值 | 行为 | 使用建议 |
| --- | --- | --- |
| `cpu` | 当前 SciPy/NumPy 基准路径；无 GPU 依赖 | 默认值；正式基准与问题复现 |
| `auto` | 检测 CUDA；不可用或 GPU 算子异常时，记录原因并对受影响 region 从原始输入以 CPU 完整重算 | RTX 3050 工作站的日常尝试方式 |
| `cuda` | 要求 CUDA 可用；无法初始化时直接报错 | 仅在完成本页第 5 节验收后使用 |

样本仍可通过 `--parallel-workers` 并行准备；所有 Python 子进程会通过共享锁让 **同一时刻最多一个 region 占用 GPU**，避免 6 GB 显存被多样本并发挤占。Weld、刚体配准和 PCA 仍串行。

每个样本会在以下位置保存后端诊断：

```text
<output-root>/parameterized_points_r24/salvaged/<sample>_remesh_backend.json
```

本次运行的 `manifest.json` 同时记录：

- `parameters.remesh_backend_requested`
- `parameters.remesh_backend_effective`
- `parameters.remesh_backend_fallback_reason`
- `runtime.remesh_backend.gpu_peak_bytes`

其中 `cuda_with_cpu_fallback` 表示部分 region 的 CUDA 算子失败，已完整以 CPU 重算；不会把 GPU 半成品混入该样本结果。

## 3. 前置条件

目标是 Windows 10/11 + NVIDIA RTX 3050（6 GB）或同类 NVIDIA CUDA GPU。先在工作站 PowerShell 中确认驱动可见：

```powershell
nvidia-smi
```

显示 GPU、驱动和 CUDA 12.x 兼容信息后再继续。该方案使用 CuPy 的 Windows CUDA 12 wheel；CuPy 14.1.1 支持 Python 3.10–3.14 与 CUDA 12.x。`[ctk]` extra 会把 CUDA 运行时组件作为 wheel 依赖下载，因此工作站只需有兼容的 NVIDIA 驱动，不强制安装完整系统 CUDA Toolkit。

基础项目环境应先按 `requirements.txt` 安装完成。GPU 包是额外安装项，不能替代基础依赖，也不能把 `cupy` 与 `cupy-cuda12x` 同时装入同一个环境。

## 4. 在可联网 Windows 机器准备离线 wheel

在与工作站 **相同 Python 大版本、相同 Windows x64 架构** 的联网机器上，于项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip download --only-binary=:all: `
  -r requirements-gpu.txt `
  -d offline_wheels\gpu
```

将整个 `offline_wheels\gpu` 文件夹复制到离线工作站项目根目录。不要只复制主 `cupy-cuda12x` wheel；必须保留 pip 同时下载的 NVIDIA CUDA component wheels。

## 5. 在离线工作站安装与自检

先进入项目目录，并在已可运行 CPU 管线的虚拟环境中执行：

```powershell
.\.venv\Scripts\python.exe -m pip install --no-index `
  --find-links offline_wheels\gpu `
  -r requirements-gpu.txt

.\.venv\Scripts\python.exe -c "from ear_param.remesh_backend import backend_diagnostics; print(backend_diagnostics('auto'))"
.\.venv\Scripts\python.exe -c "import cupy; print(cupy.cuda.runtime.getDeviceCount()); cupy.show_config()"
```

第一条诊断的期望结果中应包含 `requested: auto` 和 `effective: cuda`。如果是 `effective: cpu`，请保留输出中的 `fallback_reason`，优先检查：驱动是否可被 `nvidia-smi` 识别、wheel 是否完整、是否混装了多个 CuPy 包，以及是否使用了正确的 `.venv`。

### Windows pip CUDA wheel 的额外自检

若 `import cupy` 能识别 GPU，但过去出现过 `import cupyx.cusolver` 的 DLL 加载错误，请先将项目中的最新 `ear_param/remesh_backend.py` 同步到工作站。该文件会在选择 CUDA 后端时，借助 CuPy 依赖的 `cuda-pathfinder` 预加载 pip wheel 中分散存放的 `nvrtc` 与 `cusolver` DLL；无需手工设置 `CUDA_PATH`，也无需安装完整 CUDA Toolkit。

同步后执行下面的最小稀疏求解自检：

```powershell
.\.venv\Scripts\python.exe -c "import numpy as np; from scipy.sparse import csr_matrix; from ear_param.remesh_backend import resolve_remesh_backend; b=resolve_remesh_backend('auto'); print(b.name, b.solve_harmonic(csr_matrix([[2.,0.],[0.,4.]]), np.array([2.,8.])))"
```

期望输出以 `cuda` 开头，并包含 `[1. 2.]`。`cupy._environment` 给出的 `CUDA_PATH could not be detected` 警告在 wheel 方案中可忽略；只要这条稀疏求解命令成功即可。若失败，请保存完整输出，且暂时以 `--remesh-backend cpu` 运行。

### 使用 nvitop 实时监控（可选）

`nvitop` 只读取 NVIDIA 驱动提供的监控数据，不会改变分析结果。请在运行管线的 PowerShell 之外另开一个窗口使用它。

在可联网的 Windows 机器下载完整离线 wheel 集：

```powershell
.\.venv\Scripts\python.exe -m pip download --only-binary=:all: nvitop -d offline_wheels\nvitop
```

将 `offline_wheels\nvitop` 整个文件夹复制到工作站项目根目录，在工作站安装并启动：

```powershell
.\.venv\Scripts\python.exe -m pip install --no-index --find-links offline_wheels\nvitop nvitop
.\.venv\Scripts\python.exe -m nvitop
```

界面中重点查看 RTX 3050 的 GPU 利用率、专用显存、功耗、温度，以及当前 Python 分析进程；按 `q` 退出。由于 Remesh 的 GPU 运算按 region 串行提交，利用率可能呈短时波峰，而不必持续 100%。

### GPU 分段耗时记录

每个完成 Remesh 的样本都会在以下文件中保存 GPU 性能记录：

```text
<output-root>/parameterized_points_r24/salvaged/<sample>_remesh_backend.json
```

其中 `gpu_timing` 包含 `region_count`、`lock_wait_seconds`、`host_to_device_seconds`、`harmonic_solve_seconds`、`uv_lookup_seconds`、`map_to_3d_seconds`、`device_to_host_seconds` 与 `region_wall_seconds`。同一轮次汇总值也会写入 `manifest.json` 的 `runtime.remesh_backend.gpu_timing`。这些字段仅用于性能诊断，不进入几何、QC、Weld、配准或 PCA 计算。

然后运行 CUDA 专项单元测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_remesh_backend.py -q
```

有 GPU 时，`test_cuda_backend_matches_cpu_within_tolerance` 不应跳过；它要求 UV face ID、unmapped mask 完全一致，且重心坐标误差不大于 `1e-12`。

## 6. CPU/CUDA 发布前对照

首次部署或更新 CuPy/驱动后，必须对同一小批代表性样本分别跑一次 CPU 与 CUDA。建议包含：普通区域、边界复杂区域、退化 UV 修复区域和 r48 覆盖修复区域。

```powershell
# CPU 基准
.\.venv\Scripts\python.exe scripts\run_full_pipeline.py `
  --mesh_dir data\clean_mesh `
  --landmarks_dir data\landmarks `
  --regions config\region_table.csv `
  --samples MQ_S001L MQ_S001R `
  --parallel-workers 4 `
  --alignment-mode fixed-reference `
  --reference-sample <已通过Weld的参考耳> `
  --qc-figure-mode repaired-fail `
  --remesh-backend cpu `
  --output-root output\runs\gpu_validation_cpu

# CUDA 对照；先用 auto，确认 manifest 中实际后端为 cuda 后才可作为 GPU 对照
.\.venv\Scripts\python.exe scripts\run_full_pipeline.py `
  --mesh_dir data\clean_mesh `
  --landmarks_dir data\landmarks `
  --regions config\region_table.csv `
  --samples MQ_S001L MQ_S001R `
  --parallel-workers 4 `
  --alignment-mode fixed-reference `
  --reference-sample <已通过Weld的参考耳> `
  --qc-figure-mode repaired-fail `
  --remesh-backend auto `
  --output-root output\runs\gpu_validation_cuda
```

人工验收时必须逐项比较：

1. 两轮 `parameterized_points_r24/salvaged/*_remesh_points.csv`：以相同 `point_id` 对齐后，`x/y/z` 的最大绝对差不超过 `1e-8 mm`，NaN 位置完全一致。
2. 两轮 `*_remesh_qc.csv`：每个 `sample_tag + region_id` 的 `raw_status`、`status`、未映射计数、退化计数和修复结论完全一致。
3. 两轮 `whole_ear_r24/weld_repaired/weld_qc_summary.csv`：每个样本的 Weld 状态一致。
4. 两轮 `pipeline_batch_summary.csv` 和 PCA 输入 manifest：对齐状态、`pca_included`/`reference_pca_included` 与拦截原因一致。

若任一项不一致，停止使用 `cuda`/`auto` 作为生产加速路径，改回 `--remesh-backend cpu`，并保留两轮 `manifest.json`、后端 JSON 和日志以便定位。

## 7. 日常运行与桌面软件

完成第 6 节验收后，CLI 仅需在原命令末尾加一项：

```powershell
--remesh-backend auto
```

桌面软件的“运行参数”页也提供“Remesh 计算后端”：默认“CPU（稳定）”；GPU 工作站建议选择“自动检测 GPU”。运行结束后，在结果目录的 `manifest.json` 和每样本 `*_remesh_backend.json` 查看实际使用情况。

GPU 不会加速 PNG 写入、退化区域的 CPU 修复、Weld、配准、PCA 或磁盘 I/O。因此，若当前主要耗时来自 QC 图片、退化修复或存储设备，整体提速会有限，这是预期行为。
