"""Watermark sync: pull new data from Garmin and upsert into SQLite."""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from garmin_local.normalize import (
    normalize_activity,
    normalize_daily_summary,
    normalize_exercise_sets,
    normalize_hrv,
    normalize_sleep,
    normalize_training_readiness,
    normalize_training_status,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config defaults (can be overridden by env)
# ---------------------------------------------------------------------------

SLEEP_MIN = 1.0
SLEEP_MAX = 2.0
DEFAULT_BACKFILL_DAYS = 90

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sleep() -> None:
    time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))


def _today_str() -> str:
    return str(date.today())


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")


def _date_range(start: date, end: date) -> list[str]:
    """Return list of ISO date strings from start to end inclusive."""
    days = (end - start).days
    return [str(start + timedelta(days=i)) for i in range(days + 1)]


# ---------------------------------------------------------------------------
# Watermark
# ---------------------------------------------------------------------------

WATERMARK_KEY = "last_sync_success"


def get_watermark(conn: sqlite3.Connection) -> date | None:
    """Return the last successful sync date, or None for first run."""
    row = conn.execute(
        "SELECT value FROM sync_state WHERE key = ?", (WATERMARK_KEY,)
    ).fetchone()
    if row is None:
        return None
    return date.fromisoformat(row["value"])


def set_watermark(conn: sqlite3.Connection, d: date) -> None:
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (WATERMARK_KEY, str(d)),
    )


# ---------------------------------------------------------------------------
# Raw payload store
# ---------------------------------------------------------------------------


def _save_raw(conn: sqlite3.Connection, endpoint: str, date_key: str, payload: Any) -> None:
    conn.execute(
        "INSERT INTO raw_payloads (endpoint, date_key, fetched_at, payload)"
        " VALUES (?, ?, ?, ?)"
        " ON CONFLICT(endpoint, date_key) DO UPDATE SET"
        "   fetched_at = excluded.fetched_at,"
        "   payload = excluded.payload",
        (endpoint, date_key, _now_utc_iso(), json.dumps(payload, default=str)),
    )


# ---------------------------------------------------------------------------
# Per-table upserts
# ---------------------------------------------------------------------------


def _upsert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" * len(row))
    updates = ", ".join(f"{k} = excluded.{k}" for k in row if k != _pk(table))
    sql = (
        f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        f" ON CONFLICT({_pk(table)}) DO UPDATE SET {updates}"
    )
    conn.execute(sql, list(row.values()))


def _pk(table: str) -> str:
    pks = {
        "activities": "activity_id",
        "daily_summary": "calendar_date",
        "sleep": "calendar_date",
        "hrv": "calendar_date",
        "training_status": "calendar_date",
        "body_composition": "calendar_date",
        "strength_sets": "(activity_id, message_index)",
        "training_readiness": "(calendar_date, timestamp_gmt)",
    }
    return pks.get(table, "rowid")


def _upsert_composite(
    conn: sqlite3.Connection,
    table: str,
    pk_cols: list[str],
    row: dict[str, Any],
) -> None:
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" * len(row))
    pk_expr = ", ".join(pk_cols)
    updates = ", ".join(f"{k} = excluded.{k}" for k in row if k not in pk_cols)
    if updates:
        sql = (
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
            f" ON CONFLICT({pk_expr}) DO UPDATE SET {updates}"
        )
    else:
        sql = (
            f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})"
        )
    conn.execute(sql, list(row.values()))


# ---------------------------------------------------------------------------
# Main sync
# ---------------------------------------------------------------------------


