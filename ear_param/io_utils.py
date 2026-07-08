#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
io_utils.py 鈥?鏂囦欢 I/O 涓庢棩蹇楀伐鍏?
==================================

鎻愪緵缁熶竴鐨勬枃浠跺姞杞姐€佷繚瀛樺拰鏃ュ織閰嶇疆鎺ュ彛銆?

鍖呭惈:
  - read_csv_robust: 澶氱紪鐮佸吋瀹圭殑 CSV 璇诲彇
  - load_mesh:       閫氱敤 mesh 鍔犺浇 (ply/obj/stl)
  - load_landmarks:  鐗瑰緛鐐?CSV 鍔犺浇涓庢牎楠?
  - get_landmark:    浠?DataFrame 鎻愬彇鍗曚釜鐗瑰緛鐐瑰潗鏍?
  - save_mesh_ply:   淇濆瓨 mesh 涓?PLY
  - save_landmarks_csv: 淇濆瓨鐗瑰緛鐐?CSV
  - setup_logging:   閰嶇疆鍙岃緭鍑烘棩蹇?(鎺у埗鍙?+ 鏂囦欢)
"""

import logging
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import trimesh


# ============================================================================
# 鏃ュ織閰嶇疆
# ============================================================================

def setup_logging(
    sample_id: str,
    side: str,
    log_dir: Path,
) -> logging.Logger:
    """
    閰嶇疆鏃ュ織: 鍚屾椂杈撳嚭鍒版帶鍒跺彴鍜屾枃浠?

    - 鏂囦欢 handler 浣跨敤 DEBUG 绾у埆, 璁板綍璇︾粏璋冭瘯淇℃伅
    - 鎺у埗鍙?handler 浣跨敤 INFO 绾у埆, 閬垮厤鍒峰睆

    Parameters
    ----------
    sample_id : str
        鏍锋湰缂栧彿, 濡?'S001', 鎴?'SIMULATION' 鐢ㄤ簬鎵归噺妯″紡.
    side : str
        宸﹀彸渚? 'R' 鎴?'L', 鎴?'ALL' 鐢ㄤ簬鎵归噺妯″紡.
    log_dir : Path
        鏃ュ織杈撳嚭鐩綍.

    Returns
    -------
    logging.Logger
        閰嶇疆濂界殑 logger 瀹炰緥, 鏍煎紡涓?
        "YYYY-MM-DD HH:MM:SS | LEVEL    | message"
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{sample_id}_{side}_parameterize_{timestamp}.log"

    logger = logging.getLogger(f"parameterize_{sample_id}_{side}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()  # 闃叉閲嶅娣诲姞 handler

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 鏂囦欢 handler (DEBUG 绾у埆)
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 鎺у埗鍙?handler (INFO 绾у埆)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


# ============================================================================
# CSV 璇诲彇
# ============================================================================

def read_csv_robust(
    filepath: Path,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """
    浠?UTF-8 浼樺厛銆佸缂栫爜鍏滃簳鐨勬柟寮忚鍙?CSV 鏂囦欢.

    鑷姩灏濊瘯浠ヤ笅缂栫爜椤哄簭:
      utf-8 鈫?utf-8-sig 鈫?gbk 鈫?gb2312 鈫?latin-1

    Parameters
    ----------
    filepath : Path
        CSV 鏂囦欢璺緞.
    logger : logging.Logger | None
        鏃ュ織璁板綍鍣? 鍙€?

    Returns
    -------
    pd.DataFrame
        璇诲彇鐨勬暟鎹〃.

    Raises
    ------
    ValueError
        鎵€鏈夌紪鐮佸皾璇曞潎澶辫触鏃舵姏鍑?
    """
    encodings = ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin-1']
    for enc in encodings:
        try:
            df = pd.read_csv(str(filepath), encoding=enc)
            if logger:
                logger.debug(f"璇诲彇 CSV: {filepath} (encoding={enc})")
            return df
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"鏃犳硶瑙ｇ爜 CSV 鏂囦欢: {filepath}")


# ============================================================================
# Mesh 鍔犺浇涓庝繚瀛?
# ============================================================================

def load_mesh(
    mesh_path: str | Path,
    logger: logging.Logger | None = None,
) -> trimesh.Trimesh:
    """
    鍔犺浇 mesh 鏂囦欢 (.ply, .obj, .stl).

    鑷姩澶勭悊 Scene 绫诲瀷 (鎻愬彇鎵€鏈夊嚑浣曚綋鍚堝苟).

    Parameters
    ----------
    mesh_path : str | Path
        Mesh 鏂囦欢璺緞.
    logger : logging.Logger | None
        鏃ュ織璁板綍鍣? 鍙€?

    Returns
    -------
    trimesh.Trimesh
        鍔犺浇鐨勭嫭绔?mesh 瀵硅薄.

    Raises
    ------
    FileNotFoundError
        鏂囦欢涓嶅瓨鍦?
    ValueError
        鏃犳硶鍔犺浇涓?Trimesh 鎴?mesh 涓虹┖.
    """
    mesh_path = Path(mesh_path)
    if not mesh_path.exists():
        raise FileNotFoundError(f"Mesh 鏂囦欢涓嶅瓨鍦? {mesh_path}")

    if logger:
        logger.debug(f"鍔犺浇 mesh: {mesh_path}")

    mesh = trimesh.load(str(mesh_path), process=False)

    # 澶勭悊 Scene 绫诲瀷
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))

    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"鏃犳硶灏嗘枃浠跺姞杞戒负 Trimesh: {mesh_path}")

    n_verts = mesh.vertices.shape[0]
    n_faces = len(mesh.faces) if mesh.faces is not None else 0
    if n_verts == 0:
        raise ValueError(f"绌?mesh: {mesh_path}")

    if logger:
        logger.debug(f"  -> 椤剁偣鏁?{n_verts}, 闈㈡暟={n_faces}")

    return mesh


