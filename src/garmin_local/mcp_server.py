"""MCP server exposing read-only Garmin data via MCP stdio transport."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = MCPServer(
    "garmin-local",
    instructions=(
        "Read-only access to your local Garmin Connect SQLite database. "
        "All dates are ISO format (YYYY-MM-DD). "
        "Distances in metres, durations in seconds, speed in m/s, "
        "HR in bpm, HRV in ms (RMSSD), weight in kg, calories in kcal. "
        "Use garmin://schema to explore available tables and columns."
    ),
)

_DB_PATH: Path | None = None


def _db() -> sqlite3.Connection:
    """Return a read-only connection to the Garmin database."""
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = Path(os.environ.get("GARMIN_DB_PATH", "data/garmin.db"))
    uri = f"file:{_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_md(rows: list[sqlite3.Row], cap: int = 200) -> str:
    """Format sqlite3.Row results as a compact markdown table."""
    if not rows:
        return "_No data_"
    keys = list(rows[0].keys())
    truncated = len(rows) > cap
    display = rows[:cap]
    header = "| " + " | ".join(keys) + " |"
    sep = "| " + " | ".join("---" for _ in keys) + " |"
    body = "\n".join(
        "| " + " | ".join(str(r[k]) if r[k] is not None else "" for k in keys) + " |"
        for r in display
    )
    result = f"{header}\n{sep}\n{body}"
    if truncated:
        result += f"\n\n_{len(rows) - cap} more rows not shown_"
    return result


def _fmt(val: Any) -> str:
    return "" if val is None else str(val)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def sync_status() -> str:
    """Return last sync date, row counts per table, and date coverage."""
    conn = _db()
    try:
        watermark = conn.execute(
            "SELECT value FROM sync_state WHERE key='last_sync_success'"
        ).fetchone()
        last_sync = watermark["value"] if watermark else "never"

        tables = [
            "activities", "daily_summary", "sleep", "hrv",
            "training_readiness", "training_status", "strength_sets",
            "raw_payloads",
        ]
        lines = [f"**Last sync:** {last_sync}\n", "| Table | Rows | Earliest | Latest |",
                 "|-------|------|----------|--------|"]
        for t in tables:
            try:
                row = conn.execute(f"SELECT COUNT(*) as n FROM {t}").fetchone()  # noqa: S608
                n = row["n"]
                # find date coverage where possible
                date_col = {
                    "activities": "calendar_date",
                    "daily_summary": "calendar_date",
                    "sleep": "calendar_date",
                    "hrv": "calendar_date",
                    "training_readiness": "calendar_date",
                    "training_status": "calendar_date",
                    "strength_sets": None,
                    "raw_payloads": "date_key",
                }.get(t)
                if date_col:
                    span = conn.execute(
                        f"SELECT MIN({date_col}), MAX({date_col}) FROM {t}"  # noqa: S608
                    ).fetchone()
                    earliest, latest = span[0] or "", span[1] or ""
                else:
                    earliest, latest = "", ""
                lines.append(f"| {t} | {n} | {earliest} | {latest} |")
            except sqlite3.OperationalError:
                lines.append(f"| {t} | error | | |")
        return "\n".join(lines)
    finally:
        conn.close()


@mcp.tool()
def list_activities(
    start: str,
    end: str,
    activity_type: str = "",
    limit: int = 50,
) -> str:
    """List activities in a date range.

    Args:
        start: Start date ISO (YYYY-MM-DD).
        end: End date ISO (YYYY-MM-DD).
        activity_type: Filter by type key e.g. 'running', 'strength_training'. Empty = all.
        limit: Max rows to return (default 50, max 200).
    """
    conn = _db()
    try:
        limit = min(limit, 200)
        params: list[Any] = [start, end]
        type_clause = ""
        if activity_type:
            type_clause = " AND activity_type = ?"
            params.append(activity_type)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT activity_id, calendar_date, activity_type, activity_name,
                   ROUND(distance_m/1000.0, 2) AS distance_km,
                   ROUND(duration_s/60.0, 1) AS duration_min,
                   ROUND(avg_speed_mps * 3.6, 2) AS avg_speed_kph,
                   avg_hr_bpm, max_hr_bpm, calories_kcal, aerobic_te
            FROM activities
            WHERE calendar_date BETWEEN ? AND ?{type_clause}
            ORDER BY calendar_date DESC
            LIMIT ?
            """,  # noqa: S608
            params,
        ).fetchall()
        return _rows_to_md(rows)
    finally:
        conn.close()