def run_sync(
    conn: sqlite3.Connection,
    api: Any,
    *,
    force: bool = False,
    backfill_days: int = DEFAULT_BACKFILL_DAYS,
) -> None:
    """Execute a watermark sync. Idempotent — re-running changes nothing."""
    today = date.today()
    watermark = get_watermark(conn)

    if watermark is None:
        start = today - timedelta(days=backfill_days)
        logger.info("First run — backfilling %d days from %s", backfill_days, start)
    elif force:
        start = today - timedelta(days=7)
        logger.info("Forced sync from %s", start)
    else:
        cadence_check = today - timedelta(days=7)
        if watermark >= cadence_check:
            logger.info("Last sync %s is recent — skipping (use --now to force)", watermark)
            return
        start = watermark - timedelta(days=7)  # overlap to catch late-arriving data
        logger.info("Incremental sync from %s", start)

    start_str = str(start)
    today_str = str(today)
    dates = _date_range(start, today)

    logger.info("Syncing %d days (%s to %s)", len(dates), start_str, today_str)

    # ------------------------------------------------------------------
    # Activities
    # ------------------------------------------------------------------
    logger.info("Fetching activities %s to %s", start_str, today_str)
    activities_raw = api.get_activities_by_date(start_str, today_str)
    _sleep()

    if isinstance(activities_raw, list):
        _save_raw(conn, "activities_by_date", f"{start_str}_{today_str}", activities_raw)
        strength_ids: list[int] = []
        for act in activities_raw:
            row = normalize_activity(act)
            _upsert(conn, "activities", row)
            if act.get("activityType", {}).get("typeKey") in (
                "strength_training", "fitness_equipment"
            ):
                strength_ids.append(act["activityId"])
        conn.commit()
        logger.info("Upserted %d activities", len(activities_raw))

        for aid in strength_ids:
            logger.info("Fetching exercise sets for activity %s", aid)
            sets_raw = api.get_activity_exercise_sets(aid)
            _sleep()
            if sets_raw:
                _save_raw(conn, "activity_exercise_sets", str(aid), sets_raw)
                sets_rows, ex_rows = normalize_exercise_sets(aid, sets_raw)
                for r in sets_rows:
                    _upsert_composite(conn, "strength_sets", ["activity_id", "message_index"], r)
                for r in ex_rows:
                    _upsert_composite(
                        conn,
                        "exercise_set_exercises",
                        ["activity_id", "message_index", "rank"],
                        r,
                    )
                conn.commit()

    # ------------------------------------------------------------------
    # Daily wellness
    # ------------------------------------------------------------------
    logger.info("Fetching daily summaries")
    for d in dates:
        raw = api.get_stats(d)
        _sleep()
        if raw:
            _save_raw(conn, "daily_summary", d, raw)
            _upsert(conn, "daily_summary", normalize_daily_summary(raw))

    conn.commit()
    logger.info("Upserted daily_summary for %d days", len(dates))

    # ------------------------------------------------------------------
    # Sleep
    # ------------------------------------------------------------------
    logger.info("Fetching sleep data")
    for d in dates:
        raw = api.get_daily_sleep(d)
        _sleep()
        if raw:
            _save_raw(conn, "sleep", d, raw)
            row = normalize_sleep(raw)
            if row and row.get("calendar_date"):
                _upsert(conn, "sleep", row)

    conn.commit()
    logger.info("Upserted sleep")

    # ------------------------------------------------------------------
    # HRV
    # ------------------------------------------------------------------
    logger.info("Fetching HRV range %s to %s", start_str, today_str)
    hrv_range = api.get_hrv_data_range(start_str, today_str)
    _sleep()
    if hrv_range:
        _save_raw(conn, "hrv_range", f"{start_str}_{today_str}", hrv_range)
        for summary in hrv_range.get("hrvSummaries", []):
            row = normalize_hrv({"hrvSummary": summary})
            if row and row.get("calendar_date"):
                _upsert(conn, "hrv", row)

    conn.commit()
    logger.info("Upserted HRV")

    # ------------------------------------------------------------------
    # Training readiness
    # ------------------------------------------------------------------
    logger.info("Fetching training readiness")
    for d in dates:
        raw = api.get_training_readiness(d)
        _sleep()
        if raw:
            _save_raw(conn, "training_readiness", d, raw)
            for row in normalize_training_readiness(raw if isinstance(raw, list) else [raw]):
                if row.get("calendar_date") and row.get("timestamp_gmt"):
                    _upsert_composite(
                        conn,
                        "training_readiness",
                        ["calendar_date", "timestamp_gmt"],
                        row,
                    )

    conn.commit()
    logger.info("Upserted training_readiness")

    # ------------------------------------------------------------------
    # Training status
    # ------------------------------------------------------------------
    logger.info("Fetching training status")
    for d in dates:
        raw = api.get_daily_training_status(d)
        _sleep()
        if raw:
            _save_raw(conn, "training_status", d, raw)
            row = normalize_training_status(raw)
            if row and row.get("calendar_date"):
                _upsert(conn, "training_status", row)

    conn.commit()
    logger.info("Upserted training_status")

    # ------------------------------------------------------------------
    # Watermark
    # ------------------------------------------------------------------
    set_watermark(conn, today)
    conn.commit()
    logger.info("Sync complete. Watermark set to %s", today)
