"""Machine-readable JSON Lines event protocol."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path


EVENT_PREFIX = "@@EAR_EVENT@@"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonlEventWriter:
    def __init__(self, path: Path, *, mirror_stdout: bool = False) -> None:
        self.path = Path(path)
        self.mirror_stdout = mirror_stdout

    def emit(self, event: str, **fields: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "event": event,
            "timestamp": _utc_timestamp(),
            **fields,
        }
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded + "\n")
            stream.flush()
        if self.mirror_stdout:
            print(f"{EVENT_PREFIX}{encoded}", flush=True)
        return payload
