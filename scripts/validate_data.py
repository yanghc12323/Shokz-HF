#!/usr/bin/env python3
"""
输入数据校验脚本 — 耳 mesh + landmarks + 采样点 + QC 一致性检查

用法：
  python scripts/validate_data.py [--dry-run]

功能：
  1. 扫描 data/clean_mesh/*.ply 和 data/landmarks/*_landmarks.csv
  2. 校验每对 (mesh, landmarks) 的文件命名、完整性、基本几何一致性
  3. 扫描 output/parameterized_points/*_points.csv 和 output/qc/*_qc.csv
  4. 逐样本逐区域比对：采样点数、区域名、landmark ID 与 config/region_table.csv 是否一致
  5. 输出完整校验报告（控制台 + JSON）
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 项目根目录 & 路径常量
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
MESH_DIR = DATA_DIR / "clean_mesh"
LMS_DIR = DATA_DIR / "landmarks"

OUTPUT_DIR = PROJECT_ROOT / "output"
POINTS_DIR = OUTPUT_DIR / "parameterized_points"
QC_DIR = OUTPUT_DIR / "qc"

REGION_CSV = PROJECT_ROOT / "config" / "region_table.csv"

REQUIRED_LMS_IDS = {"L10", "L15", "L19", "L20", "L21", "L28", "L29", "L30", "L31"}

# 期望输出字段（只读校验，字段名需一一匹配文档）
EXPECTED_POINTS_COLS = [
    "sample_id", "side", "region_id", "region_name",
    "point_id_global", "point_id_region",
    "x", "y", "z", "u", "v",
    "lambda_a", "lambda_b", "lambda_c",
    "lm_a", "lm_b", "lm_c",
]

EXPECTED_QC_COLS = [
    "region_id", "region_name", "used_patch_file",
    "source_point_count", "source_face_count",
    "sample_point_count", "expected_point_count",
    "fallback_ratio", "interpolator", "status",
]


# ============================================================
# 1. 文件扫描 & 配对
# ============================================================

def _scan_files() -> Tuple[Dict[str, Path], Dict[str, Path]]:
    """
    扫描 data/clean_mesh 和 data/landmarks 目录。
    返回 {sample_key: mesh_path}, {sample_key: lms_path}
    sample_key 示例: "S001_R"
    """
    meshes: Dict[str, Path] = {}
    landmarks: Dict[str, Path] = {}

    if MESH_DIR.exists():
        for f in MESH_DIR.glob("*.ply"):
            key = f.stem  # e.g. "S001_R"
            meshes[key] = f

    if LMS_DIR.exists():
        for f in LMS_DIR.glob("*_landmarks.csv"):
            # 从文件名提取 sample_id_side，如 "S001_R_landmarks.csv" → "S001_R"
            stem = f.stem  # "S001_R_landmarks"
            if stem.endswith("_landmarks"):
                key = stem[:-10]  # 去掉末尾 "_landmarks"
                landmarks[key] = f
            else:
                # 也兼容没有后缀命名的 landmarks 文件
                key = stem
                landmarks[key] = f

    return meshes, landmarks


def _scan_outputs() -> Dict[str, Tuple[Optional[Path], Optional[Path]]]:
    """
    扫描 output/parameterized_points/*_points.csv 和 output/qc/*_qc.csv。
    返回 {sample_key: (points_csv_path, qc_csv_path)}
    """
    outputs: Dict[str, Tuple[Optional[Path], Optional[Path]]] = defaultdict(
        lambda: (None, None)
    )

    if POINTS_DIR.exists():
        for f in POINTS_DIR.glob("*_points.csv"):
            key = f.stem[:-7]  # 去掉末尾 "_points"
            prev = outputs[key]
            outputs[key] = (f, prev[1])

    if QC_DIR.exists():
        for f in QC_DIR.glob("*_qc.csv"):
            key = f.stem[:-3]  # 去掉末尾 "_qc"
            prev = outputs[key]
            outputs[key] = (prev[0], f)

    return dict(outputs)


# ============================================================
# 2. 单项校验函数
# ============================================================

def _validate_mesh_file(mesh_path: Path) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """校验 PLY 文件是否可读、是否有顶点/面片。"""
    try:
        import trimesh
        mesh = trimesh.load(str(mesh_path))
        if mesh is None:
            return False, "trimesh 返回 None", None
        info = {
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces) if mesh.faces is not None else 0,
            "is_watertight": bool(mesh.is_watertight),
        }
        return True, "OK", info
    except Exception as exc:
        return False, f"加载失败: {exc}", None


def _validate_landmarks_file(
    lms_path: Path,
) -> Tuple[bool, str, Optional[pd.DataFrame]]:
    """校验 landmarks CSV：必需列、无 NaN、坐标数值范围。"""
    try:
        # 使用 read_csv_robust 多编码兼容
        encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"]
        df = None
        for enc in encodings:
            try:
                df = pd.read_csv(lms_path, encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if df is None:
            return False, "无法解码 CSV（尝试了多种编码）", None

        # 列名规范化：去除前导/尾随空白
        df.columns = df.columns.str.strip()

        required = {"landmark_id", "x", "y", "z"}
        missing = required - set(df.columns)
        if missing:
            return False, f"缺少列: {missing}", None

        # 检查 landmark_id
        ids = set(df["landmark_id"].dropna().astype(str).str.strip())
        if not ids:
            return False, "无有效 landmark_id", None

        missing_ids = REQUIRED_LMS_IDS - ids
        if missing_ids:
            return False, f"缺少必需 landmark: {sorted(missing_ids)}", None

        # 检查坐标 NaN
        if df[["x", "y", "z"]].isnull().any().any():
            rows = df[df[["x", "y", "z"]].isnull().any(axis=1)]
            return False, f"坐标缺失 NaN 的行: {len(rows)}", df

        # 坐标范 围合理性（耳模型一般所有坐标在 ±200 mm 以内）
        for col in ["x", "y", "z"]:
            vals = df[col]
            if (vals < -500).any() or (vals > 500).any():
                return False, f"{col} 坐标超出 ±500 mm 范围", df

        return True, f"OK ({len(df)} landmarks)", df
    except Exception as exc:
        return False, f"校验异常: {exc}", None


def _validate_points_csv(csv_path: Path) -> Tuple[bool, str, Optional[pd.DataFrame]]:
    """校验采样点 CSV：列名、每区域点数、landmark ID 是否匹配 config 定义。"""
    try:
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()

        missing_cols = set(EXPECTED_POINTS_COLS) - set(df.columns)
        if missing_cols:
            return False, f"缺少列: {missing_cols}", None

        # 加载区域表做对比
        if not REGION_CSV.exists():
            return False, "config/region_table.csv 不存在", None

        regions_df = pd.read_csv(REGION_CSV)
        regions_df.columns = regions_df.columns.str.strip()

        issues = []

        # 按 region_id 分组，逐一校验
        for region_id, group in df.groupby("region_id"):
            region_cfg = regions_df[regions_df["region_id"] == region_id]
            if region_cfg.empty:
                issues.append(f"region_id={region_id} 不在 config 定义中")
                continue

            cfg = region_cfg.iloc[0]
            expected_r = int(cfg["resolution"])
            expected_n = (expected_r + 1) * (expected_r + 2) // 2

            if len(group) != expected_n:
                issues.append(
                    f"region_id={region_id} 点数 {len(group)} ≠ 期望 {expected_n}"
                )

            # 验证 lm_a, lm_b, lm_c 与 config 一致
            for col in ["lm_a", "lm_b", "lm_c"]:
                vals = group[col].unique()
                if len(vals) != 1 or vals[0] != cfg[col]:
                    issues.append(
                        f"region_id={region_id} {col}={vals} ≠ config {cfg[col]}"
                    )

        if issues:
            return False, "; ".join(issues), df
        return True, f"OK ({len(df)} 行)", df
    except Exception as exc:
        return False, f"读取异常: {exc}", None


def _validate_qc_csv(
    qc_path: Path, points_df: Optional[pd.DataFrame] = None
) -> Tuple[bool, str, Optional[pd.DataFrame]]:
    """校验 QC 报告 CSV：列、点数与采样点 CSV 一致。"""
    try:
        df = pd.read_csv(qc_path)
        df.columns = df.columns.str.strip()

        missing_cols = set(EXPECTED_QC_COLS) - set(df.columns)
        if missing_cols:
            return False, f"缺少列: {missing_cols}", None

        issues = []

        # 交叉验证
        if points_df is not None:
            for _, row in df.iterrows():
                rid = row["region_id"]
                spc = int(row["sample_point_count"])
                epc = int(row["expected_point_count"])
                if spc != epc:
                    issues.append(f"region_id={rid} sample_point_count={spc} ≠ expected={epc}")

                pts_count = len(points_df[points_df["region_id"] == rid]) if "region_id" in points_df.columns else -1
                if pts_count >= 0 and pts_count != spc:
                    issues.append(
                        f"region_id={rid} QC 记录 {spc} 点 ≠ 实际 CSV 中 {pts_count} 点"
                    )

            statuses = df["status"].unique()
            for st in statuses:
                if st not in ("PASS", "WARNING", "FAIL"):
                    issues.append(f"非法 QC status: {st}")

        if issues:
            return False, "; ".join(issues), df
        return True, f"OK ({len(df)} 行)", df
    except Exception as exc:
        return False, f"读取异常: {exc}", None


def _validate_consistency(meshes, landmarks, outputs) -> List[str]:
    """跨数据源一致性校验。"""
    issues = []

    mesh_keys = set(meshes.keys())
    lms_keys = set(landmarks.keys())
    out_keys = set(outputs.keys())

    # 无 mesh 但有 landmarks
    orphan_lms = lms_keys - mesh_keys
    if orphan_lms:
        issues.append(f"孤立 landmarks（无对应 mesh）: {sorted(orphan_lms)}")

    # 无 landmarks 但有 mesh
    orphan_mesh = mesh_keys - lms_keys
    if orphan_mesh:
        issues.append(f"孤立 mesh（无对应 landmarks）: {sorted(orphan_mesh)}")

    # 有 mesh+landmarks 但无输出
    paired = mesh_keys & lms_keys
    no_output = paired - out_keys
    if no_output:
        issues.append(f"有输入但无输出: {sorted(no_output)}")

    # 有输出但无输入
    extra_output = out_keys - paired
    if extra_output:
        issues.append(f"有输出但无对应输入: {sorted(extra_output)}")

    return issues


# ============================================================
# 3. 主流程
# ============================================================

def validate_all(dry_run: bool = False) -> int:
    """
    执行全部校验，打印报告，返回 exit code（0=全部通过，1=有失败）。
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"=" * 70)
    print(f"  3D 耳模型数据校验  {ts}")
    print(f"  项目根: {PROJECT_ROOT}")
    print(f"=" * 70)

    report: Dict[str, Any] = {
        "timestamp": ts,
        "dry_run": dry_run,
        "sections": {},
    }

    # ----------------------------------------------------------
    # 第 1 部分：扫描 & 配对
    # ----------------------------------------------------------
    meshes, landmarks = _scan_files()
    outputs = _scan_outputs()

    print(f"\n[1] 文件扫描")
    print(f"    Mesh 文件数:     {len(meshes)}")
    print(f"    Landmarks 文件数: {len(landmarks)}")
    print(f"    输出文件组:       {len(outputs)}")

    report["sections"]["scan"] = {
        "mesh_count": len(meshes),
        "landmarks_count": len(landmarks),
        "output_groups": len(outputs),
    }

    all_pass = True
    sample_results: Dict[str, List[dict]] = defaultdict(list)

    # ----------------------------------------------------------
    # 第 2 部分：逐样本校验输入
    # ----------------------------------------------------------
    print(f"\n[2] 输入数据校验")
    paired_keys = sorted(set(meshes.keys()) | set(landmarks.keys()))

    if not paired_keys:
        print("    ⚠ 未找到任何数据文件")
        report["sections"]["inputs"] = {"note": "无数据文件"}
    else:
        for key in paired_keys:
            mesh_ok, mesh_msg, mesh_info = (True, "", {})  # defaults
            lms_ok, lms_msg, _lms_df = (True, "", None)

            if key in meshes:
                mesh_ok, mesh_msg, mesh_info = _validate_mesh_file(meshes[key])
            else:
                mesh_ok, mesh_msg, mesh_info = (
                    False,
                    "缺少 mesh 文件",
                    None,
                )

            if key in landmarks:
                lms_ok, lms_msg, _lms_df = _validate_landmarks_file(landmarks[key])
            else:
                lms_ok, lms_msg = False, "缺少 landmarks 文件"

            status = "✓" if (mesh_ok and lms_ok) else "✗"
            print(f"    {status} {key}: mesh={mesh_msg}; lms={lms_msg}")

            if not mesh_ok or not lms_ok:
                all_pass = False

            sample_results[key].append(
                {
                    "type": "input",
                    "mesh_ok": mesh_ok,
                    "mesh_msg": mesh_msg,
                    "mesh_info": mesh_info,
                    "lms_ok": lms_ok,
                    "lms_msg": lms_msg,
                }
            )

        report["sections"]["inputs"] = dict(sample_results)

    # ----------------------------------------------------------
    # 第 3 部分：逐样本校验输出
    # ----------------------------------------------------------
    print(f"\n[3] 输出数据校验")
    if not outputs:
        print("    ⚠ 未找到输出文件")
        report["sections"]["outputs"] = {"note": "无输出文件"}
    else:
        for key in sorted(outputs.keys()):
            pts_path, qc_path = outputs[key]
            pts_ok, pts_msg, pts_df = (
                _validate_points_csv(pts_path) if pts_path else (True, "无文件", None)
            )
            qc_ok, qc_msg, _qc_df = (
                _validate_qc_csv(qc_path, pts_df) if qc_path else (True, "无文件", None)
            )

            status = "✓" if (pts_ok and qc_ok) else "✗"
            print(f"    {status} {key}: points={pts_msg}; qc={qc_msg}")

            if not pts_ok or not qc_ok:
                all_pass = False

            sample_results[key].append(
                {
                    "type": "output",
                    "points_ok": pts_ok,
                    "points_msg": pts_msg,
                    "qc_ok": qc_ok,
                    "qc_msg": qc_msg,
                }
            )

        report["sections"]["outputs"] = {
            k: [r for r in v if r["type"] == "output"]
            for k, v in sample_results.items()
        }

    # ----------------------------------------------------------
    # 第 4 部分：跨数据一致性
    # ----------------------------------------------------------
    print(f"\n[4] 跨数据一致性")
    consistency_issues = _validate_consistency(meshes, landmarks, outputs)
    if consistency_issues:
        for issue in consistency_issues:
            print(f"    ✗ {issue}")
        all_pass = False
    else:
        print("    ✓ 一致")

    report["sections"]["consistency"] = {
        "passed": len(consistency_issues) == 0,
        "issues": consistency_issues,
    }

    # ----------------------------------------------------------
    # 第 5 部分：汇总
    # ----------------------------------------------------------
    print(f"\n{'=' * 70}")
    print(f"  校验结果: {'全部通过 ✓' if all_pass else '存在问题 ✗'}")
    print(f"{'=' * 70}")

    report["all_pass"] = all_pass

    # 保存 JSON 报告
    report_path = OUTPUT_DIR / "logs" / f"validate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    # 将不可序列化对象转为字符串
    json_report = json.dumps(report, indent=2, default=str, ensure_ascii=False)
    report_path.write_text(json_report, encoding="utf-8")
    print(f"\n  综合报告已保存: {report_path}")

    return 0 if all_pass else 1


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="3D 耳模型输入/输出数据完整性校验",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅扫描文件，不执行校验",
    )
    args = parser.parse_args()

    if args.dry_run:
        meshes, landmarks = _scan_files()
        outputs = _scan_outputs()
        print("=== Mesh 文件 ===")
        for k, v in sorted(meshes.items()):
            print(f"  {k}: {v}")
        print(f"\n=== Landmarks 文件 ===")
        for k, v in sorted(landmarks.items()):
            print(f"  {k}: {v}")
        print(f"\n=== 输出文件 ===")
        for k, (pts, qc) in sorted(outputs.items()):
            print(f"  {k}: points={pts}  qc={qc}")
        return 0

    exit_code = validate_all()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()