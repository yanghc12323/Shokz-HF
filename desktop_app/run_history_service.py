"""Read-only discovery of persisted desktop attempts for one project."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from desktop_app.models import AttemptRecord, ProjectRecord, RunStatus


@dataclass(frozen=True)
class RunHistoryEntry:
    attempt: AttemptRecord
    failure_reason: str


class RunHistoryService:
    """Rebuild attempt records from desktop state without mutating a project."""

    def list_attempts(self, project: ProjectRecord) -> list[RunHistoryEntry]:
        attempts_root = project.root / "runs"
        if not attempts_root.is_dir():
            return []
        entries: list[RunHistoryEntry] = []
        for state_path in attempts_root.glob("*/attempts/*/desktop_state.json"):
            entry = self._read_entry(project, state_path)
            if entry is not None:
                entries.append(entry)
        return sorted(
            entries,
            key=lambda entry: (entry.attempt.logical_run_id, entry.attempt.attempt_id),
            reverse=True,
        )

    @staticmethod
    def _read_entry(project: ProjectRecord, state_path: Path) -> RunHistoryEntry | None:
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            logical_run_id = str(payload["logical_run_id"])
            attempt_id = str(payload["attempt_id"])
            status = RunStatus(str(payload["status"]).upper())
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None
        attempt_root = state_path.parent
        if attempt_root.name != attempt_id or attempt_root.parent.parent.name != logical_run_id:
            return None
        parent_attempt_id = payload.get("parent_attempt_id")
        if parent_attempt_id is not None and not isinstance(parent_attempt_id, str):
            return None
        attempt = AttemptRecord(
            project_root=project.root,
            logical_run_id=logical_run_id,
            attempt_id=attempt_id,
            status=status,
            parent_attempt_id=parent_attempt_id,
        )
        return RunHistoryEntry(attempt, RunHistoryService._failure_reason(attempt))

    @staticmethod
    def _failure_reason(attempt: AttemptRecord) -> str:
        manifest_path = attempt.artifacts_dir / "manifest.json"
        if not manifest_path.is_file():
            return ""
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "无法读取运行清单"
        return str(payload.get("error", "")).strip()
