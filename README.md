# Shokz 耳廓降采样与形态分析（CLI）

本仓库是面向 Windows 工作站的命令行分析工具。它将带有 35 个标点的耳廓 PLY 网格统一到 canonical 左耳坐标系，按 Region 重参数化为固定 r24 拓扑，执行质量控制与整耳拼接，最后输出固定参考耳或 GPA 配准后的平均耳、PCA、主成分极值形态和探索性聚类结果。

本项目仅保留 CLI 工作流；不再提供桌面应用或 EXE 构建功能。

## 1. 仓库边界

纳入版本控制的内容：

- ear_param/：重参数化、质控、拼接、配准、PCA 与形态分析核心；
- scripts/：可直接调用的 CLI 入口；
- config/region_table.csv：当前 Region 定义；
- tests/：算法与 CLI 回归测试；
- docs/：CLI、GPU 和方法说明；
- requirements.txt 与 requirements-gpu.txt：CPU 必需依赖及可选 GPU 依赖。

不纳入版本控制的内容：

- 真实 PLY 网格、landmark CSV、运行输出、离线 wheel、汇报材料、截图、报告渲染缓存和 landmark 重映射资料；
- 这些文件可保留在本地或数据归档盘，但不得执行 git add -f 纳入代码仓库。

## 2. 环境安装

要求：Windows 10/11、Python 3.11+，建议使用独立虚拟环境。

~~~
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
~~~

如果 PowerShell 禁止执行激活脚本，可始终直接使用 .\.venv\Scripts\python.exe，无需激活虚拟环境。

### 可选：GPU Remesh 加速

GPU 仅用于 Region 参数化中的部分数值计算；CPU 仍负责网格读取、最短路径、QC、拼接、配准和 PCA。安装与离线部署见 [GPU_ACCELERATION_OFFLINE.md](docs/GPU_ACCELERATION_OFFLINE.md)。

~~~
.\.venv\Scripts\python.exe -m pip install -r requirements-gpu.txt
.\.venv\Scripts\python.exe -c "from ear_param.remesh_backend import backend_diagnostics; print(backend_diagnostics('auto'))"
~~~

若诊断结果中 effective 为 cuda，即可在全流程命令中使用 --remesh-backend auto。当 CUDA 局部计算不可用时，auto 会回退到 CPU；如需完全 CPU 基线，显式使用 --remesh-backend cpu。

## 3. 输入要求

### 3.1 网格

将清理后的 PLY 网格放入自行指定的数据目录，例如：

~~~
data/
  clean_mesh/
    MQ_S001L.ply
    MQ_S001R.ply
    MQ_S076L.ply
~~~

样本标签为 MQ_S###L 或 MQ_S###R。L/R 是原始侧别，不表示最终分析坐标：右耳会在进入重参数化前沿 X 轴镜像，并反转三角面绕序，得到 canonical 左耳坐标；原始输入不会被改写。

### 3.2 Landmark

landmark 文件名使用 T###_L_landmarks.csv 或 T###_R_landmarks.csv，并与网格样本按编号和侧别匹配。例如：

~~~
data/
  landmarks/
    T001_L_landmarks.csv
    T001_R_landmarks.csv
    T076_L_landmarks.csv
~~~

每个样本必须具有当前 Region Table 所需的 35 个 landmark。CLI 会自动将 MQ_S001L 映射到 T001_L_landmarks.csv；如名称或侧别不能配对，样本会在预检中被记录为不可运行。

### 3.3 Region Table

config/region_table.csv 是唯一正式 Region 配置。当前版本共 54 个 Region，全部采用 r24 采样模板。若需要修改 Region 或 landmark 边界，应修改配置文件并重新运行；不要在单次输出中手工修改中间结果。

## 4. 一键全流程

以下是推荐的 Windows PowerShell 命令。它会依次执行：输入发现与 canonical 化 → Remesh/QC → 整耳拼接与边界修复 → 刚体配准 → PCA、平均耳、极值形态与聚类。

~~~
.\.venv\Scripts\python.exe scripts\run_full_pipeline.py --mesh_dir data\clean_mesh --landmarks_dir data\landmarks --regions config\region_table.csv --parallel-workers 6 --remesh-backend auto --alignment-mode fixed-reference --reference-sample MQ_S076L --qc-figure-mode repaired-fail --output-root output\runs\mq_full_YYYYMMDD
~~~

参数说明：

