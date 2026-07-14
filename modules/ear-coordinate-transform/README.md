# 耳模型刚体坐标对齐与 OBJ/STL 导出

该模块根据同名耳部标定点，用 Kabsch（rigid Procrustes）求取旋转矩阵 `R` 和平移向量 `t`，再对 moving mesh 的全部顶点应用：

```text
X_aligned = R @ X + t
```

算法不估计缩放，也不做非刚性变形。除左右耳镜像步骤会反转三角面顶点顺序外，刚体变换只改变顶点坐标，不改变网格拓扑。

默认建立适合 PCA 的统一标准坐标系：保持参考耳的方向不变，并将参考耳所选标定点（默认 `L7、L13、L15、L26`）的中心平移到 `(0,0,0)`。所有待对齐耳先通过 Kabsch 对齐到参考耳，再减去同一个参考中心。程序同时导出居中的参考模型和参考标定点，便于叠加检查或将参考耳纳入后续分析。

## 安装

```powershell
python -m pip install -r requirements.txt
```

CSV 文件使用你现有的 `landmark,x,y,z` 表头即可；旧的 `landmark_id` 表头也兼容：

```csv
landmark,x,y,z
L7,1.0,2.0,3.0
L13,4.0,5.0,6.0
```

CSV 可以包含 L2、L10、L17 等其他标定点。程序会读取整张表，再自动取出默认所需的 `L7、L13、L15、L26` 计算刚体变换；输出时会同步变换表中的全部标定点。表头不区分大小写，标定点名称也会统一为大写。

启用默认的自动镜像时，参考模型和待对齐模型的文件名必须含有独立的 `L` 或 `R` token，例如 `S001_L.stl`、`S002_R.obj`。如果两者方向不同，模块默认沿 X 轴镜像 moving mesh 和全部 moving landmarks，并修正 face winding。

## 文件选择窗口

安装依赖后，可以直接双击项目根目录下的 `启动耳模型对齐.bat`。也可以在终端运行：

```powershell
.\.venv\Scripts\python.exe -m ear_align
```

窗口只提供一个批量处理入口，依次选择：

- 参考耳 OBJ/STL/PLY
- 参考耳 landmarks CSV
- 本批次全部待处理 OBJ/STL/PLY（支持多选）
- 本批次全部 landmarks CSV（支持多选）
- 输出目录

点击“开始批量坐标变换”后，窗口会显示每个样本的状态、RMS 误差和输出路径。界面不再包含单个待对齐模型/CSV入口。

程序会在项目目录的 `.ear_align_settings.json` 中记住最近一次选择的参考模型、参考 CSV 和输出目录。下次启动窗口时会自动恢复，不需要重复选择参考模板。

## 批量坐标处理

在主窗口中：

1. 一次选择所有待处理的 OBJ/STL/PLY；
2. 一次选择所有对应的 landmarks CSV；
3. 查看窗口显示的可匹配、缺少 CSV 和多余 CSV 数量；
4. 点击唯一的“开始批量坐标变换”按钮。

程序按样本主文件名自动配对。例如：

```text
T068_L.stl  <->  T068_L_landmarks.csv
T069_R.obj  <->  T069_R_landmarks.csv
```

每个样本输出到独立子目录。单个样本缺少 CSV 或处理失败不会中断其他样本；输出根目录中的 `batch_summary.json` 会记录成功数、失败数、未匹配 CSV、每个样本的 RMS 误差和输出路径。居中的参考 OBJ/STL/CSV 只在输出根目录生成一次。

批量处理默认对每个样本使用同一个标准坐标系：先对齐到参考耳方向，再减去参考耳所选四点的中心。因此，即使参考模型原始坐标原点不在四点中心，所有批量输出仍会使用四点中心为 `(0,0,0)`。

“将参考标定点中心设为原点（PCA 标准坐标系）”默认开启。一般不建议关闭；只有需要与未经平移的原始参考模型直接叠加时才关闭。

## CLI

```powershell
python -m ear_align.cli `
  --ref-model data/S001_R.stl `
  --moving-model data/S002_L.stl `
  --ref-landmarks data/reference_landmarks.csv `
  --moving-landmarks data/moving_landmarks.csv `
  --out-obj output/moving_aligned.obj `
  --out-stl output/moving_aligned.stl
```

默认使用 `L7 L13 L15 L26`。可用 `--landmark-ids ID1 ID2 ID3 ...` 覆盖。若文件名没有 L/R token，或已在上游统一左右方向，可传 `--no-auto-mirror`。镜像轴可用 `--mirror-axis x|y|z` 设置。

如确实需要保留参考模型原始原点，可传 `--keep-reference-origin`；默认不传，即使用 PCA 标准坐标系。

输出 OBJ 所在目录会同时生成：

- `moving_landmarks_aligned.csv`
- `transform.json`：`R`、`t`、4×4 `matrix`、`det_R` 和镜像信息
- `metrics.json`：逐标定点、mean、RMS 和 max 对齐误差

也可通过 `--out-landmarks`、`--transform-json` 和 `--metrics-json` 指定路径。

## Python API

```python
from ear_align import align_and_export_mesh

result = align_and_export_mesh(
    ref_mesh_path="data/S001_R.stl",
    moving_mesh_path="data/S002_R.stl",
    ref_landmark_csv="data/reference_landmarks.csv",
    moving_landmark_csv="data/moving_landmarks.csv",
    output_obj_path="output/moving_aligned.obj",
    output_stl_path="output/moving_aligned.stl",
)

print(result.transform.matrix)
print(result.metrics["rms_error"])
```

## 测试

```powershell
python -m unittest discover -s tests -v
```

端到端测试会构造一个四面体，施加已知旋转和平移，执行完整导出，并重新读取 OBJ 验证顶点、faces、`det(R)` 和对齐误差。
