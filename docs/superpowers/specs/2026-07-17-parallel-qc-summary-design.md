# 并行 Remesh QC 独立汇总设计

## 目标

在桌面端已启用多样本 Remesh 并行的基础上，让对应的 Remesh QC 也能安全并行，同时保持既有 CLI 默认行为、最终 QC 汇总文件名和结果判定不变。

## 根因

`scripts/visualize_remesh_qc.py` 对每次调用均写入同一个 `<out_dir>/<layer>/qc_visualization_summary.csv`。以单样本方式并发调用时会相互覆盖，导致读取到错误样本或损坏汇总文件。

## 设计

1. QC CLI 新增可选 `--summary-dir` 参数。
   - 未提供时，继续向 `--out_dir` 写入标准汇总 CSV，保持独立 CLI 与历史调用完全兼容。
   - 提供时，PNG 仍写入原 `--out_dir/<layer>/<sample>/<region>_qc.png`；仅三份 summary CSV 写入该独立目录的 `raw/`、`repaired/`、`salvaged/`。
2. 全流程每个样本将 Remesh 与 QC 作为同一工作线程中的连续工作执行；QC 使用 `<qc_dir>/_sample_summaries/<sample_tag>` 作为独立汇总目录。
3. 所有样本工作完成后，协调线程读取独立 summary，按 `sample_tag`、`region_id` 稳定排序，合并写回既有标准文件：
   - `<qc_dir>/raw/qc_visualization_summary.csv`
   - `<qc_dir>/repaired/qc_visualization_summary.csv`
   - `<qc_dir>/salvaged/qc_visualization_summary.csv`
4. 合并失败不改变 Remesh/QC 样本判定；它作为全流程错误抛出，因为标准审计产物不完整。每样本 QC 结果仍由其私有 summary 读取。
5. 暂停/取消仍在工作提交前的安全检查点生效；已提交的 Remesh+QC 工作单元完成后再响应。

## 兼容性与验收

- 不传 `--summary-dir` 的 QC CLI 输出路径、CSV 内容和参数含义不变。
- 相同输入、参数下，并行与串行的逐样本 `remesh_qc` 状态、合并后的 QC summary 内容一致。
- 并发测试证明两个 QC 调用可重叠执行，且每个调用读取自身 summary。
- 最终标准 summary 仍存在，供已有结果复核、人工检查和旧脚本使用。
