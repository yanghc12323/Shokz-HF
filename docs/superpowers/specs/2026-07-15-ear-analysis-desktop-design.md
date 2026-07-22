# 耳模型分析工程软件设计规格

> 日期：2026-07-15  
> 状态：设计已在对话中确认，等待书面规格复核  
> 目标平台：Windows 10/11  
> 推荐技术：PySide6 + PyVistaQt/VTK  
> 项目根目录：由用户在软件中选择，不由软件搬迁或重建

## 1. 目标

将当前已经可由命令行运行的耳模型分析流程封装为本地 Windows 工程软件，覆盖：

1. 项目目录选择与输入检查；
2. 左右耳标准侧转换；
3. W2 Remesh、Raw/Repaired/Salvaged 质量检查；
4. 整耳全局模板、边界焊接与焊接修补；
5. GPA 和固定参考耳两种刚体对齐；
6. PCA、75% 累计方差阈值、平均耳、PC 形态和样本得分；
7. 实时任务进度、日志、取消、失败样本重跑；
8. 三维模型与质量检查结果查看；
9. 一键生成可追溯的汇报包。

软件服务于分析人员和标注同事，但第一版不区分账户或权限。

## 2. 明确不做的功能

第一版不提供 landmark 或 M 点的新增、拖动、吸附和三维坐标编辑。标注继续在 Geomagic 中完成，软件只读取和校验导出的文件。

第一版还不包含：

- 用户登录、账户和权限系统；
- 云端同步、远程任务和网络服务；
- 数据库服务器；
- 在界面层重新实现 Remesh、Weld、Alignment 或 PCA 算法；
- 自动降低质量门禁或把 FAIL 改成 WARNING/PASS；
- 自动删除或覆盖历史分析结果；
- 将软件做成网页或依赖浏览器运行。

## 3. 用户与典型任务

### 3.1 分析人员

- 打开项目并检查所有输入是否成对；
- 配置样本范围、参考耳、对齐方式和 QC 图开关；
- 从 Remesh 运行到 PCA，观察进度和失败原因；
- 查看各层 QC、整耳、对齐和 PCA 结果；
- 重跑失败样本或指定阶段；
- 生成汇报包。

### 3.2 标注同事

- 打开同一项目查看输入文件是否被正确识别；
- 查看由标注问题导致的失败区域和处理建议；
- 回到 Geomagic 修改标注并重新导出；
- 在软件中重新扫描项目并重跑相应样本。

## 4. 项目目录契约

软件直接使用现有项目结构：

```text
<project_root>/
  data/
    clean_mesh/
      <sample_tag>.ply
    landmarks/
      <sample_tag>_landmarks.csv
  config/
    region_table.csv
    edge_control_points.csv
  output/
  ear_param/
  scripts/
```

基本规则：

- 原始输入目录只读，软件不修改 `data/` 和 `config/`；
- mesh 与 landmark 通过相同的 `<sample_tag>` 配对；
- M 点坐标由 Geomagic 标注后写入相应 landmark 数据；
- `edge_control_points.csv` 定义哪些共享边使用哪些 M 点；
- 配对缺失、列缺失、坐标非数值、重复标识、区域引用不存在等问题必须在运行前报告；
- 输入检查只判断结构和可运行性，不替代算法阶段的几何 QC。

## 5. 技术路线比较与选择

### 5.1 采用：PySide6 + PyVistaQt/VTK

- PySide6 提供 Windows 原生窗口、表格、菜单、任务状态和进程管理；
- PyVistaQt/VTK 用于 PLY、整耳、平均耳和 PC 形态的三维显示；
- 现有 Python 模块和脚本可直接复用；
- 最终可使用 PyInstaller 打包为 Windows 文件夹式程序包。

### 5.2 不采用：仅做命令行壳

开发量较小，但不能在软件内有效查看三维 QC、整耳和 PCA 形态，不能满足完整工程软件目标。

### 5.3 不采用：Electron/Tauri + Python 后端

会引入前端、桌面壳和 Python 服务之间的通信及双技术栈打包。对当前项目而言维护成本高于收益。

## 6. 总体架构

```text
ear_desktop/
  app/                 # 程序启动、主窗口、全局异常处理
  ui/                  # 页面和可复用控件，只负责交互与展示
  project/             # 项目扫描、输入校验、样本索引
  tasks/               # 命令构建、后台进程、事件与取消
  results/             # CSV/JSON/PLY/PNG/PCA 结果解析
  visualization/       # PyVistaQt 三维查看器
  reports/             # 汇报包生成
  models/              # 页面使用的只读领域模型和状态枚举
```

