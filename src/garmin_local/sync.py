"""Watermark sync: pull new data from Garmin and upsert into SQLite."""

from __future__ import annotations

import sqlite3
from datetime import date


def get_watermark(conn: sqlite3.Connection) -> date | None:
    """Return the last successful sync date, or None for first run."""
    raise NotImplementedError("Phase 2")


def run_sync(
    conn: sqlite3.Connection,
    *,
    force: bool = False,
    backfill_days: int = 90,
) -> None:
    """Execute a watermark sync.

    On first run, backfills *backfill_days* days.
    Re-running must be a no-op (idempotent upserts).
    """
    raise NotImplementedError("Phase 2")
