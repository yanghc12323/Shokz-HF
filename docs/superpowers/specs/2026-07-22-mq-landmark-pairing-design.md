# MQ 模型与 Landmark 配对兼容设计

## 目标

让分析流程直接读取模型侧命名为 `MQ_S###L/R.ply`、landmark 侧命名为
`T###_L/R_landmarks.csv` 的新版输入；不修改模型、landmark 或 region table
的原始文件。

## 已确认的数据契约

- 模型样本标签：`MQ_S001L`，文件为 `MQ_S001L.ply`。
- 对应 landmark：`T001_L_landmarks.csv`。
- 映射：`MQ_S(三位数字)(L|R)` → `T(同一三位数字)_(同一侧)_landmarks.csv`。
- 当前目录中 130 个模型和 130 个 landmark 可按该规则一一配对；每个 landmark
  文件包含新 region table 所需的 35 个点位。

## 方案比较

1. 批量重命名 landmark 为 MQ 格式：改动少，但破坏上游数据命名，不采用。
2. 在各脚本中分别做字符串替换：短期可用，但规则重复、容易产生不一致，不采用。
3. 在 `ear_param.pipeline` 中提供集中解析器，并让所有需要模型/landmark 路径或
   左右耳信息的调用点使用它：改动集中、可测试、保留原始文件名，采用。

## 设计

新增一个只读样本输入解析接口，负责：

- 发现 legacy 同名对：`T001_L.ply` + `T001_L_landmarks.csv`；
- 发现 MQ 对：`MQ_S001L.ply` + `T001_L_landmarks.csv`；
- 以模型文件主体作为 `sample_tag`，使输出、事件和桌面界面显示 `MQ_S001L`；
- 为每对返回实际的模型路径、landmark 路径、样本编号与耳侧；
- 对缺失配对维持现有 `MISSING_MESH` / `MISSING_LANDMARKS` 语义。

下游阶段只使用解析出的实际路径。新命名下，canonical 输出仍使用
`MQ_S001L.ply` / `MQ_S001L_landmarks.csv`，因此后续 Remesh、整耳、配准和 PCA
的现有文件契约无需改变。

## 范围

- 修改：样本发现、canonicalization 侧别解析、pipeline 子进程参数、manifest、QC
  直接脚本、桌面导入校验。
- 修改：与上述命名契约相关的 CLI / UI 示例文字和测试。
- 不修改：Remesh、修复、整耳、刚性配准与 PCA 的几何算法；原始数据文件。

## 错误处理与验收

- 新版 130 对必须全部显示为 `READY`。
- 每个 `MQ` 样本的实际 landmark 路径必须指向对应 `T` 文件。
- 缺失或不合规文件仍需产生可读的校验错误。
- 旧 `T001_L` 同名输入仍须通过现有测试，防止历史 CLI 流程回归。
