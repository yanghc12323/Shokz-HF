# 54 Region Remesh 上下文缓存设计

## 目标

对同一个样本的 54 个 region 复用确定性的 Remesh 前置计算，减少重复 CPU 工作，同时保持现有 Remesh 点、路径、UV、QC 判定和输出文件语义不变。

## 当前事实

- `config/region_table.csv` 包含 54 个 region；
- 所有 region 的 `resolution=24`；
- 共涉及 35 个 landmark；
- 当前 `build_region_remesh()` 在每个 region 内重复构建 mesh 邻接图、KDTree、landmark 吸附和 r24 template；
- 相邻 region 使用相同 landmark 顶点对时会重复执行最短路径计算。

## 设计

新增仅在单一样本 Remesh 进程内存活的 `RemeshContext`：

- `adjacency`：由 `build_mesh_adjacency(mesh)` 构建一次；
- `snapped_landmarks`：基于一个 KDTree 对该样本所需 landmark 一次性吸附；
- `path_cache`：以无方向顶点对为键缓存最短顶点路径；读取时按请求方向返回正向或反向路径；
- `templates`：以 `resolution` 为键缓存 `SubdivisionTemplate`。

`build_region_remesh()` 新增可选 context 参数。未传 context 时保留当前逐 region 独立执行行为，保证既有 API 和外部调用兼容。正式 `parameterize_ear_remesh.py` 在循环 54 个 region 前创建一个 context，并传入每次 region 计算。

## 一致性边界

- 不改变 Dijkstra 权重、起止顶点、tie 行为、UV 求解、采样、修复或 QC 阈值；
- 缓存仅复用同一次计算已经得到的对象；
- 输出 CSV/PLY 的内容、region 顺序、点序和面拓扑必须保持不变；
- 运行耗时、日志时间戳和内存地址可变化，不属于分析结果。

## 验收

1. 有/无 context 的同一 region 产生相同的路径、UV、模板、3D 点和面；
2. 同一 context 中的多 region 只构建一次邻接图与 KDTree；
3. 共享边路径在反向请求时只运行一次最短路径算法，且返回正确方向；
4. 54 region 的实际表格只生成一次 r24 template；
5. 现有 Remesh 测试与全流程配置测试通过；
6. 不修改 CLI 参数和输出目录契约。

## 自检

- 没有固定写入 54 或 35；实际缓存从传入 regions 动态提取；
- context 生命周期限制在单样本子进程，不跨 mesh 或跨样本复用；
- 共享路径缓存按顶点 ID 而非 landmark 名称键控，确保等价端点复用；
- 不涉及 GPU、并行度或数值库替换。
