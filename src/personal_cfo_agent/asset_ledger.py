"""CSV helpers for the normalized asset ledger."""

from __future__ import annotations

import csv
from pathlib import Path

from personal_cfo_agent.models import LEDGER_FIELDNAMES, NormalizedAsset


def ledger_rows_for_csv(rows: list[NormalizedAsset]) -> list[dict[str, str]]:
    return [row.to_csv_row() for row in rows]


def write_normalized_asset_ledger(path: Path, rows: list[NormalizedAsset]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDNAMES)
        writer.writeheader()
        writer.writerows(ledger_rows_for_csv(rows))