边界要求：

- `ear_desktop` 不复制 `ear_param` 中的几何或统计算法；
- 长任务通过独立 Python 进程运行正式脚本，避免阻塞界面；
- 结果状态从正式 CSV/JSON 读取，界面不另设一套判定公式；
- 每个模块只通过明确的数据对象或事件通信，不直接操作其他页面控件。

## 7. 工作区设计

### 7.1 项目与数据

显示：

- 当前项目根目录；
- 样本清单、侧别、mesh/landmark 是否存在；
- `region_table.csv`、`edge_control_points.csv` 和参考耳检查结果；
- READY、CHECK 和 BLOCKED 状态及具体原因。

操作：打开项目、重新扫描、打开文件所在目录、进入批处理中心。

### 7.2 批处理中心

配置：

- 全部 READY 样本或用户选择的样本；
- 完整流程或指定阶段；
- 是否生成 Remesh QC 图；
- GPA、固定参考耳或两条分支都运行；
- 固定参考耳，正式默认值为 `T076_L`；
- Salvage 退化面比例等已经由正式 CLI 暴露的参数。

运行反馈：

- 当前样本、区域和阶段；
- 样本总进度与阶段进度；
- 实时日志；
- PASS/WARNING/FAIL/ERROR/SKIPPED 状态；
- 已耗时；如无法可靠估算，不显示虚假的剩余时间。

控制：开始、安全取消、打开运行目录、重跑失败样本、重跑指定阶段。

### 7.3 质量检查

支持按以下维度筛选：

- 样本；
- region；
- Raw、Repaired、Salvaged、Weld；
- PASS、WARNING、FAIL；
- unmapped、degenerate、边界焊接等失败原因。

同一页面显示三维模型或 QC 图、数值指标、原始与修补状态、失败原因和建议。QC 页面只读，不修改结果。

### 7.4 整耳与对齐

显示：

- Salvaged 区域拼接后的整耳；
- 焊接前后状态及共享边统计；
- 边界焊接 QC；
- GPA 或固定参考耳对齐结果；
- 标准侧、镜像轴、参考耳、是否缩放；
- `pca_ready` 及未准入原因。

### 7.5 PCA 分析

支持两个彼此独立的 PCA 数据分支：

- GPA 对齐；
- 固定参考耳对齐，正式参考耳为 `T076_L`。

显示：

- 实际纳入和排除的样本；
- 排除原因；
- 每个 PC 的解释率和累计解释率；
- 达到 75% 阈值所需的最少 PC 数；
- 平均耳；
- PC1、PC2 及其他保留 PC 的正负 2 标准差形态；
- 样本 scores；
- GPA 与固定参考耳的方差、平均耳、PC 形态和 scores 对比结果。

界面不得将两条对齐分支的 components 或 scores 混为同一坐标系下的原始数值。

### 7.6 结果导出

一键生成只读汇报包，至少包含：

- 项目、代码版本、参数和运行环境摘要；
- 样本发现、各阶段状态和通过率；
- WARNING/FAIL/ERROR 清单；
- 关键 Raw/Repaired/Salvaged/Weld QC 图；
- 整耳、焊接和对齐结果；
- PCA 准入清单、解释率、平均耳、PC 形态和 scores；
- 原始成果文件索引；
- 完整日志。

第一版报告格式为本地 HTML、XLSX 汇总表和配套文件目录。报告是导出物，不代表软件采用网页架构。

## 8. 任务执行与进度协议

### 8.1 后台进程

使用 `QProcess` 启动独立计算进程。开发环境中调用项目 Python 解释器和正式脚本；打包环境中调用同一安装目录内的 `ear-analysis-worker.exe`。Worker 只是现有正式编排器和阶段脚本的打包入口，不复制几何或统计算法。

完整群体分析继续以 `scripts/run_full_pipeline.py` 为唯一主入口。诊断性单样本重跑使用现有 `parameterize_ear_remesh.py`、`visualize_remesh_qc.py` 和 `build_whole_ear.py`，由桌面任务层显式传入该诊断任务的输入与输出目录。桌面层不自行串联算法函数。

界面进程不得直接执行长时间 NumPy/VTK/Remesh 计算。

### 8.2 机器可读事件

不能长期依赖解析自由格式终端文本。正式实施时为编排器增加 JSON Lines 事件输出，示例：

```json
{"event":"stage_started","sample_tag":"T078_L","stage":"REMESH"}
{"event":"region_finished","sample_tag":"T078_L","region_id":"T013","status":"PASS"}
{"event":"sample_finished","sample_tag":"T078_L","stage":"REMESH","status":"PASS"}
```

