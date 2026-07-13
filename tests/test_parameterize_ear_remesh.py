from pathlib import Path
from uuid import uuid4

import pandas as pd

from scripts.parameterize_ear_remesh import build_sample_status_summary


def test_build_sample_status_summary_counts_each_sample():
    work_dir = Path(".test_artifacts") / "unit_summary" / uuid4().hex
    work_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame({
        "sample_id": ["T001", "T001", "T001"],
        "side": ["L", "L", "L"],
        "status": ["PASS", "WARNING", "FAIL"],
    }).to_csv(work_dir / "T001_L_remesh_qc.csv", index=False)
    pd.DataFrame({
        "sample_id": ["T002", "T002", "T002", "T002"],
        "side": ["L", "L", "L", "L"],
        "status": ["PASS", "PASS", "PASS", "WARNING"],
    }).to_csv(work_dir / "T002_L_remesh_qc.csv", index=False)

    summary = build_sample_status_summary(work_dir)

    assert summary.to_dict("records") == [
        {
            "sample_tag": "T001_L",
            "PASS": 1,
            "WARNING": 1,
            "FAIL": 1,
            "TOTAL": 3,
        },
        {
            "sample_tag": "T002_L",
            "PASS": 3,
            "WARNING": 1,
            "FAIL": 0,
            "TOTAL": 4,
        },
    ]
