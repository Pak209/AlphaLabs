from __future__ import annotations

import json
from pathlib import Path

from .service import AlphaLabService


def seed() -> None:
    service = AlphaLabService()
    if service.list_ideas(limit=1):
        return
    sample_path = Path("alpha_lab/sample_alpha_idea.json")
    service.import_ideas(json.loads(sample_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    seed()
