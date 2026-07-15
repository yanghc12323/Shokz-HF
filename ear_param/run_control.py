"""File-backed safe-checkpoint control for desktop pipeline runs."""

from __future__ import annotations

import json
from pathlib import Path
import time


class RunCancelled(RuntimeError):
    """Raised when the desktop controller asks a pipeline to cancel."""


class FileRunControl:
    """Read the desktop control file at declared pipeline safe checkpoints."""

    def __init__(self, path: Path, *, poll_seconds: float = 0.25) -> None:
        self.path = Path(path)
        self.poll_seconds = poll_seconds

    def checkpoint(self) -> None:
        """Block while paused and raise only for an explicit cancellation."""
        while self._status() == "PAUSE_REQUESTED":
            time.sleep(self.poll_seconds)
        if self._status() == "CANCEL_REQUESTED":
            raise RunCancelled("run cancelled by desktop controller")

    def _status(self) -> str:
        if not self.path.exists():
            return "RUNNING"
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        status = str(payload.get("status", "RUNNING")).upper()
        if status not in {"RUNNING", "PAUSE_REQUESTED", "CANCEL_REQUESTED"}:
            raise ValueError(f"invalid run-control status: {status}")
        return status
