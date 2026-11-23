"""SQLite schema and migrations using PRAGMA user_version."""

from __future__ import annotations

import sqlite3
from pathlib import Path

CURRENT_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_V1 = """
-- Raw payloads: source of truth for re-parsing
CREATE TABLE IF NOT EXISTS raw_payloads (
    endpoint      TEXT NOT NULL,
    date_key      TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,  -- UTC ISO
    payload       TEXT NOT NULL,  -- JSON
    PRIMARY KEY (endpoint, date_key)
);

-- Sync watermark
CREATE TABLE IF NOT EXISTS sync_state (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL
);

-- Activities (all types)
CREATE TABLE IF NOT EXISTS activities (
    activity_id             INTEGER PRIMARY KEY,
    activity_name           TEXT,
    activity_type           TEXT NOT NULL,
    start_time_gmt          TEXT NOT NULL,  -- UTC ISO "YYYY-MM-DD HH:MM:SS"
    start_time_local        TEXT NOT NULL,
    calendar_date           TEXT NOT NULL,  -- "YYYY-MM-DD" of local start
    distance_m              REAL,           -- metres
    duration_s              REAL,           -- seconds
    moving_duration_s       REAL,           -- seconds
    elapsed_duration_s      REAL,           -- seconds
    avg_speed_mps           REAL,           -- m/s
    calories_kcal           REAL,
    avg_hr_bpm              REAL,
    max_hr_bpm              REAL,
    steps                   INTEGER,
    aerobic_te              REAL,           -- aerobic training effect 0-5
    anaerobic_te            REAL,           -- anaerobic training effect 0-5
    device_id               INTEGER
);

CREATE INDEX IF NOT EXISTS idx_activities_date ON activities (calendar_date);
CREATE INDEX IF NOT EXISTS idx_activities_type ON activities (activity_type);

-- Strength exercise sets (one row per set per activity)
CREATE TABLE IF NOT EXISTS strength_sets (
    activity_id         INTEGER NOT NULL REFERENCES activities (activity_id),
    message_index       INTEGER NOT NULL,
    set_type            TEXT NOT NULL,      -- "ACTIVE" or "REST"
    start_time_gmt      TEXT,               -- "YYYY-MM-DDTHH:MM:SS.s"
    duration_s          REAL,
    reps                INTEGER,
    weight_kg           REAL,               -- null = no sensor/manual entry
    PRIMARY KEY (activity_id, message_index)
);

-- Exercise classifications within each set (top classification candidate)
CREATE TABLE IF NOT EXISTS exercise_set_exercises (
    activity_id     INTEGER NOT NULL,
    message_index   INTEGER NOT NULL,
    rank            INTEGER NOT NULL,       -- 0 = highest probability
    category        TEXT NOT NULL,          -- e.g. "PULL_UP"
    name            TEXT,                   -- subcategory/variant, nullable
    probability     REAL,
    PRIMARY KEY (activity_id, message_index, rank),
    FOREIGN KEY (activity_id, message_index) REFERENCES strength_sets (activity_id, message_index)
);

-- Daily wellness summary
CREATE TABLE IF NOT EXISTS daily_summary (
    calendar_date               TEXT PRIMARY KEY,  -- "YYYY-MM-DD"
    total_steps                 INTEGER,
    total_distance_m            INTEGER,
    resting_hr_bpm              INTEGER,
    min_hr_bpm                  INTEGER,
    max_hr_bpm                  INTEGER,
    avg_stress                  INTEGER,            -- 0-100
    max_stress                  INTEGER,
    body_battery_high           INTEGER,            -- 0-100
    body_battery_low            INTEGER,
    body_battery_at_wake        INTEGER,
    body_battery_most_recent    INTEGER,
    total_kcal                  REAL,
    active_kcal                 REAL,
    bmr_kcal                    REAL,
    highly_active_s             INTEGER,
    active_s                    INTEGER,
    sedentary_s                 INTEGER,
    sleeping_s                  INTEGER,
    moderate_intensity_min      INTEGER,
    vigorous_intensity_min      INTEGER,
    avg_spo2_pct                REAL,
    lowest_spo2_pct             REAL,
    avg_respiration_brpm        REAL,
    wellness_start_gmt          TEXT,
    wellness_end_gmt            TEXT
);

-- Sleep
CREATE TABLE IF NOT EXISTS sleep (
    calendar_date               TEXT PRIMARY KEY,  -- "YYYY-MM-DD" of sleep night
    sleep_start_gmt             TEXT,              -- UTC ISO
    sleep_end_gmt               TEXT,              -- UTC ISO
    total_sleep_s               INTEGER,
    deep_sleep_s                INTEGER,
    light_sleep_s               INTEGER,
    rem_sleep_s                 INTEGER,
    awake_s                     INTEGER,
    nap_s                       INTEGER,
    awake_count                 INTEGER,
    sleep_score                 INTEGER,           -- 0-100
    sleep_score_qualifier       TEXT,              -- e.g. "GOOD"
    avg_hr_bpm                  REAL,
    avg_spo2_pct                REAL,
    lowest_spo2_pct             INTEGER,
    avg_respiration_brpm        REAL,
    avg_stress                  REAL,
    breathing_disruption        TEXT               -- e.g. "NONE"
);

-- HRV (nightly summary)
CREATE TABLE IF NOT EXISTS hrv (
    calendar_date       TEXT PRIMARY KEY,  -- "YYYY-MM-DD"
    weekly_avg_ms       INTEGER,           -- rolling 7-day avg, RMSSD
    last_night_avg_ms   INTEGER,
    last_night_5min_high_ms INTEGER,
    baseline_low_ms     INTEGER,
    baseline_balanced_low_ms  INTEGER,
    baseline_balanced_high_ms INTEGER,
    status              TEXT,              -- e.g. "BALANCED"
    feedback_phrase     TEXT
);

-- Training readiness (multiple snapshots per day)
CREATE TABLE IF NOT EXISTS training_readiness (
    calendar_date               TEXT NOT NULL,
    timestamp_gmt               TEXT NOT NULL,     -- "YYYY-MM-DDTHH:MM:SS.s"
    input_context               TEXT,              -- e.g. "AFTER_WAKEUP_RESET"
    score                       INTEGER,           -- 0-100
    level                       TEXT,              -- "LOW"/"MODERATE"/"HIGH"
    sleep_score                 INTEGER,
    recovery_time_h             INTEGER,           -- hours
    acute_load                  INTEGER,
    hrv_weekly_avg_ms           INTEGER,
    sleep_score_factor_pct      INTEGER,
    recovery_time_factor_pct    INTEGER,
    acwr_factor_pct             INTEGER,
    stress_history_factor_pct   INTEGER,
    hrv_factor_pct              INTEGER,
    sleep_history_factor_pct    INTEGER,
    PRIMARY KEY (calendar_date, timestamp_gmt)
);

-- Training status (one row per day, primary device)
CREATE TABLE IF NOT EXISTS training_status (
    calendar_date           TEXT PRIMARY KEY,
    status_phrase           TEXT,              -- e.g. "MAINTAINING_1"
    training_status_id      INTEGER,
    fitness_trend           INTEGER,
    acwr_percent            INTEGER,
    acwr_status             TEXT,
    acute_load              INTEGER,
    chronic_load_min        REAL,
    chronic_load_max        REAL,
    acwr_ratio              REAL
);

-- Body composition (from smart scale — empty for this user currently)
CREATE TABLE IF NOT EXISTS body_composition (
    calendar_date       TEXT PRIMARY KEY,
    weight_kg           REAL,
    bmi                 REAL,
    body_fat_pct        REAL,
    muscle_mass_kg      REAL,
    bone_mass_kg        REAL,
    body_water_pct      REAL,
    visceral_fat        REAL,
    metabolic_age       INTEGER
);
"""


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def open_db(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open (or create) the SQLite database at *path*.

    Uses WAL mode for write connections. Read-only connections use the
    ``mode=ro`` URI flag per hard rules.
    """
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Apply any pending schema migrations."""
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= CURRENT_SCHEMA_VERSION:
        return
    if version < 1:
        conn.executescript(_SCHEMA_V1)
        conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        conn.commit()
