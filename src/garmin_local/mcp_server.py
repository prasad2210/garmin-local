"""MCP server exposing read-only Garmin data via MCP stdio transport."""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
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
_sync_running = threading.Lock()  # only one sync at a time

log = logging.getLogger(__name__)


def _run_sync_once(force: bool = False) -> str:
    """Run a single watermark sync, serialised via _sync_running. Returns a status string."""
    if not _sync_running.acquire(blocking=False):
        return "skipped — sync already in progress"
    try:
        from garmin_local.auth import get_client, get_token_store
        from garmin_local.db import migrate, open_db
        from garmin_local.sync import run_sync

        db_path = Path(os.environ.get("GARMIN_DB_PATH", "data/garmin.db"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = open_db(db_path)
        conn.execute("PRAGMA busy_timeout = 30000")  # wait up to 30s for write lock
        migrate(conn)
        token_store = get_token_store()
        api = get_client(token_store)
        log.info("MCP: sync started (force=%s)", force)
        run_sync(conn, api, force=force)
        conn.close()
        log.info("MCP: sync complete")
        return "ok"
    except Exception as exc:
        log.exception("MCP: sync failed — serving from existing DB")
        return f"error: {exc}"
    finally:
        _sync_running.release()


def _start_sync_scheduler() -> None:
    pass  # no-op for local — sync runs on demand via sync_now or garmin-local sync


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


@mcp.tool()
def training_context(goal: str, weeks: int = 1) -> str:
    """Return a rich training context snapshot to help plan toward a running goal.

    Assembles recent training load, fitness trend, recovery state, sleep, HRV,
    and relevant personal records into a single response. Claude uses this to
    generate a personalised training plan — either a weekly schedule or a
    multi-week training block.

    Args:
        goal: The runner's target, e.g. 'sub-2h half marathon', 'sub-20 5K',
              'increase weekly mileage to 60km', 'plan this week's runs',
              'increase top speed', 'sub-45 10K'.
        weeks: How many weeks to plan (1 = this week only, 4-12 = training block).
               Default 1.
    """
    conn = _db()
    try:
        today = date.today()
        eight_weeks_ago = str(today - timedelta(weeks=8))
        four_weeks_ago = str(today - timedelta(weeks=4))
        two_weeks_ago = str(today - timedelta(weeks=2))
        today_str = str(today)

        sections: list[str] = [f"# Training context for goal: {goal}\n"]
        sections.append(f"_Data as of {today_str}_\n")

        # ------------------------------------------------------------------
        # Current load and fitness trend
        # ------------------------------------------------------------------
        load_rows = conn.execute(
            """
            SELECT
                strftime('%Y-W%W', calendar_date) AS week,
                ROUND(AVG(acute_load), 0)    AS acute_load,
                ROUND(AVG(acwr_ratio), 2)    AS acwr,
                ROUND(AVG(acwr_percent), 0)  AS acwr_pct,
                MAX(status_phrase)           AS status,
                ROUND(AVG(fitness_trend), 1) AS fitness_trend
            FROM training_status
            WHERE calendar_date >= ?
            GROUP BY week ORDER BY week
            """,
            (eight_weeks_ago,),
        ).fetchall()

        sections.append("## Training load (8 weeks)")
        sections.append(_rows_to_md(load_rows))
        sections.append(
            "_ACWR guide: <0.8 = undertraining, 0.8–1.3 = optimal, >1.5 = injury risk_\n"
        )

        # Most recent status
        latest_status = conn.execute(
            """
            SELECT calendar_date, acute_load, acwr_ratio, acwr_percent, status_phrase, fitness_trend
            FROM training_status
            ORDER BY calendar_date DESC LIMIT 1
            """
        ).fetchone()
        if latest_status:
            sections.append("**Most recent training status:**")
            for k in latest_status.keys():
                sections.append(f"- {k}: {_fmt(latest_status[k])}")
            sections.append("")

        # ------------------------------------------------------------------
        # Weekly running volume (last 8 weeks)
        # ------------------------------------------------------------------
        volume_rows = conn.execute(
            """
            SELECT
                strftime('%Y-W%W', calendar_date) AS week,
                COUNT(*) AS runs,
                ROUND(SUM(distance_m)/1000.0, 1) AS total_km,
                ROUND(AVG(distance_m)/1000.0, 1) AS avg_km,
                ROUND(AVG(avg_hr_bpm), 0)         AS avg_hr,
                ROUND(MIN(avg_speed_mps) * 3.6, 1) AS slowest_kph,
                ROUND(MAX(avg_speed_mps) * 3.6, 1) AS fastest_kph
            FROM activities
            WHERE activity_type = 'running' AND calendar_date >= ?
            GROUP BY week ORDER BY week
            """,
            (eight_weeks_ago,),
        ).fetchall()

        sections.append("## Running volume (8 weeks)")
        sections.append(_rows_to_md(volume_rows))
        sections.append("")

        # ------------------------------------------------------------------
        # Recent runs (last 4 weeks) with pace
        # ------------------------------------------------------------------
        recent_runs = conn.execute(
            """
            SELECT
                calendar_date,
                activity_name,
                ROUND(distance_m/1000.0, 2)                            AS km,
                ROUND(duration_s/60.0, 1)                              AS duration_min,
                ROUND(1000.0 / NULLIF(distance_m/NULLIF(duration_s,0), 0) / 60.0, 2) AS pace_min_per_km,
                avg_hr_bpm,
                aerobic_te
            FROM activities
            WHERE activity_type = 'running' AND calendar_date >= ?
            ORDER BY calendar_date DESC
            """,
            (four_weeks_ago,),
        ).fetchall()

        sections.append("## Recent runs (last 4 weeks)")
        sections.append(_rows_to_md(recent_runs))
        sections.append("")

        # ------------------------------------------------------------------
        # Recovery: HRV and sleep last 14 days
        # ------------------------------------------------------------------
        recovery_rows = conn.execute(
            """
            SELECT
                ds.calendar_date,
                h.last_night_avg_ms  AS hrv_ms,
                h.status             AS hrv_status,
                sl.sleep_score,
                ROUND(sl.total_sleep_s/3600.0,1) AS sleep_h,
                ds.body_battery_at_wake AS bb_wake,
                tr.score             AS readiness
            FROM daily_summary ds
            LEFT JOIN hrv h ON h.calendar_date = ds.calendar_date
            LEFT JOIN sleep sl ON sl.calendar_date = ds.calendar_date
            LEFT JOIN (
                SELECT calendar_date, score FROM training_readiness
                WHERE input_context = 'AFTER_WAKEUP_RESET' OR input_context IS NULL
                GROUP BY calendar_date HAVING timestamp_gmt = MIN(timestamp_gmt)
            ) tr ON tr.calendar_date = ds.calendar_date
            WHERE ds.calendar_date >= ?
            ORDER BY ds.calendar_date
            """,
            (two_weeks_ago,),
        ).fetchall()

        sections.append("## Recovery: HRV, sleep, readiness (last 14 days)")
        sections.append(_rows_to_md(recovery_rows))
        sections.append("")

        # ------------------------------------------------------------------
        # Personal records (running)
        # ------------------------------------------------------------------
        pr_rows = conn.execute(
            """
            SELECT type_key, type_id,
                CASE
                    WHEN type_id IN (1,2,3,4,5,6)
                    THEN ROUND(value/60.0, 2) || ' min'
                    ELSE ROUND(value/1000.0, 2) || ' km'
                END AS result,
                pr_date
            FROM personal_records
            WHERE activity_type = 'running'
            ORDER BY type_id
            """
        ).fetchall()

        sections.append("## Personal records (running)")
        sections.append(_rows_to_md(pr_rows) if pr_rows else "_No personal records synced yet_")
        sections.append("")

        # ------------------------------------------------------------------
        # Guidance note for Claude
        # ------------------------------------------------------------------
        plan_scope = (
            "this week only (7 days, day-by-day)"
            if weeks == 1
            else f"a {weeks}-week training block plus a detailed breakdown of week 1"
        )

        sections.append("---")
        sections.append(
            f"## Instructions for Claude\n"
            f"The runner's goal is: **{goal}**\n"
            f"Plan scope requested: **{plan_scope}**\n\n"
            "Using the data above, provide:\n\n"
            "### 1. Current fitness assessment\n"
            "- Where they are now vs the goal (use pace, HR, ACWR, HRV trend)\n"
            "- Estimated current ability (e.g. current 5K pace → what half marathon time that projects to)\n"
            "- Key limiters: what's the main thing holding them back?\n\n"
            "### 2. Training plan\n"
            f"Output a **{plan_scope}**.\n"
            "For each week include: total km target, number of sessions, session types.\n"
            "For each session include: day, type (easy/tempo/interval/long), distance, pace zone, purpose.\n"
            "Be conservative if ACWR > 1.3 or HRV is trending down — reduce load, don't add it.\n\n"
            "### 3. Pace zones (derive from their data)\n"
            "- Easy: slowest recent avg pace + 30-45 sec/km\n"
            "- Tempo: ~10K race pace (use PR if available)\n"
            "- Interval: ~5K race pace or faster (use PR if available)\n"
            "- Long run: easy pace, conversational effort\n\n"
            "### Goal-specific guidance\n"
            "- Race time target (sub-X): project current fitness → gap to goal → pacing strategy\n"
            "- Top speed / VO2max: include weekly strides and one interval session\n"
            "- Mileage build: apply 10% rule, never increase two hard weeks in a row\n"
            "- Weekly plan: match session count to recent habits, don't prescribe more days than they currently run\n\n"
            "Be specific with numbers. Write it so a non-technical runner can follow it without explanation."
        )

        return "\n".join(sections)
    finally:
        conn.close()


@mcp.tool()
def body_composition(start: str, end: str) -> str:
    """Body composition trend: weight, BMI, body fat %, muscle mass for a date range.

    Args:
        start: Start date ISO (YYYY-MM-DD).
        end: End date ISO (YYYY-MM-DD).
    """
    conn = _db()
    try:
        rows = conn.execute(
            """
            SELECT calendar_date, weight_kg, bmi, body_fat_pct,
                   muscle_mass_kg, bone_mass_kg, body_water_pct,
                   visceral_fat, metabolic_age
            FROM body_composition
            WHERE calendar_date BETWEEN ? AND ?
            ORDER BY calendar_date
            """,
            (start, end),
        ).fetchall()
        return _rows_to_md(rows)
    finally:
        conn.close()


@mcp.tool()
def sync_now() -> str:
    """Trigger an immediate sync from Garmin Connect.

    Starts a sync in the background and returns immediately — the sync itself
    takes 1-3 minutes. Call sync_status() afterwards to confirm it completed.
    Safe to call at any time; uses upserts so re-running changes nothing if
    data is already current.
    """
    if not _sync_running.acquire(blocking=False):
        return "A sync is already running. Call sync_status() in a minute to check progress."
    _sync_running.release()

    threading.Thread(
        target=_run_sync_once,
        kwargs={"force": True},
        daemon=True,
        name="garmin-sync-manual",
    ).start()
    return "Sync started in the background. Call sync_status() in 1-2 minutes to confirm it completed."


@mcp.tool()
def personal_records() -> str:
    """Return all-time personal records (fastest 5K, 10K, half marathon, marathon, etc.)."""
    conn = _db()
    try:
        rows = conn.execute(
            """
            SELECT
                type_key,
                activity_type,
                CASE
                    WHEN type_id IN (1,2,3,4,5,6)
                    THEN ROUND(value / 60.0, 2) || ' min'
                    ELSE ROUND(value / 1000.0, 2) || ' km'
                END AS result,
                pr_date,
                activity_id
            FROM personal_records
            ORDER BY activity_type, type_id
            """,
        ).fetchall()
        return _rows_to_md(rows)
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

## body_composition
Primary key: calendar_date TEXT
- weight_kg REAL, bmi REAL, body_fat_pct REAL
- muscle_mass_kg REAL, bone_mass_kg REAL, body_water_pct REAL
- visceral_fat REAL, metabolic_age INTEGER
(populated only if you use a Garmin smart scale)

## personal_records
Primary key: pr_id INTEGER
- activity_type TEXT (e.g. 'running'), type_id INTEGER, type_key TEXT
- type_id: 1=1km, 2=1mi, 3=5km, 4=10km, 5=half marathon, 6=marathon, 7=longest run
- value REAL — duration in seconds (types 1-6) or distance in metres (type 7)
- pr_date TEXT 'YYYY-MM-DD', activity_id INTEGER (source activity)

## raw_payloads
Primary key: (endpoint, date_key)
- fetched_at TEXT, payload TEXT (JSON)

## Tools summary
- sync_status, list_activities, activity_detail, daily_overview, weekly_summary
- training_load, sleep_analysis, body_composition, personal_records
- sync_now — pull the latest data from Garmin Connect immediately
- training_context(goal) — assembles all relevant data for a planning goal;
  Claude uses this to generate a personalised training plan or weekly schedule
- run_sql — arbitrary SELECT


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


def _add_health_routes(app: Any) -> Any:
    """Add /healthz and /readyz routes to an existing Starlette app."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def readyz(request: Request) -> JSONResponse:
        try:
            conn = _db()
            conn.execute("SELECT 1").fetchone()
            conn.close()
            return JSONResponse({"status": "ready"})
        except Exception as exc:
            return JSONResponse({"status": "not ready", "error": str(exc)}, status_code=503)

    app.router.routes.insert(0, Route("/healthz", healthz))
    app.router.routes.insert(1, Route("/readyz", readyz))
    return app


def serve(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the MCP server.

    transport: 'stdio' (default), 'sse', or 'streamable-http'.
    """
    if transport in ("sse", "streamable-http"):
        import uvicorn

        if transport == "sse":
            app = _add_health_routes(mcp.sse_app())
        else:
            app = _add_health_routes(mcp.streamable_http_app())

        uvicorn.run(app, host=host, port=port)
    else:
        mcp.run(transport="stdio")
