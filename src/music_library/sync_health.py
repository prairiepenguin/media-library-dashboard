from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGES = (
    "music_scan",
    "musicbrainz_refresh",
    "plex_export",
    "artwork_refresh",
    "github_push",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sanitize_error(exc: Exception) -> str:
    message = str(exc).replace("\r", " ").replace("\n", " ")
    message = re.sub(r"https?://\S+", "[url removed]", message)
    message = re.sub(r"(?:[A-Za-z]:\\|/)[^ ]+", "[path removed]", message)
    message = re.sub(r"(?i)(token|key|password|secret)\s*[=:]\s*\S+", r"\1=[removed]", message)
    message = " ".join(message.split())[:240]
    return f"{type(exc).__name__}: {message or 'No details available'}"


class SyncHealth:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.payload: dict[str, Any] = payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            self.payload = {}
        self.payload.setdefault("schema_version", 1)
        self.payload.setdefault("stages", {})

    def _write(self) -> None:
        self.payload["updated_at"] = utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def start(self, stage: str) -> None:
        entry = self.payload["stages"].setdefault(stage, {})
        entry.update({"status": "running", "started_at": utc_now(), "error": ""})
        self._write()

    def succeed(self, stage: str, details: dict[str, Any] | None = None) -> None:
        entry = self.payload["stages"].setdefault(stage, {})
        entry.update({"status": "success", "last_success": utc_now(), "error": ""})
        if details:
            entry["details"] = details
        self._write()

    def skip(self, stage: str, reason: str) -> None:
        entry = self.payload["stages"].setdefault(stage, {})
        entry.update({"status": "skipped", "last_skipped": utc_now(), "reason": reason})
        self._write()

    def fail(self, stage: str, exc: Exception) -> None:
        entry = self.payload["stages"].setdefault(stage, {})
        error = sanitize_error(exc)
        entry.update(
            {
                "status": "error",
                "last_error": utc_now(),
                "last_error_message": error,
                "error": error,
            }
        )
        self._write()
