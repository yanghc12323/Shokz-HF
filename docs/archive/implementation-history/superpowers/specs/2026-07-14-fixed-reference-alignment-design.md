# 固定参考耳刚体对齐设计

## 目标

保留现有 GPA 对齐作为群体 PCA 主路径，并新增一条基于指定参考耳的独立刚体对齐与 PCA 路径，用于工程坐标表达和对齐标准敏感性比较。

## 范围与边界

- 两条路径都从同一批 canonical-L、salvaged Weld 整耳输入开始。
- 两条路径均只使用 Kabsch 旋转和平移；不缩放、不二次镜像、不改变顶点顺序或三角面拓扑。
- GPA 路径仍为默认路径，输出到现有 `aligned_weld_repaired/` 与 `w3_pca_r24/`。
- 固定参考耳路径只有在调用方提供 `--reference-sample` 时执行，输出到独立的 `aligned_reference_weld_repaired/` 与 `w3_pca_reference_r24/`。
- 两个对齐目录和两个 PCA 目录不得混合读取。

## 固定参考耳算法

设参考样本的有序 landmark 为 `T`，任一样本 landmark 为 `S`。对每个样本独立计算 Kabsch 最优刚体变换：

`S_aligned = R * S + t`

其中 `R` 是行列式为 +1 的旋转矩阵，`t` 是平移向量。参考样本本身也通过相同计算输出，从而形成可审计的恒定工程坐标系。

## 接口与交付

- `ear_param.alignment.fixed_reference_alignment()`：可单元测试的 landmark 对齐核心。
- `scripts/align_whole_ear.py --alignment_mode fixed_reference --reference_sample <tag>`：导出固定参考耳路径的 PLY、CSV、变换矩阵、QC 表与叠加图。
- `scripts/run_full_pipeline.py --reference-sample <tag>`：在正式批处理中保留 GPA-PCA，并额外运行固定参考耳-PCA。
- QC 表新增对齐方法与参考样本字段；批处理汇总分别记录两条 PCA 路径的状态和纳入数。

## 验证标准

- 已知旋转和平移的 landmark 可精确还原至参考 landmark。
- 固定参考耳路径的参考样本残差为零或数值精度范围内接近零。
- 旋转矩阵行列式接近 +1，网格边长误差接近零。
- 完整回归测试通过；无参考样本时现有 GPA 流程行为不变。