@mcp.tool()
def activity_detail(activity_id: int) -> str:
    """Return full detail for one activity, including strength sets if applicable.

    Args:
        activity_id: Garmin activity ID (integer).
    """
    conn = _db()
    try:
        act = conn.execute(
            "SELECT * FROM activities WHERE activity_id = ?", (activity_id,)
        ).fetchone()
        if not act:
            return f"_No activity found with id {activity_id}_"

        lines = ["**Activity**\n"]
        for k in act.keys():  # noqa: SIM118 — sqlite3.Row needs .keys()
            lines.append(f"- **{k}:** {_fmt(act[k])}")

        sets = conn.execute(
            """
            SELECT ss.message_index, ss.set_type, ss.duration_s, ss.reps, ss.weight_kg,
                   GROUP_CONCAT(ese.category || COALESCE('/' || ese.name, ''), ' | ') AS exercises
            FROM strength_sets ss
            LEFT JOIN exercise_set_exercises ese
                   ON ese.activity_id = ss.activity_id AND ese.message_index = ss.message_index
                  AND ese.rank = 0
            WHERE ss.activity_id = ?
            GROUP BY ss.message_index
            ORDER BY ss.message_index
            """,
            (activity_id,),
        ).fetchall()
        if sets:
            lines.append("\n**Strength Sets**\n")
            lines.append(_rows_to_md(sets))
        return "\n".join(lines)
    finally:
        conn.close()


@mcp.tool()
def daily_overview(start: str, end: str) -> str:
    """Daily wellness overview: steps, HR, stress, body battery, sleep, HRV, readiness.

    Args:
        start: Start date ISO (YYYY-MM-DD).
        end: End date ISO (YYYY-MM-DD).
    """
    conn = _db()
    try:
        rows = conn.execute(
            """
            SELECT
                ds.calendar_date,
                ds.total_steps,
                ds.resting_hr_bpm,
                ds.avg_stress,
                ds.body_battery_at_wake  AS bb_wake,
                ds.body_battery_high     AS bb_high,
                ds.body_battery_low      AS bb_low,
                sl.sleep_score,
                ROUND(sl.total_sleep_s / 3600.0, 1) AS sleep_h,
                h.last_night_avg_ms      AS hrv_ms,
                h.status                 AS hrv_status,
                tr.score                 AS readiness,
                tr.level                 AS readiness_level
            FROM daily_summary ds
            LEFT JOIN sleep sl ON sl.calendar_date = ds.calendar_date
            LEFT JOIN hrv h ON h.calendar_date = ds.calendar_date
            LEFT JOIN (
                SELECT calendar_date, score, level
                FROM training_readiness
                WHERE input_context = 'AFTER_WAKEUP_RESET'
                   OR input_context IS NULL
                GROUP BY calendar_date
                HAVING timestamp_gmt = MIN(timestamp_gmt)
            ) tr ON tr.calendar_date = ds.calendar_date
            WHERE ds.calendar_date BETWEEN ? AND ?
            ORDER BY ds.calendar_date
            """,
            (start, end),
        ).fetchall()
        return _rows_to_md(rows)
    finally:
        conn.close()


@mcp.tool()
def weekly_summary(weeks: int = 8) -> str:
    """Weekly training summary: volume by activity type, avg sleep, avg HRV, avg readiness.

    Args:
        weeks: Number of recent weeks to include (default 8).
    """
    conn = _db()
    try:
        since = str(date.today() - timedelta(weeks=weeks))
        activity_rows = conn.execute(
            """
            SELECT
                strftime('%Y-W%W', calendar_date) AS week,
                activity_type,
                COUNT(*) AS sessions,
                ROUND(SUM(distance_m) / 1000.0, 1) AS total_km,
                ROUND(SUM(duration_s) / 60.0, 0)   AS total_min,
                ROUND(AVG(avg_hr_bpm), 0)           AS avg_hr
            FROM activities
            WHERE calendar_date >= ?
            GROUP BY week, activity_type
            ORDER BY week, activity_type
            """,
            (since,),
        ).fetchall()

        wellness_rows = conn.execute(
            """
            SELECT
                strftime('%Y-W%W', ds.calendar_date) AS week,
                ROUND(AVG(sl.total_sleep_s) / 3600.0, 1) AS avg_sleep_h,
                ROUND(AVG(h.last_night_avg_ms), 0)        AS avg_hrv_ms,
                ROUND(AVG(tr.score), 0)                   AS avg_readiness
            FROM daily_summary ds
            LEFT JOIN sleep sl ON sl.calendar_date = ds.calendar_date
            LEFT JOIN hrv h ON h.calendar_date = ds.calendar_date
            LEFT JOIN (
                SELECT calendar_date, score FROM training_readiness
                WHERE input_context = 'AFTER_WAKEUP_RESET' OR input_context IS NULL
                GROUP BY calendar_date HAVING timestamp_gmt = MIN(timestamp_gmt)
            ) tr ON tr.calendar_date = ds.calendar_date
            WHERE ds.calendar_date >= ?
            GROUP BY week
            ORDER BY week
            """,
            (since,),
        ).fetchall()

        parts = ["**Activity volume by week**\n", _rows_to_md(activity_rows),
                 "\n**Weekly wellness averages**\n", _rows_to_md(wellness_rows)]
        return "\n".join(parts)
    finally:
        conn.close()


