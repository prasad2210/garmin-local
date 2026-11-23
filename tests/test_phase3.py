"""Tests for Phase 3: MCP server tools using an in-memory DB with synthetic data."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from garmin_local.db import migrate, open_db

# ---------------------------------------------------------------------------
# Fixtures: in-memory DB seeded with synthetic data
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create a seeded DB and point the MCP server at it."""
    db_path = tmp_path / "garmin.db"
    monkeypatch.setenv("GARMIN_DB_PATH", str(db_path))

    # Reset cached path in mcp_server between tests
    import garmin_local.mcp_server as ms
    ms._DB_PATH = None

    conn = open_db(db_path)
    migrate(conn)

    today = date(2026, 11, 20)
    dates = [str(today - timedelta(days=i)) for i in range(13, -1, -1)]

    # sync_state
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES ('last_sync_success', ?)",
        (str(today),),
    )

    # activities
    conn.execute(
        """INSERT INTO activities VALUES
        (1001,'Morning Run','running','2026-11-20 06:00:00','2026-11-20 07:00:00',
         '2026-11-20',10000,3600,3550,3600,2.78,500,145,170,9000,3.5,0.5,999)"""
    )
    conn.execute(
        """INSERT INTO activities VALUES
        (1002,'Strength','strength_training','2026-11-18 08:00:00','2026-11-18 09:00:00',
         '2026-11-18',NULL,3600,NULL,3600,NULL,300,130,160,NULL,2.0,0.5,999)"""
    )

    # strength_sets + exercises
    conn.execute(
        "INSERT INTO strength_sets VALUES (1002,0,'ACTIVE','2026-11-18T08:01:00.0',45,10,NULL)"
    )
    conn.execute(
        "INSERT INTO strength_sets VALUES (1002,1,'REST','2026-11-18T08:01:45.0',60,NULL,NULL)"
    )
    conn.execute(
        "INSERT INTO exercise_set_exercises VALUES (1002,0,0,'PULL_UP','LAT_PULLDOWN',95.0)"
    )

    # daily_summary + sleep + hrv + training_readiness + training_status
    for d in dates:
        conn.execute(
            """INSERT OR IGNORE INTO daily_summary
            (calendar_date,total_steps,total_distance_m,resting_hr_bpm,
             avg_stress,body_battery_high,body_battery_low,body_battery_at_wake,
             body_battery_most_recent,total_kcal,active_kcal,bmr_kcal,
             highly_active_s,active_s,sedentary_s,sleeping_s,
             moderate_intensity_min,vigorous_intensity_min,
             avg_spo2_pct,lowest_spo2_pct,avg_respiration_brpm,
             wellness_start_gmt,wellness_end_gmt)
            VALUES (?,8000,6400,50,30,85,32,70,60,2200,400,1800,
                    1800,3600,36000,28800,20,10,96,93,14,
                    ?||'T00:00:00',?||'T23:59:59')""",
            (d, d, d),
        )
        conn.execute(
            """INSERT OR IGNORE INTO sleep
            (calendar_date,sleep_start_gmt,sleep_end_gmt,total_sleep_s,
             deep_sleep_s,light_sleep_s,rem_sleep_s,awake_s,nap_s,
             awake_count,sleep_score,sleep_score_qualifier,
             avg_hr_bpm,avg_spo2_pct,lowest_spo2_pct,avg_respiration_brpm,
             avg_stress,breathing_disruption)
            VALUES (?,?||'T22:00:00',?||'T06:00:00',28800,
                    5400,14400,7200,1800,0,
                    3,78,'GOOD',52,96,93,14,20,'NONE')""",
            (d, d, d),
        )
        conn.execute(
            """INSERT OR IGNORE INTO hrv
            (calendar_date,weekly_avg_ms,last_night_avg_ms,last_night_5min_high_ms,
             baseline_low_ms,baseline_balanced_low_ms,baseline_balanced_high_ms,
             status,feedback_phrase)
            VALUES (?,55,58,72,45,50,65,'BALANCED','HRV_BALANCED_1')""",
            (d,),
        )
        conn.execute(
            """INSERT OR IGNORE INTO training_readiness
            (calendar_date,timestamp_gmt,input_context,score,level,
             sleep_score,recovery_time_h,acute_load,hrv_weekly_avg_ms,
             sleep_score_factor_pct,recovery_time_factor_pct,acwr_factor_pct,
             stress_history_factor_pct,hrv_factor_pct,sleep_history_factor_pct)
            VALUES (?,?||'T07:30:00.0','AFTER_WAKEUP_RESET',72,'HIGH',
                    78,0,350,55,80,90,70,65,75,68)""",
            (d, d),
        )
        conn.execute(
            """INSERT OR IGNORE INTO training_status
            (calendar_date,status_phrase,training_status_id,fitness_trend,
             acwr_percent,acwr_status,acute_load,chronic_load_min,chronic_load_max,acwr_ratio)
            VALUES (?,
                    'MAINTAINING_1',4,2,80,'OPTIMAL',350,300,450,0.85)""",
            (d,),
        )

    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Tool tests
