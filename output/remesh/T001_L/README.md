# T001_R Remesh 输出文件清单

使用 `ear_param/remesh.py` 的 `build_region_remesh()` 生成。

## 1. Snapped Landmarks
| 文件 | 字段 | 说明 |
|------|------|------|
| `snapped_landmarks.csv` | `landmark_id`, `orig_x/y/z`, `snap_x/y/z`, `vertex_id`, `distance_mm` | 原始 landmark 坐标、吸附到 mesh 最近顶点的坐标、vertex ID 及吸附距离 |

## 2. Boundary Paths（阶段 4：构建三条边界路径）
| 文件 | 字段 | 说明 |
|------|------|------|
| `boundary_path_AB.csv` | `vertex_id` | Landmark A → B 的最短路径（vertex ID 序列） |
| `boundary_path_BC.csv` | `vertex_id` | Landmark B → C 的最短路径（vertex ID 序列） |
| `boundary_path_CA.csv` | `vertex_id` | Landmark C → A 的最短路径（vertex ID 序列） |
| `boundary_edges.csv` | `edge` | 三条路径合并后的所有边界边，格式 `u-v` |

## 3. Patch Extraction（阶段 5：剪出面片）
| 文件 | 字段 | 说明 |
|------|------|------|
| `patch_face_ids.csv` | `global_face_id` | 切出的 patch 在原始 mesh 中的全局 face ID |
| `patch_local_faces.csv` | `v0`, `v1`, `v2` | 局部顶点索引构成的面片 |
| `patch_local_vertices.csv` | `x`, `y`, `z` | 局部坐标系的 3D 顶点坐标 |
| `patch_local_to_global.csv` | `local_id`, `global_vertex_id` | 局部→全局 vertex ID 映射表 |

## 4. Parameterization（阶段 6：协同参数化）
| 文件 | 字段 | 说明 |
|------|------|------|
| `parameterization_uv.csv` | `u`, `v`, `local_vertex_id` | 所有 patch 顶点的 UV 坐标 |
| `parameterization_original_face_ids.csv` | `global_face_id` | 参数化时使用的全局 face ID |

## 5. subdivision（阶段 7：细分生成固定模板）
| 文件 | 字段 | 说明 |
|------|------|------|
| `template_barycentric.csv` | `lambda1`, `lambda2`, `lambda3` | 45 个模板点在父三角形中的重心坐标 |
| `template_uv.csv` | `u`, `v` | 45 个模板点的 UV 坐标 |
| `template_faces.csv` | `v0`, `v1`, `v2` | 64 个模板三角面，跨样本完全一致 |

## 6. Located Samples（阶段 8：UV 定位 + 3D 反推）
| 文件 | 字段 | 说明 |
|------|------|------|
| `located_sample_uv.csv` | `u`, `v` | 45 个采样点在 source patch 上的 UV 坐标 |
| `located_face_indices.csv` | `face_index` | 每个采样点所在的 source face 索引 |
| `located_barycentric.csv` | `lambda1`, `lambda2`, `lambda3` | 每个采样点在 source face 内的重心坐标 |
| `located_unmapped_mask.csv` | `unmapped` | 0 = 映射成功，1 = 未映射 |

## 7. 3D Result
| 文件 | 字段 | 说明 |
|------|------|------|
| `sample_points_3d.csv` | `point_id`, `x`, `y`, `z` | 45 个模板点映射回 3D 后的空间坐标 |

## 8. Summary
| 文件 | 字段 | 说明 |
|------|------|------|
| `summary.json` | — | 完整 QC 摘要（patch_faces, unmapped, flipped, degenerate, boundary 长度, snap 距离等） |