终端文本继续保留给人工阅读；桌面软件以事件流更新进度，以正式结果文件确认最终状态。

### 8.3 取消

- 用户取消后先请求子进程正常结束；
- 超时后使用 `psutil` 按任务主进程 PID 递归终止其进程树，只处理本软件启动的任务；
- 已写完的样本成果保留；
- 当前批次状态记为 CANCELLED；
- 不将部分文件冒充为 PASS；
- 再次打开软件时能够读取该批次的已完成记录。

### 8.4 重跑语义

- “重跑失败样本”创建新的诊断任务，只对选中样本执行 Remesh、QC，并可验证该样本的整耳 Weld；
- 单样本诊断任务不运行 PCA，也不把新结果混入某个已经完成的正式群体批次；
- Alignment 和 PCA 属于群体级结果。修复样本需要进入正式统计时，用户必须基于当前输入启动新的完整群体批次；
- 每次诊断重跑和完整群体重跑都有新的运行编号，不覆盖旧批次；
- 如果当前输入文件相对历史 manifest 已发生变化，历史结果仍可作为当时输入的有效记录，但界面显示 STALE，表示它不再代表项目当前输入。

## 9. 输出隔离与追溯

### 9.1 当前缺口

当前 `scripts/run_full_pipeline.py --run_dir ...` 主要隔离：

```text
pipeline_batch_summary.csv
pipeline_run_summary.csv
pipeline_run.log
```

Remesh、QC、Weld、Alignment 和 PCA 的主要成果仍由 `PipelineConfig` 默认写入若干固定 `output/...` 目录。桌面软件不能据此宣称已经实现完整的历史批次隔离。

### 9.2 实施要求

桌面版开发的第一项基础工作是为正式编排器增加运行作用域，使一次运行的所有阶段成果位于同一批次目录，例如：

```text
output/pipeline_runs/<run_id>/
  manifest.json
  events.jsonl
  logs/
  canonical_inputs_r24/
  parameterized_points_r24/
    raw/
    repaired/
    salvaged/
  remesh_r24/
    raw/
    repaired/
    salvaged/
  remesh_qc_r24/
  whole_ear_r24/
    weld_repaired/
    aligned_gpa/
    aligned_reference_T076_L/
  pca_gpa_r24/
  pca_reference_T076_L_r24/
  reports/
```

保留现有命令行默认目录行为以避免破坏成熟功能；桌面端必须显式传入运行作用域目录。

### 9.3 Manifest

`manifest.json` 至少记录：

- run_id、创建时间、结束时间和状态；
- 项目根目录；
- 样本清单及输入文件相对路径；
- 输入文件大小、修改时间，条件允许时记录哈希；
- region table 和边界控制表信息；
- resolution、Salvage 门禁和 QC 参数；
- 标准侧与镜像轴；
- 对齐分支和参考耳；
- PCA 方差阈值；
- Python、主要依赖和代码版本；
- 各阶段输出相对路径。

## 10. 结果解析与状态来源

状态优先级：

1. 正式阶段 CSV/JSON 结果；
2. 机器可读事件流用于运行中展示；
3. 普通日志仅用于诊断。

界面状态模型统一使用：

```text
NOT_STARTED
RUNNING
PASS
WARNING
FAIL
ERROR
SKIPPED
CANCELLED
STALE
```

Raw、Repaired、Salvaged、Weld 和 Alignment 的门禁继续由现有算法模块决定。GUI 不复制阈值，也不根据图像外观自行改判。

## 11. 三维显示与性能

- 模型按需加载，不在打开项目时一次载入全部 PLY；
- 切换样本时释放不再需要的 VTK 对象，只保留小容量缓存；
- 三维显示允许使用只影响视图的抽稀副本，但下载、统计和正式结果始终使用原文件；
- 大型 CSV 使用分页或表格模型按需读取；
- QC PNG 使用缩略图列表，选中后加载原图；
- 三维视图提供旋转、平移、缩放、复位、标准视角、边界显示和截图；
- 任何显示失败都不能修改或破坏计算结果。

## 12. 故障处理

### 12.1 运行前阻断

以下问题阻止对应样本或批次启动：

- 项目根目录无效；
- 脚本或 Python 环境不可用；
- mesh/landmark 缺少配对；
- 配置表格式错误或引用不存在；
- 固定参考耳不存在或未达到输入条件；
- 输出批次目录已存在且非空。

### 12.2 运行中故障