@mcp.tool()
def training_load(weeks: int = 12) -> str:
    """Training load trend: weekly acute load, ACWR, training status phrase, fitness trend.

    Args:
        weeks: Number of recent weeks to include (default 12).
    """
    conn = _db()
    try:
        since = str(date.today() - timedelta(weeks=weeks))
        rows = conn.execute(
            """
            SELECT
                strftime('%Y-W%W', calendar_date) AS week,
                ROUND(AVG(acute_load), 0)   AS avg_acute_load,
                ROUND(AVG(acwr_ratio), 2)   AS avg_acwr,
                ROUND(AVG(acwr_percent), 0) AS avg_acwr_pct,
                MAX(status_phrase)          AS status_phrase,
                ROUND(AVG(fitness_trend), 1) AS avg_fitness_trend
            FROM training_status
            WHERE calendar_date >= ?
            GROUP BY week
            ORDER BY week
            """,
            (since,),
        ).fetchall()
        return _rows_to_md(rows)
    finally:
        conn.close()


@mcp.tool()
def sleep_analysis(start: str, end: str) -> str:
    """Sleep detail: duration, stages, score, HRV, SpO2, respiration for a date range.

    Args:
        start: Start date ISO (YYYY-MM-DD).
        end: End date ISO (YYYY-MM-DD).
    """
    conn = _db()
    try:
        rows = conn.execute(
            """
            SELECT
                sl.calendar_date,
                ROUND(sl.total_sleep_s / 3600.0, 1)  AS total_h,
                ROUND(sl.deep_sleep_s / 3600.0, 1)   AS deep_h,
                ROUND(sl.rem_sleep_s / 3600.0, 1)    AS rem_h,
                ROUND(sl.light_sleep_s / 3600.0, 1)  AS light_h,
                sl.sleep_score,
                sl.sleep_score_qualifier,
                sl.avg_hr_bpm,
                sl.avg_spo2_pct,
                sl.lowest_spo2_pct,
                sl.avg_respiration_brpm,
                sl.awake_count,
                h.last_night_avg_ms  AS hrv_ms,
                h.status             AS hrv_status
            FROM sleep sl
            LEFT JOIN hrv h ON h.calendar_date = sl.calendar_date
            WHERE sl.calendar_date BETWEEN ? AND ?
            ORDER BY sl.calendar_date
            """,
            (start, end),
        ).fetchall()
        return _rows_to_md(rows)
    finally:
        conn.close()


@mcp.tool()
def run_sql(query: str) -> str:
    """Execute a read-only SELECT query against the Garmin database.

    Restricted to SELECT statements only. Max 200 rows returned. 10-second timeout.
    Use garmin://schema to explore the schema first.

    Args:
        query: A single SQL SELECT statement.
    """
    # Only allow SELECT
    stripped = query.strip()
    if not re.match(r"(?i)^select\b", stripped):
        return "_Error: only SELECT statements are allowed._"
    # Reject multiple statements
    if ";" in stripped.rstrip(";"):
        return "_Error: only a single statement is allowed._"

    conn = _db()
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        rows = conn.execute(stripped).fetchmany(200)  # type: ignore[arg-type]
        if not rows:
            return "_No rows returned_"
        # Convert to list of Row for _rows_to_md
        all_rows = conn.execute(stripped).fetchall()  # type: ignore[arg-type]
        return _rows_to_md(all_rows)
    except sqlite3.OperationalError as exc:
        return f"_SQL error: {exc}_"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Resource: schema
# ---------------------------------------------------------------------------


