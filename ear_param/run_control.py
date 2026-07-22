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
        while True:
            status = self._status()
            if status == "PAUSE_REQUESTED":
                self._write_status("PAUSED")
                continue
            if status == "PAUSED":
                time.sleep(self.poll_seconds)
                continue
            if status == "CANCEL_REQUESTED":
                raise RunCancelled("run cancelled by desktop controller")
            return

    def _write_status(self, status: str) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps({"status": status}), encoding="utf-8")
        for _ in range(20):
            try:
                temporary.replace(self.path)
                return
            except PermissionError:
                time.sleep(self.poll_seconds)
        temporary.replace(self.path)

    def _status(self) -> str:
        if not self.path.exists():
            return "RUNNING"
        while True:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                break
            except (FileNotFoundError, PermissionError, json.JSONDecodeError):
                time.sleep(self.poll_seconds)
        status = str(payload.get("status", "RUNNING")).upper()
        if status not in {"RUNNING", "PAUSE_REQUESTED", "PAUSED", "CANCEL_REQUESTED"}:
            raise ValueError(f"invalid run-control status: {status}")
        return status