- 单样本异常写为 ERROR，其他样本继续；
- 批次级 Weld/Alignment/PCA 异常终止该分支并保留上游成果；
- 进程退出码、异常摘要和日志路径必须展示；
- 不把“QC 图片生成失败”等同于几何 FAIL，但必须单独记录；
- 报告生成失败不影响正式分析结果。

### 12.3 恢复

软件启动或打开项目时扫描 `output/pipeline_runs/`：

- 已完成批次可直接浏览；
- CANCELLED/ERROR 批次可查看已有成果并创建重跑任务；
- 缺少结束标记且无活动进程的批次标记为 INTERRUPTED；
- 不自动继续一个来源和参数未知的中断任务。

## 13. 测试策略

### 13.1 单元测试

- 项目目录扫描和样本配对；
- landmark、region table、edge control table 校验；
- 运行目录与 manifest 生成；
- CLI 参数和命令构建；
- JSONL 事件解析；
- 各阶段 CSV/JSON 状态解析；
- 汇总计数、筛选和排除原因；
- 报告数据模型。

### 13.2 集成测试

- 桌面任务调用 CLI 后的输出与直接命令行运行一致；
- 单样本失败不阻塞后续样本；
- 安全取消保留已完成结果且状态正确；
- 固定参考耳与 GPA 两条分支独立；
- 重跑产生新批次且不覆盖旧批次；
- 上游输入变化后旧下游结果能够识别为 STALE。

### 13.3 界面测试

- 项目打开、页面切换和筛选；
- 任务运行时界面保持响应；
- 日志追加不会导致内存无限增长；
- 1366×768、1920×1080 和高 DPI 缩放下无内容重叠；
- 三维场景非空，标准视角和边界显示有效；
- PASS/WARNING/FAIL 不只依赖颜色，还包含文字。

### 13.4 验收数据

- 使用 `T076_L` 作为稳定参考样本；
- 至少保留一个会触发 WARNING/FAIL 的样本验证诊断路径；
- 使用一小组样本完成快速回归；
- 最终使用当前完整数据集做端到端验收；
- 桌面端与命令行的关键 CSV、顶点数量、面拓扑、PCA 准入清单和汇总计数必须一致。

## 14. 打包与运行环境

推荐依赖：

```text
PySide6
pyvista
pyvistaqt
vtk
pandas
numpy
matplotlib
openpyxl
psutil
```

开发期从项目 Python 环境运行。交付期优先使用 PyInstaller `onedir` 模式，生成桌面主程序和独立计算 Worker；二者共同复用同一版本的 `ear_param` 代码。由于 VTK 和 Qt 体积较大，文件夹式程序包更容易启动、排错和升级。需要正式安装体验时，再使用 Inno Setup 等工具制作 Windows 安装程序。

软件默认离线运行，不发送遥测或项目数据。

## 15. 分阶段交付

### 阶段 A：运行隔离与机器可读任务接口

- 所有阶段支持运行作用域输出；
- manifest、events.jsonl、取消和状态恢复；
- 保持现有 CLI 默认行为兼容。

### 阶段 B：桌面骨架与项目管理

- 主窗口、工作区导航、项目打开；
- 输入扫描、校验、样本表；
- 历史批次发现。

### 阶段 C：批处理中心

- 命令构建、后台进程、实时事件和日志；
- 安全取消、失败重跑；
- 批次总表。

### 阶段 D：QC 与三维结果查看

- Raw/Repaired/Salvaged/Weld 筛选；
- PNG 对照与 PLY 三维查看；
- 整耳、边界、对齐结果。

### 阶段 E：PCA 与报告

- 方差、平均耳、PC 形态、scores；
- GPA/固定参考耳对比；
- HTML、XLSX 和成果目录汇报包。

### 阶段 F：打包与全量验收

- Windows onedir 包；
- 高 DPI、异常恢复和完整数据集测试；
- 用户使用文档与交付清单。

## 16. 完成标准

软件只有在满足以下条件时才可认为第一版完成：

1. 能打开现有项目目录而不改动原始数据；
2. 能识别并解释输入错误；
3. 能从 Remesh 运行到 GPA/固定参考耳 PCA；
4. 长任务期间界面保持响应并显示真实进度；
5. 能安全取消并重跑失败样本；
6. 能查看 Raw/Repaired/Salvaged/Weld、整耳、对齐和 PCA 结果；
7. 能生成可追溯汇报包；
8. 不同批次不互相覆盖；
9. 桌面端结果与正式命令行结果一致；
10. 全量自动测试和代表性端到端验收通过。