# ---------------------------------------------------------------------------


def test_sync_status(seeded_db):
    from garmin_local.mcp_server import sync_status
    result = sync_status()
    assert "2026-11-20" in result
    assert "activities" in result
    assert "daily_summary" in result


def test_list_activities_all(seeded_db):
    from garmin_local.mcp_server import list_activities
    result = list_activities("2026-11-01", "2026-11-30")
    assert "Morning Run" in result
    assert "Strength" in result


def test_list_activities_filter_type(seeded_db):
    from garmin_local.mcp_server import list_activities
    result = list_activities("2026-11-01", "2026-11-30", activity_type="running")
    assert "Morning Run" in result
    assert "Strength" not in result


def test_list_activities_empty_range(seeded_db):
    from garmin_local.mcp_server import list_activities
    result = list_activities("2025-01-01", "2025-01-07")
    assert "No data" in result


def test_activity_detail_run(seeded_db):
    from garmin_local.mcp_server import activity_detail
    result = activity_detail(1001)
    assert "Morning Run" in result
    assert "1001" in result


def test_activity_detail_strength_shows_sets(seeded_db):
    from garmin_local.mcp_server import activity_detail
    result = activity_detail(1002)
    assert "Strength Sets" in result
    assert "PULL_UP" in result or "LAT_PULLDOWN" in result


def test_activity_detail_missing(seeded_db):
    from garmin_local.mcp_server import activity_detail
    result = activity_detail(99999)
    assert "No activity" in result


def test_daily_overview(seeded_db):
    from garmin_local.mcp_server import daily_overview
    result = daily_overview("2026-11-10", "2026-11-20")
    assert "sleep_score" in result or "78" in result
    assert "2026-11-20" in result


def test_weekly_summary(seeded_db):
    from garmin_local.mcp_server import weekly_summary
    result = weekly_summary(weeks=4)
    assert "running" in result
    assert "sleep" in result.lower() or "avg_sleep" in result


def test_training_load(seeded_db):
    from garmin_local.mcp_server import training_load
    result = training_load(weeks=4)
    assert "MAINTAINING" in result or "acwr" in result.lower()


def test_sleep_analysis(seeded_db):
    from garmin_local.mcp_server import sleep_analysis
    result = sleep_analysis("2026-11-10", "2026-11-20")
    assert "sleep_score" in result or "78" in result
    assert "BALANCED" in result


def test_run_sql_select(seeded_db):
    from garmin_local.mcp_server import run_sql
    result = run_sql("SELECT calendar_date, total_steps FROM daily_summary LIMIT 3")
    assert "2026-11" in result
    assert "8000" in result


def test_run_sql_rejects_non_select(seeded_db):
    from garmin_local.mcp_server import run_sql
    result = run_sql("DROP TABLE activities")
    assert "Error" in result or "error" in result


def test_run_sql_rejects_multiple_statements(seeded_db):
    from garmin_local.mcp_server import run_sql
    result = run_sql("SELECT 1; DROP TABLE activities")
    assert "Error" in result or "error" in result


def test_run_sql_no_rows(seeded_db):
    from garmin_local.mcp_server import run_sql
    result = run_sql("SELECT * FROM activities WHERE activity_id = 99999")
    assert "No rows" in result or "No data" in result


def test_schema_resource(seeded_db):
    from garmin_local.mcp_server import schema_resource
    result = schema_resource()
    assert "activities" in result
    assert "daily_summary" in result
    assert "SELECT" in result