| 参数 | 作用 |
|---|---|
| --parallel-workers N | 同时运行的样本数。0 为自动；应根据 CPU 核数、内存和单个网格规模调整。CPU/内存已接近饱和时不应继续增大。 |
| --remesh-backend cpu\|auto\|cuda | cpu 为严格 CPU 基线；auto 优先用 CUDA 并允许局部 CPU 回退；cuda 要求 GPU 后端可用。 |
| --alignment-mode fixed-reference | 将所有通过 Weld 的样本刚体配准到指定参考耳。 |
| --reference-sample MQ_S076L | 固定参考耳。必须存在并通过 Weld；可按研究设计改为其他合格样本。 |
| --alignment-mode gpa | 改用广义 Procrustes 分析（GPA）共同配准。 |
| --qc-figure-mode all | 为所有 Region 导出 QC PNG，最慢。 |
| --qc-figure-mode repaired-fail | 仅为修复后仍失败的 Region 导出 QC PNG，推荐正式批处理使用。 |
| --qc-figure-mode none | 不导出 QC PNG，仅保留 CSV、manifest 和日志。 |
| --output-root | 本轮唯一输出目录；目录必须在启动前不存在或为空，避免与旧运行混合。 |
| --skip-pca | 仅完成 Remesh、拼接和配准，不运行 PCA。 |
| --samples MQ_S001L MQ_S001R | 仅运行指定样本，适用于复核或重跑。 |

完整参数：

~~~
.\.venv\Scripts\python.exe scripts\run_full_pipeline.py --help
~~~

## 5. 运行状态与质量门禁

每个样本依次接受以下门禁：

1. 输入预检：网格、landmark、Region Table 是否存在且可配对；
2. Remesh/QC：每个 Region 的 r24 点位、UV 覆盖、退化面及修复/Salvage 状态；
3. Weld：Region 共边界一致性、全局面拓扑和面朝向；
4. Alignment：仅对 Weld 通过的整耳执行 GPA 或固定参考耳刚体配准；
5. PCA：仅纳入拓扑一致且 PCA-ready 的对齐样本。

PASS 表示可进入下一阶段；WARNING 表示有可审计的轻度问题；FAIL 表示当前结果不应进入后续统计；ERROR 表示样本级脚本异常，应优先查看该轮日志和 manifest。单个 Region 的 FAIL 不一定导致进程异常，但会影响整耳 Weld 和 PCA 入组。

## 6. 输出结构

使用 --output-root output\runs\<run_name> 时，所有产物被隔离在同一轮目录中。主要目录如下：

~~~
<run_name>/
  manifest.json                         本轮输入、参数、代码状态和最终摘要
  pipeline_summary.csv                  每样本跨阶段状态
  sample_timings.txt                    每个样本的处理时长
  canonical_inputs_r24/                 canonical 化后的输入副本及审计信息
  parameterized_points_r24/
    salvaged/                           最终用于后续步骤的 points、faces、QC CSV 与后端诊断
  remesh_r24/salvaged/                  Region 重网格 PLY
  qc_visualizations_r24/                按选择的档位输出 QC PNG 与汇总 CSV
  whole_ear_r24/
    weld_repaired/                      拼接整耳 PLY、Weld QC 与拓扑审计
    aligned_reference_<reference>/      固定参考耳配准结果
  pca_reference_<reference>_r24/        平均耳、PCA score、主成分形态
    pca_morphology/                     聚类、极端个体和类别平均耳
~~~

当前正式批处理只完整保留 salvaged 层的几何与点位输出。raw/repaired 状态信息保留在最终 QC 记录、汇总表和 manifest 中，避免为每个样本重复写入大量中间 PLY/CSV。

PCA 形态分析目录中的关键文件：

- mean_whole_ear.ply：全部 PCA 入组样本的平均耳；
- scores.csv：每个样本的 PCA score；
- pc_modes/PC01_plus_2sd.ply 等：PC1、PC2 的 ±2 SD 形态；
- pca_morphology/cluster_k_selection.csv：候选簇数的 silhouette 比较；
- pca_morphology/cluster_assignments.csv：样本所属簇与 PCA score；
- pca_morphology/cluster_means/Cluster_XX_mean.ply：各簇平均耳。

## 7. 单阶段命令

一般应优先运行全流程。以下入口仅用于定位问题或对既有结果做单阶段复核：

~~~
.\.venv\Scripts\python.exe scripts\parameterize_ear_remesh.py --help
.\.venv\Scripts\python.exe scripts\build_whole_ear.py --help
.\.venv\Scripts\python.exe scripts\align_whole_ear.py --help
.\.venv\Scripts\python.exe scripts\build_average_ear.py --help
~~~

## 8. 验证与开发

~~~
python -m compileall -q ear_param scripts
python -m pytest tests -q
git diff --check
git status --short
~~~

## 9. 相关说明

- GPU 离线安装、诊断和 CPU/GPU 数值一致性要求：[GPU_ACCELERATION_OFFLINE.md](docs/GPU_ACCELERATION_OFFLINE.md)
- Region Remesh 的方法与 QC 说明：[W2 Remesh 使用说明.md](docs/W2%20Remesh%20使用说明.md)
- 整耳模板、Weld 与刚体坐标系统一：[整耳全局模板、边界焊接与刚体统一坐标系.md](docs/整耳全局模板、边界焊接与刚体统一坐标系.md)
- PCA、平均耳与形态学结果：[W3 PCA 与平均耳技术路线.md](docs/W3%20PCA%20与平均耳技术路线.md)
