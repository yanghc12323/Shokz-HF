# 正式全流程批处理入口设计

## 1. 目标

新增一个正式命令行入口 `scripts/run_full_pipeline.py`。它自动发现
`data/clean_mesh/` 与 `data/landmarks/` 中成对存在的耳朵样本，并按既有
W2/W3 主线运行：remesh、salvage、remesh 可视化 QC、整耳 Weld repair、刚体
对齐、PCA 与平均耳。该入口只编排已有流程，不重写任何几何算法。

## 2. 输入发现规则

1. 只接受 `data/clean_mesh/<sample_tag>.ply`，其中 `<sample_tag>` 的格式由
   文件名保留，例如 `T076_L`。
2. 每个 mesh 必须存在配对 landmark 文件
   `data/landmarks/<sample_tag>_landmarks.csv`。
3. 发现结果分为：`READY`（配对完整）、`MISSING_LANDMARKS`、
   `MISSING_MESH`。后两类不进入计算，但必须写入总表。
4. 仅处理同一侧别的完整配对样本。若发现 L/R 混合，Weld 可以分别构建，
   但对齐/PCA 必须在单一侧别中运行；本轮默认拒绝混合侧别进入同一个 PCA。

## 3. 阶段与状态传播

每个 READY 样本依序经过：

```text
DISCOVERED
-> REMESH
-> SALVAGED
-> REMESH_QC
-> WELD_REPAIRED
-> ALIGNMENT
-> PCA_INCLUDED
```

- `REMESH`：执行当前论文式 patch-based remesh，并分别写 raw/repaired/
  salvaged 输出。
- `SALVAGED`：只有 15 个 region 均为最终 PASS 的样本才进入整耳处理。
- `REMESH_QC`：为已生成样本写 raw 与 repaired 的 QC 可视化；可视化失败
  不篡改 remesh 的几何判定，但总表必须记录。
- `WELD_REPAIRED`：对所有 salvage 合格样本组装整耳，并启用已有保守共享边
  修补。只有 Weld `status=PASS` 且 `pca_ready=True` 才进入对齐。
- `ALIGNMENT`：对所有 PCA-ready 整耳做当前 Kabsch/GPA 刚体对齐。只有
  alignment `status=PASS` 才可进入 PCA。
- `PCA_INCLUDED`：若对齐 PASS 样本不少于 2，则运行 W3 PCA；PCA 的实际纳入
  仍由其独立 provenance/topology 门禁决定。

任何样本在某一几何/QC 阶段 FAIL 后，停止该样本之后的阶段，但整批继续。
异常同样被捕获并记录为 `ERROR` 与简短错误信息；不会中断其他样本。

## 4. 实现边界

新增一个很薄的编排模块和入口：

```text
ear_param/pipeline.py           # 发现、阶段状态、批次汇总与调用适配
scripts/run_full_pipeline.py    # argparse、实时终端输出、最终总表打印
tests/test_pipeline.py          # 样本发现、失败隔离、汇总与命令行测试
```

为避免复制或漂移，现有脚本中仅抽取必要的可复用单样本/批次函数；
`parameterize_ear_remesh.py`、`build_whole_ear.py`、`align_whole_ear.py`、
`build_average_ear.py` 仍保留为可独立运行的阶段入口。所有已有默认输出路径
保持不变。

## 5. 命令行接口

默认命令：

```powershell
python scripts/run_full_pipeline.py
```

默认读取：

```text
data/clean_mesh/
data/landmarks/
config/region_table.csv
```

默认输出使用现有正式目录：

```text
output/parameterized_points_r24/
output/qc_visualizations_r24/
output/whole_ear_r24/weld_repaired/
output/whole_ear_r24/aligned_weld_repaired/
output/w3_pca_r24/
output/pipeline_runs/<run_id>/
```

可选参数必须允许替换上述输入/输出根目录、指定 resolution 表、仅运行指定
`--samples`，以及通过 `--skip-pca` 跳过最后 PCA。默认绝不删除旧输出。

## 6. 终端反馈与总表

运行时输出固定格式的进度行：

```text
[Pipeline] [1/12] T076_L REMESH ... PASS
[Pipeline] [1/12] T076_L WELD ... PASS
[Pipeline] [1/12] T076_L ALIGNMENT ... PASS
```

结束后打印总表，至少包含：

```text
sample_tag | discovery | remesh | salvage | remesh_qc | weld | alignment | pca_included | reason
```

并打印整批计数：发现数、完整配对数、缺失配对数、各阶段 PASS/FAIL/ERROR 数、
PCA 实际纳入数、保留 PC 数和累计解释方差。

同一信息写入：

```text
output/pipeline_runs/<run_id>/pipeline_batch_summary.csv
output/pipeline_runs/<run_id>/pipeline_run_summary.csv
output/pipeline_runs/<run_id>/pipeline_run.log
```

`pipeline_batch_summary.csv` 每行对应一个发现样本；`pipeline_run_summary.csv`
为单行批次统计；日志记录阶段开始、结束、异常和最终 PCA 结论。

## 7. 失败与 PCA 规则

- `T049_L` 一类 Weld FAIL 保持失败，不由总控脚本修改阈值或自动纳入 PCA。
- `MISSING_LANDMARKS`、`MISSING_MESH`、`ERROR`、任意 QC FAIL 均在总表显式可见。
- PCA 仅在至少两个 alignment PASS 样本时执行；不足时记 `SKIPPED_INSUFFICIENT_SAMPLES`。
- 若 PCA 自身拒绝某个对齐样本，以 `pca_input_manifest.csv` 为最终证据，并将
  原因回填到批次总表。

## 8. 验证标准

测试必须覆盖：

1. mesh/landmark 成对发现及缺失配对记录。
2. 单样本 remesh/Weld FAIL 或运行异常不阻断后续样本。
3. 下游只接收上一阶段 PASS 样本。
4. 总表状态、原因、计数与 PCA 纳入信息准确。
5. `--samples`、`--skip-pca` 与默认目录行为。
6. 现有 W2/Weld/alignment/PCA 全量回归不受影响。

## 9. 非目标

- 不修复 T049_L 的几何问题。
- 不改变 region table、M 点规则、Weld 阈值或 PCA 算法。
- 不删除旧运行输出，不自动覆盖用户指定的历史批次目录。