def save_mesh_ply(
    vertices: np.ndarray,
    faces: np.ndarray,
    filepath: Path,
) -> None:
    """
    淇濆瓨 mesh 涓?PLY 鏂囦欢.

    Parameters
    ----------
    vertices : np.ndarray, shape (N, 3)
        缃戞牸椤剁偣鍧愭爣.
    faces : np.ndarray, shape (M, 3)
        涓夎闈㈢墖绱㈠紩.
    filepath : Path
        杈撳嚭鏂囦欢璺緞.
    """
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.export(str(filepath))


# ============================================================================
# Landmarks 鍔犺浇涓庝繚瀛?
# ============================================================================

def load_landmarks(
    csv_path: str | Path,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """
    鍔犺浇鐗瑰緛鐐?CSV 鏂囦欢.

    瑕佹眰鑷冲皯鍖呭惈浠ヤ笅鍒? landmark_id, x, y, z.
    浠?landmark_id 浣滀负 DataFrame 绱㈠紩.

    Parameters
    ----------
    csv_path : str | Path
        CSV 鏂囦欢璺緞.
    logger : logging.Logger | None
        鏃ュ織璁板綍鍣? 鍙€?

    Returns
    -------
    pd.DataFrame
        浠?landmark_id 涓虹储寮曠殑鐗瑰緛鐐?DataFrame.

    Raises
    ------
    FileNotFoundError
        鏂囦欢涓嶅瓨鍦?
    ValueError
        缂哄皯蹇呰鍒?
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"鐗瑰緛鐐规枃浠朵笉瀛樺湪: {csv_path}")

    if logger:
        logger.debug(f"鍔犺浇鐗瑰緛鐐? {csv_path}")

    df = read_csv_robust(csv_path, logger)

    required = {"landmark_id", "x", "y", "z"}
    missing = required - set(df.columns)
    if missing:
        if len(df.columns) == 4:
            for enc in ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin-1']:
                try:
                    df = pd.read_csv(
                        str(csv_path),
                        encoding=enc,
                        header=None,
                        names=["landmark_id", "x", "y", "z"],
                    )
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue
            else:
                raise ValueError(f"Cannot decode CSV file: {csv_path}")
        else:
            raise ValueError(f"Landmark file is missing columns: {missing}, actual columns: {list(df.columns)}")

    df["landmark_id"] = df["landmark_id"].astype(str)
    df = df.set_index("landmark_id")

    if logger:
        logger.debug(f"  -> 鍔犺浇浜?{len(df)} 涓壒寰佺偣")

    return df


def get_landmark(
    lms: pd.DataFrame,
    lm_id: str,
    logger: logging.Logger | None = None,
) -> np.ndarray:
    """
    浠庣壒寰佺偣 DataFrame 涓彁鍙栨寚瀹?landmark 鐨?(x, y, z) 鍧愭爣.

    Parameters
    ----------
    lms : pd.DataFrame
        浠?landmark_id 涓虹储寮曠殑鐗瑰緛鐐硅〃.
    lm_id : str
        鐗瑰緛鐐圭紪鍙? 濡?'L10'.
    logger : logging.Logger | None
        鏃ュ織璁板綍鍣? 鍙€?

    Returns
    -------
    np.ndarray, shape (3,)
        鐗瑰緛鐐圭殑涓夌淮鍧愭爣鏁扮粍 [x, y, z].

    Raises
    ------
    KeyError
        鎸囧畾鐨?landmark 涓嶅瓨鍦?
    """
    if lm_id not in lms.index:
        msg = f"缂哄皯鐗瑰緛鐐? {lm_id}"
        if logger:
            logger.error(msg)
        raise KeyError(msg)
    return lms.loc[lm_id, ["x", "y", "z"]].to_numpy(dtype=float)


def save_landmarks_csv(
    landmark_coords: dict[str, tuple[float, float, float]],
    filepath: Path,
    sample_id: str,
    landmark_ids: list[str] | None = None,
    annotator: str = "simulated",
) -> None:
    """
    淇濆瓨鐗瑰緛鐐逛负 CSV 鏂囦欢.

    Parameters
    ----------
    landmark_coords : dict
        {landmark_id: (x, y, z)} 鍧愭爣瀛楀吀.
    filepath : Path
        杈撳嚭鏂囦欢璺緞.
    sample_id : str
        鏍锋湰缂栧彿 (浠呯敤浜庢敞閲? 涓嶅奖鍝嶈緭鍑哄唴瀹?.
    landmark_ids : list[str] | None
        瑕佽緭鍑虹殑 landmark 缂栧彿鍒楄〃. 涓?None 鏃惰緭鍑哄叏閮?
    annotator : str
        鏍囨敞鑰呮爣璇?
    """
    ids = landmark_ids if landmark_ids is not None else list(landmark_coords.keys())
    records = []
    for lm_id in ids:
        x, y, z = landmark_coords[lm_id]
        records.append({
            "landmark_id": lm_id,
            "x": round(x, 4),
            "y": round(y, 4),
            "z": round(z, 4),
            "confidence": 1.0,
            "annotator": annotator,
            "comment": "",
        })
    df = pd.DataFrame(records)
    df.to_csv(str(filepath), index=False)
