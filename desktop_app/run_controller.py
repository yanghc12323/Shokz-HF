"""One-process desktop control for isolated pipeline attempts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Callable

from PySide6.QtCore import QObject, QProcess, Signal

from desktop_app.models import AttemptRecord, ProjectRecord, RunOptions, RunStatus
from desktop_app.recovery_service import RecoveryOption, RecoveryService


class RunController(QObject):
    """Start one project-scoped CLI process and persist desktop control state."""

    attempt_changed = Signal(object)
    event_received = Signal(object)
    run_finished = Signal(object)

    def __init__(self, *, process_factory: Callable[[], object] = QProcess) -> None:
        super().__init__()
        self._process_factory = process_factory
        self.process: object | None = None
        self.active_attempt: AttemptRecord | None = None
        self.last_command: list[str] = []
        self._event_offset = 0
        self._event_remainder = b""
        self._recovery_option: RecoveryOption | None = None

    @property
    def supports_process_control(self) -> bool:
        """Recovery scripts have no safe pause/cancel checkpoint protocol."""
        return self._recovery_option is None

    @property
    def control_path(self) -> Path:
        return self._require_attempt().root / "control.json"

    @property
    def event_path(self) -> Path:
        return self._require_attempt().root / "events.jsonl"

    def start(self, project: ProjectRecord, options: RunOptions) -> AttemptRecord:
        if self.process is not None:
            raise RuntimeError("another local run is already active")
        logical_run_id = datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S-%f")
        attempt = AttemptRecord.create(project.root, logical_run_id, "attempt-001")
        attempt.root.mkdir(parents=True, exist_ok=False)
        running = replace(attempt, status=RunStatus.RUNNING)
        self._write_json(self.control_path_for(running), {"status": "RUNNING"})
        self._write_state(running)

        script = Path(__file__).resolve().parents[1] / "scripts" / "run_full_pipeline.py"
        arguments = [
            str(script),
            "--mesh_dir", str(project.mesh_dir),
            "--landmarks_dir", str(project.landmarks_dir),
            "--regions", str(project.region_table_path),
            "--output-root", str(running.artifacts_dir),
            "--event-log", str(running.root / "events.jsonl"),
            "--control-path", str(running.root / "control.json"),
            "--max-salvage-unmapped-ratio", str(options.max_salvage_unmapped_ratio),
            "--max-salvage-degenerate-ratio", str(options.max_salvage_degenerate_ratio),
            "--pca-variance-threshold", str(options.pca_variance_threshold),
            "--qc-figure-mode", options.qc_figure_mode,
            "--alignment-mode", options.alignment_mode,
            "--parallel-workers", str(options.parallel_workers),
        ]
        if options.sample_tags:
            arguments.extend(["--samples", *options.sample_tags])
        if options.skip_remesh_qc:
            arguments.append("--skip-remesh-qc")
        if options.reference_sample:
            arguments.extend(["--reference-sample", options.reference_sample])

        process = self._process_factory()
        process.setProgram(sys.executable)
        process.setArguments(arguments)
        process.setWorkingDirectory(str(project.root))
        finished_signal = getattr(process, "finished", None)
        if finished_signal is not None:
            finished_signal.connect(lambda *_: self.refresh_terminal_status())
        process.start()
        self.process = process
        self.active_attempt = running
        self.last_command = [sys.executable, *arguments]
        self.attempt_changed.emit(running)
        return running

    def start_recovery(
        self,
        project: ProjectRecord,
        parent: AttemptRecord,
        option: RecoveryOption,
    ) -> AttemptRecord:
        if self.process is not None:
            raise RuntimeError("another local run is already active")
        service = RecoveryService()
        child = service.create_attempt(parent, option)
        arguments = service.build_command(project, parent, child, option)
        running = replace(child, status=RunStatus.RUNNING)
        self._write_state(running)
        process = self._process_factory()
        process.setProgram(sys.executable)
        process.setArguments(arguments)
        process.setWorkingDirectory(str(project.root))
        finished_signal = getattr(process, "finished", None)
        if finished_signal is not None:
            finished_signal.connect(lambda exit_code, *_: self._finish_recovery(exit_code))
        process.start()
        self.process = process
        self.active_attempt = running
        self._recovery_option = option
        self.last_command = [sys.executable, *arguments]
        self.attempt_changed.emit(running)
        return running

    def _finish_recovery(self, exit_code: int) -> None:
        attempt = self._require_attempt()
        status = RunStatus.COMPLETED if exit_code == 0 else RunStatus.FAILED
        attempt.artifacts_dir.mkdir(parents=True, exist_ok=True)
        recovery = json.loads((attempt.root / "recovery.json").read_text(encoding="utf-8"))
        self._write_json(
            attempt.artifacts_dir / "manifest.json",
            {
                "status": "COMPLETED" if status is RunStatus.COMPLETED else "ERROR",
                "output_scope": "isolated",
                "outputs": self._recovery_outputs(attempt),
                "recovery": recovery,
                "error": "" if status is RunStatus.COMPLETED else f"recovery process exited with {exit_code}",
            },
        )
        updated = replace(attempt, status=status)
        self.active_attempt = updated
        self._write_state(updated)
        self.attempt_changed.emit(updated)
        self.run_finished.emit(updated)
        self.process = None
        self._recovery_option = None

    def _recovery_outputs(self, attempt: AttemptRecord) -> dict[str, str]:
        option = self._recovery_option
        if option is RecoveryOption.WELD:
            return {"weld_dir": "whole_ear_r24/weld_repaired"}
        if option is RecoveryOption.ALIGNMENT:
            return {"aligned_dir": "whole_ear_r24/aligned_gpa"}
        if option is RecoveryOption.PCA:
            return {"pca_dir": "pca_gpa_r24"}
        return {}

    def request_pause(self) -> AttemptRecord:
        return self._set_control_status("PAUSE_REQUESTED", RunStatus.PAUSE_REQUESTED)

    def resume(self) -> AttemptRecord:
        return self._set_control_status("RUNNING", RunStatus.RUNNING)

    def cancel(self) -> AttemptRecord:
        return self._set_control_status("CANCEL_REQUESTED", RunStatus.CANCELLED)

    def read_new_events(self) -> list[dict[str, object]]:
        path = self.event_path
        if not path.exists():
            return []
        with path.open("rb") as stream:
            stream.seek(self._event_offset)
            chunk = stream.read()
            self._event_offset = stream.tell()
        lines = (self._event_remainder + chunk).split(b"\n")
        self._event_remainder = lines.pop()
        events = [json.loads(line.decode("utf-8")) for line in lines if line]
        for event in events:
            self.event_received.emit(event)
        return events

    def refresh_control_status(self) -> AttemptRecord:
        """Reflect the pipeline's safe-checkpoint pause acknowledgement in the UI."""
        attempt = self._require_attempt()
        if attempt.status in {RunStatus.CANCELLED, RunStatus.COMPLETED, RunStatus.FAILED}:
            return attempt
        if not self.control_path.is_file():
            return attempt
        try:
            payload = json.loads(self.control_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, PermissionError, json.JSONDecodeError):
            return attempt
        status = {
            "RUNNING": RunStatus.RUNNING,
            "PAUSE_REQUESTED": RunStatus.PAUSE_REQUESTED,
            "PAUSED": RunStatus.PAUSED,
        }.get(str(payload.get("status", "")).upper())
        if status is None or status is attempt.status:
            return attempt
        updated = replace(attempt, status=status)
        self.active_attempt = updated
        self._write_state(updated)
        self.attempt_changed.emit(updated)
        return updated

    def refresh_terminal_status(self) -> AttemptRecord:
        attempt = self._require_attempt()
        manifest_path = attempt.artifacts_dir / "manifest.json"
        if not manifest_path.is_file():
            return attempt
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        mapping = {
            "COMPLETED": RunStatus.COMPLETED,
            "CANCELLED": RunStatus.CANCELLED,
            "ERROR": RunStatus.FAILED,
        }
        status = mapping.get(str(payload.get("status", "")).upper())
        if status is None:
            return attempt
        updated = replace(attempt, status=status)
        self.active_attempt = updated
        self._write_state(updated)
        self.attempt_changed.emit(updated)
        self.run_finished.emit(updated)
        self.process = None
        return updated

    @staticmethod
    def control_path_for(attempt: AttemptRecord) -> Path:
        return attempt.root / "control.json"

    def _set_control_status(self, control_status: str, run_status: RunStatus) -> AttemptRecord:
        attempt = replace(self._require_attempt(), status=run_status)
        self._write_json(self.control_path_for(attempt), {"status": control_status})
        self.active_attempt = attempt
        self._write_state(attempt)
        self.attempt_changed.emit(attempt)
        return attempt

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def _write_state(self, attempt: AttemptRecord) -> None:
        self._write_json(
            attempt.root / "desktop_state.json",
            {
                "logical_run_id": attempt.logical_run_id,
                "attempt_id": attempt.attempt_id,
                "parent_attempt_id": attempt.parent_attempt_id,
                "status": attempt.status,
            },
        )

    def _require_attempt(self) -> AttemptRecord:
        if self.active_attempt is None:
            raise RuntimeError("no active desktop run")
        return self.active_attempt
