"""Tests for the machine-readable JSONL event protocol."""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys

import pytest


class TrackingStream(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()


def test_writer_appends_one_utf8_json_object_per_line_with_utc_timestamp(
    tmp_path: Path,
):
    from ear_param.events import JsonlEventWriter

    path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path)

    payload = writer.emit("stage_started", stage="REMESH", sample_tag="T076_L_\u8033")
    writer.emit("stage_finished", stage="REMESH", attempt=2)

    lines = path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]

    assert len(events) == 2
    assert all(isinstance(event, dict) for event in events)
    assert payload == events[0]
    assert events[0]["event"] == "stage_started"
    assert events[0]["sample_tag"] == "T076_L_\u8033"
    assert events[1]["event"] == "stage_finished"
    assert datetime.fromisoformat(events[0]["timestamp"]).tzinfo == timezone.utc
    assert "\u8033".encode("utf-8") in path.read_bytes()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_writer_rejects_nonfinite_payload(tmp_path: Path, value: float):
    from ear_param.events import JsonlEventWriter

    path = tmp_path / "events.jsonl"

    with pytest.raises(ValueError):
        JsonlEventWriter(path).emit("progress", value=value)

    assert not path.exists()


def test_writer_mirrors_prefixed_event_to_stdout_and_flushes(
    tmp_path: Path,
    monkeypatch,
):
    from ear_param.events import EVENT_PREFIX, JsonlEventWriter

    path = tmp_path / "events.jsonl"
    stream = TrackingStream()
    monkeypatch.setattr(sys, "stdout", stream)

    JsonlEventWriter(path, mirror_stdout=True).emit("progress", percent=50)

    encoded = path.read_text(encoding="utf-8")
    assert EVENT_PREFIX == "@@EAR_EVENT@@"
    assert stream.getvalue() == f"{EVENT_PREFIX}{encoded}"
    assert stream.flush_count == 1
