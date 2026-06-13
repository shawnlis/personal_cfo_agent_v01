"""Template writer for structured manual snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_manual_snapshot_template() -> dict[str, Any]:
    return {
        "snapshot_date": datetime.now(timezone.utc).date().isoformat(),
        "base_currency": "SGD",
        "source_note": "Manual user-entered snapshot. Do not include account numbers.",
        "assets": [],
        "liabilities": [],
        "warnings_acknowledged": False,
    }


def write_manual_snapshot_template(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_manual_snapshot_template(), indent=2) + "\n",
        encoding="utf-8",
    )
    return path
