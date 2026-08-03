# Remesh CUDA 混合加速设计

## 目标

在 Windows 10/11 离线工作站的 RTX 3050 6GB 显卡上，加速 Remesh 的高耗时计算，同时保持 CPU 与 CUDA 路径在以下范围内一致：

- 输出 remesh 三维点逐坐标最大绝对误差不超过 `1e-8 mm`；
- 每个 region 的 raw、salvaged、QC 状态完全一致；
- Weld、对齐与 PCA 入组结果完全一致。

CPU 路径保持默认、无 GPU 依赖且结果不变。

## 现状与结论

当前 `cKDTree` 在 `prepare_remesh_context` 中每个样本仅建立一次，并批量吸附全部 landmark，已经有缓存，不作为第一阶段 GPU 目标。较大的计算量来自：

1. 同一网格上不同 landmark 边反复执行单源 Dijkstra；
2. 各 region 的 harmonic UV 稀疏方程求解；
3. UV 样本点逐点、逐三角面的定位与三维回映；
4. 退化 UV 的候选修复及 r48 致密验证重复执行上述步骤。

CuPy 可提供 Windows/CUDA 12 的 GPU 数组和稀疏 `spsolve`，但不提供 SciPy `dijkstra` 的等价实现。因此第一版不引入 WSL2/cuGraph，也不编写自定义 CUDA 图最短路。

## 架构

### 计算后端

新增一个仅供 Remesh 内部使用的后端接口，支持：

- `cpu`：现有 NumPy/SciPy 实现，默认；
- `cuda`：使用 CuPy 的 `float64` 数组、GPU 稀疏求解与 GPU UV 定位/映射；
- `auto`：启动时检测 CuPy、CUDA 设备和可用显存；条件不满足时记录原因并回退 `cpu`。

CUDA 是可选依赖。未安装或初始化失败时，CPU CLI、桌面软件、打包软件均可正常使用。

### CPU 最短路缓存

以起点顶点 ID 为键，在每个 `RemeshContext` 中缓存一次 `dijkstra(..., return_predecessors=True)` 返回的距离和前驱树。任意边 `(start, end)` 从该起点树重建路径；反向边复用同一无向路径再反转。此改动保持 SciPy 调用、权重、前驱规则和路径重建规则不变。

### CUDA 任务与显存策略

CUDA 仅处理彼此独立的 region UV 数组：

- 将单个 patch 的稀疏 Laplacian 和二维 RHS 上传至 GPU，以 `float64` 求解 U、V；
- 以 GPU 内核并行计算 UV 中每个输出模板点的候选三角面与重心坐标，并按 CPU 面序取第一个合法面；
- 以 GPU 并行进行重心三维映射后将结果复制回 NumPy。

GPU 任务通过进程内互斥锁串行提交。样本级 Remesh 仍可由现有 CPU 工作线程并行调度，但最多一个线程持有 GPU。每次只保留一个 region 的 GPU 稀疏矩阵、UV 和映射缓冲区，使用后立即释放，适配 6GB 显存。

### 数值安全与回退

每次 CUDA Remesh 结果均执行既有 QC、退化修复和致密验证规则。出现 CUDA 不可用、CUDA 内存/运行错误、UV/三维点非有限或后端内部结构校验失败时，即将当前 region 从原始 CPU 输入重算并采用 CPU 结果。正常的分析 QC FAIL 仍按既有规则如实输出，不能因为它是 FAIL 而自动改走 CPU。

`auto` 只负责可用性回退，不静默改变已选择的 CUDA 成果。CPU/CUDA 的逐点和逐 QC 对照作为发布前的固定验证集门禁，而非每次生产运行重复执行。运行 manifest、样本处理时间表和 region QC 中记录：请求后端、实际后端、回退原因、CPU/CUDA 算子耗时和峰值显存。

## 验证策略

新增固定 GPU 对照集测试，使用代表性正常 region、边界复杂 region、退化修复 region 和致密覆盖修复 region。对每个样本分别执行 `cpu`、`cuda`：

1. 逐区域对比采样三维点，最大绝对坐标差 `<= 1e-8 mm`；
2. 比较 face ID、重心坐标合法性、unmapped mask、修复方法和 QC 字段；
3. 比较整耳 Weld 汇总、对齐结果、PCA 入组 manifest；
4. 记录 CPU/CUDA 的阶段耗时、加速比和 GPU 峰值显存。

GPU 硬件不可用的开发或 CI 环境中，CUDA 专项测试跳过；CPU 回归测试必须持续通过。

## CLI 与桌面软件

全流程 CLI 新增：

```text
--remesh-backend {cpu,cuda,auto}
```

默认 `cpu`，保证历史命令与结果不变。桌面软件的运行参数页增加同一选项，默认“CPU（稳定）”；“CUDA（实验性）”与“自动检测”在不可用时显示回退原因，不阻止 CPU 分析。

## 离线部署

GPU 包不并入基础 `requirements.txt`。另建 GPU 可选依赖清单，锁定兼容 RTX 3050、CUDA 12 和项目 Python/NumPy 版本的 CuPy wheel 及其 CUDA 组件。为离线工作站下载 wheel 到单独目录，安装和自检命令写入部署文档。

## 不在范围内

- 不引入 WSL2、Linux、cuGraph、Docker 或云计算。
- 不实现自定义 CUDA Dijkstra。
- 不更改 region table、网格坐标、Weld 阈值、修复门禁或 PCA 统计方法。
- 不要求 GPU；没有 CUDA 的机器继续使用当前 CPU 流程。
