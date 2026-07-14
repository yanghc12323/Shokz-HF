"""Persistent project-local settings for the desktop interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parent.parent / ".ear_align_settings.json"


def load_settings(path: str | Path = DEFAULT_SETTINGS_PATH) -> dict[str, Any]:
    settings_path = Path(path)
    if not settings_path.is_file():
        return {}
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(data: dict[str, Any], path: str | Path = DEFAULT_SETTINGS_PATH) -> None:
    settings_path = Path(path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = settings_path.with_suffix(settings_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(settings_path)


def save_reference_template(
    reference_model: str,
    reference_csv: str,
    output_directory: str = "",
    path: str | Path = DEFAULT_SETTINGS_PATH,
) -> None:
    current = load_settings(path)
    current.update(
        {
            "reference_model": reference_model,
            "reference_csv": reference_csv,
            "output_directory": output_directory,
        }
    )
    save_settings(current, path)

