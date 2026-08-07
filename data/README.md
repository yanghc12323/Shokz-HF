# 本地输入数据目录

本目录用于存放真实分析输入，但真实 PLY 网格与 landmark CSV 不纳入 Git。

推荐结构：

~~~
data/
  clean_mesh/
    MQ_S001L.ply
    MQ_S001R.ply
  landmarks/
    T001_L_landmarks.csv
    T001_R_landmarks.csv
~~~

网格样本名采用 MQ_S###L 或 MQ_S###R；对应 landmark 文件采用 T###_L_landmarks.csv 或 T###_R_landmarks.csv。完整配对规则、35 个 landmark 要求及全流程命令见项目根目录 README。
