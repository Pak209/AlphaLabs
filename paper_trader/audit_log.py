from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, payload: dict[str, Any]) -> None:
        entry = {
            "event": event,
            "logged_at": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")

    def read_today(self, now: datetime | None = None) -> list[dict[str, Any]]:
        today = (now or datetime.now(timezone.utc)).date()
        rows: list[dict[str, Any]] = []
        if not self.path.exists():
            return rows
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    logged_at = datetime.fromisoformat(str(row["logged_at"]).replace("Z", "+00:00"))
                except (KeyError, ValueError, json.JSONDecodeError):
                    continue
                if logged_at.date() == today:
                    rows.append(row)
        return rows

    def count_today(self, event: str, now: datetime | None = None) -> int:
        return sum(1 for row in self.read_today(now) if row.get("event") == event)