@mcp.resource("garmin://schema")
def schema_resource() -> str:
    """Database schema: tables, columns, units, example queries."""
    return """# garmin-local database schema

All dates: TEXT "YYYY-MM-DD". Timestamps: TEXT UTC ISO. Units as noted.

## activities
Primary key: activity_id (INTEGER)
- activity_type TEXT — e.g. 'running', 'strength_training', 'cycling'
- calendar_date, start_time_gmt, start_time_local
- distance_m REAL (metres), duration_s REAL (seconds), moving_duration_s
- avg_speed_mps REAL (m/s), calories_kcal REAL
- avg_hr_bpm REAL, max_hr_bpm REAL, steps INTEGER
- aerobic_te REAL (0-5), anaerobic_te REAL (0-5)

## daily_summary
Primary key: calendar_date TEXT
- total_steps, total_distance_m (metres)
- resting_hr_bpm, min_hr_bpm, max_hr_bpm
- avg_stress, max_stress (0-100)
- body_battery_high, body_battery_low, body_battery_at_wake, body_battery_most_recent (0-100)
- total_kcal, active_kcal, bmr_kcal
- highly_active_s, active_s, sedentary_s, sleeping_s (seconds)
- moderate_intensity_min, vigorous_intensity_min
- avg_spo2_pct, lowest_spo2_pct (%), avg_respiration_brpm (breaths/min)

## sleep
Primary key: calendar_date TEXT
- sleep_start_gmt, sleep_end_gmt (UTC ISO)
- total_sleep_s, deep_sleep_s, light_sleep_s, rem_sleep_s, awake_s, nap_s (seconds)
- sleep_score (0-100), sleep_score_qualifier TEXT (e.g. 'GOOD')
- avg_hr_bpm, avg_spo2_pct, lowest_spo2_pct, avg_respiration_brpm
- awake_count INTEGER, avg_stress REAL, breathing_disruption TEXT

## hrv
Primary key: calendar_date TEXT
- weekly_avg_ms, last_night_avg_ms, last_night_5min_high_ms (ms, RMSSD)
- baseline_low_ms, baseline_balanced_low_ms, baseline_balanced_high_ms
- status TEXT (e.g. 'BALANCED'), feedback_phrase TEXT

## training_readiness
Primary key: (calendar_date, timestamp_gmt)
- score (0-100), level TEXT ('LOW'/'MODERATE'/'HIGH')
- input_context TEXT — 'AFTER_WAKEUP_RESET' is the morning score
- sleep_score, recovery_time_h (hours), acute_load, hrv_weekly_avg_ms
- factor percentages: sleep_score_factor_pct, recovery_time_factor_pct,
  acwr_factor_pct, stress_history_factor_pct, hrv_factor_pct, sleep_history_factor_pct

## training_status
Primary key: calendar_date TEXT
- status_phrase TEXT (e.g. 'MAINTAINING_1'), training_status_id, fitness_trend
- acwr_percent, acwr_status, acwr_ratio
- acute_load, chronic_load_min, chronic_load_max

## strength_sets
Primary key: (activity_id, message_index)
- set_type TEXT ('ACTIVE' or 'REST')
- duration_s REAL, reps INTEGER, weight_kg REAL (null = no sensor)

## exercise_set_exercises
Primary key: (activity_id, message_index, rank)
- rank=0 is highest-probability classification
- category TEXT (e.g. 'PULL_UP'), name TEXT (e.g. 'LAT_PULLDOWN'), probability REAL

## raw_payloads
Primary key: (endpoint, date_key)
- fetched_at TEXT, payload TEXT (JSON)

## Example queries

-- Last 4 weeks of runs with pace
SELECT calendar_date, activity_name,
       ROUND(distance_m/1000.0,2) AS km,
       ROUND(duration_s/60.0,1) AS min,
       ROUND(1000.0/(distance_m/duration_s)/60.0,2) AS pace_min_per_km,
       avg_hr_bpm
FROM activities
WHERE activity_type='running' AND calendar_date >= date('now','-28 days')
ORDER BY calendar_date DESC;

-- Sleep trend last 2 weeks
SELECT calendar_date,
       ROUND(total_sleep_s/3600.0,1) AS sleep_h,
       sleep_score, last_night_avg_ms AS hrv_ms
FROM sleep JOIN hrv USING(calendar_date)
WHERE calendar_date >= date('now','-14 days')
ORDER BY calendar_date;

-- Strength sessions with exercise summary
SELECT a.calendar_date, a.activity_name,
       COUNT(CASE WHEN ss.set_type='ACTIVE' THEN 1 END) AS active_sets
FROM activities a JOIN strength_sets ss USING(activity_id)
WHERE a.activity_type='strength_training'
GROUP BY a.activity_id ORDER BY a.calendar_date DESC LIMIT 10;
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def serve() -> None:
    """Start the MCP server over stdio."""
    mcp.run(transport="stdio")
