"""Tests for Phase 2: schema migrations, upsert idempotency, watermark logic."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from garmin_local.db import migrate, open_db
from garmin_local.normalize import (
    normalize_activity,
    normalize_daily_summary,
    normalize_exercise_sets,
    normalize_hrv,
    normalize_sleep,
    normalize_training_readiness,
)
from garmin_local.sync import get_watermark, run_sync, set_watermark

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path):
    conn = open_db(tmp_path / "test.db")
    migrate(conn)
    return conn


# ---------------------------------------------------------------------------
# Schema and migration
# ---------------------------------------------------------------------------


def test_migration_creates_tables(db):
    tables = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {
        "activities", "daily_summary", "sleep", "hrv",
        "training_readiness", "training_status", "strength_sets",
        "exercise_set_exercises", "body_composition",
        "raw_payloads", "sync_state",
    }
    assert expected.issubset(tables)


def test_migration_sets_user_version(db):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    assert version == 2


def test_migration_idempotent(db):
    migrate(db)  # second call must not raise or change version
    version = db.execute("PRAGMA user_version").fetchone()[0]
    assert version == 2


# ---------------------------------------------------------------------------
# Watermark
# ---------------------------------------------------------------------------


def test_watermark_none_on_first_run(db):
    assert get_watermark(db) is None


def test_watermark_roundtrip(db):
    d = date(2026, 11, 1)
    set_watermark(db, d)
    db.commit()
    assert get_watermark(db) == d


def test_watermark_update(db):
    set_watermark(db, date(2026, 11, 1))
    set_watermark(db, date(2026, 11, 20))
    db.commit()
    assert get_watermark(db) == date(2026, 11, 20)


# ---------------------------------------------------------------------------
# Normalize helpers
# ---------------------------------------------------------------------------


def test_normalize_activity():
    raw = {
        "activityId": 123,
        "activityName": "Morning Run",
        "activityType": {"typeKey": "running"},
        "startTimeLocal": "2026-11-20 07:30:00",
        "startTimeGMT": "2026-11-20 06:30:00",
        "distance": 10000.0,
        "duration": 3600.0,
        "movingDuration": 3550.0,
        "elapsedDuration": 3600.0,
        "averageSpeed": 2.78,
        "calories": 500.0,
        "averageHR": 145.0,
        "maxHR": 170.0,
        "steps": 9500,
        "aerobicTrainingEffect": 3.5,
        "anaerobicTrainingEffect": 1.0,
        "deviceId": 999,
    }
    row = normalize_activity(raw)
    assert row["activity_id"] == 123
    assert row["activity_type"] == "running"
    assert row["calendar_date"] == "2026-11-20"
    assert row["distance_m"] == 10000.0
    assert row["duration_s"] == 3600.0


def test_normalize_daily_summary():
    raw = {
        "calendarDate": "2026-11-20",
        "totalSteps": 8000,
        "totalDistanceMeters": 6400,
        "restingHeartRate": 48,
        "averageStressLevel": 25,
        "bodyBatteryHighestValue": 85,
        "bodyBatteryLowestValue": 32,
        "totalKilocalories": 2200.0,
        "activeKilocalories": 400.0,
        "bmrKilocalories": 1800.0,
    }
    row = normalize_daily_summary(raw)
    assert row["calendar_date"] == "2026-11-20"
    assert row["total_steps"] == 8000
    assert row["resting_hr_bpm"] == 48


def test_normalize_sleep_extracts_dto():
    raw = {
        "dailySleepDTO": {
            "calendarDate": "2026-11-20",
            "sleepStartTimestampGMT": 1763996400000,
            "sleepEndTimestampGMT": 1764025200000,
            "sleepTimeSeconds": 28800,
            "deepSleepSeconds": 5400,
            "lightSleepSeconds": 14400,
            "remSleepSeconds": 7200,
            "awakeSleepSeconds": 1800,
            "napTimeSeconds": 0,
            "awakeCount": 3,
            "sleepScores": {"overall": {"value": 78, "qualifierKey": "GOOD"}},
            "avgHeartRate": 52.0,
            "averageSpO2Value": 96.5,
            "lowestSpO2Value": 93,
            "averageRespirationValue": 14.2,
            "avgSleepStress": 20.0,
            "breathingDisruptionSeverity": "NONE",
        }
    }
    row = normalize_sleep(raw)
    assert row is not None
    assert row["calendar_date"] == "2026-11-20"
    assert row["total_sleep_s"] == 28800
    assert row["sleep_score"] == 78
    assert row["sleep_score_qualifier"] == "GOOD"
    assert row["sleep_start_gmt"] is not None


def test_normalize_sleep_returns_none_when_empty():
    assert normalize_sleep({}) is None
    assert normalize_sleep({"dailySleepDTO": None}) is None


def test_normalize_hrv():
    raw = {
        "hrvSummary": {
            "calendarDate": "2026-11-20",
            "weeklyAvg": 55,
            "lastNightAvg": 58,
            "lastNight5MinHigh": 72,
            "baseline": {"lowUpper": 45, "balancedLow": 50, "balancedUpper": 65},
            "status": "BALANCED",
            "feedbackPhrase": "HRV_BALANCED_1",
        }
    }
    row = normalize_hrv(raw)
    assert row is not None
    assert row["calendar_date"] == "2026-11-20"
    assert row["weekly_avg_ms"] == 55
    assert row["status"] == "BALANCED"


def test_normalize_exercise_sets():
    raw = {
        "exerciseSets": [
            {
                "messageIndex": 0,
                "setType": "ACTIVE",
                "startTime": "2026-11-20T09:00:00.0",
                "duration": 45.0,
                "repetitionCount": 10,
                "weight": None,
                "exercises": [
                    {"category": "PULL_UP", "name": "LAT_PULLDOWN", "probability": 95.0}
                ],
            },
            {
                "messageIndex": 1,
                "setType": "REST",
                "startTime": "2026-11-20T09:00:45.0",
                "duration": 60.0,
                "repetitionCount": None,
                "weight": None,
                "exercises": [],
            },
        ]
    }
    sets, exercises = normalize_exercise_sets(123, raw)
    assert len(sets) == 2
    assert sets[0]["set_type"] == "ACTIVE"
    assert sets[0]["reps"] == 10
    assert sets[1]["set_type"] == "REST"
    assert len(exercises) == 1
    assert exercises[0]["category"] == "PULL_UP"
    assert exercises[0]["rank"] == 0


def test_normalize_training_readiness():
    raw_list = [
        {
            "calendarDate": "2026-11-20",
            "timestamp": "2026-11-20T07:30:00.0",
            "inputContext": "AFTER_WAKEUP_RESET",
            "score": 72,
            "level": "HIGH",
            "sleepScore": 78,
            "recoveryTime": 0,
            "acuteLoad": 350,
            "hrvWeeklyAverage": 55,
            "sleepScoreFactorPercent": 80,
            "recoveryTimeFactorPercent": 90,
            "acwrFactorPercent": 70,
            "stressHistoryFactorPercent": 65,
            "hrvFactorPercent": 75,
            "sleepHistoryFactorPercent": 68,
        }
    ]
    rows = normalize_training_readiness(raw_list)
    assert len(rows) == 1
    assert rows[0]["score"] == 72
    assert rows[0]["input_context"] == "AFTER_WAKEUP_RESET"


# ---------------------------------------------------------------------------
# Upsert idempotency
# ---------------------------------------------------------------------------


def test_upsert_activity_idempotent(db):
    raw = {
        "activityId": 1001,
        "activityName": "Easy Run",
        "activityType": {"typeKey": "running"},
        "startTimeLocal": "2026-11-20 07:00:00",
        "startTimeGMT": "2026-11-20 06:00:00",
        "distance": 5000.0,
        "duration": 1800.0,
        "movingDuration": None,
        "elapsedDuration": None,
        "averageSpeed": 2.78,
        "calories": 300.0,
        "averageHR": 140.0,
        "maxHR": 165.0,
        "steps": 4500,
        "aerobicTrainingEffect": 2.5,
        "anaerobicTrainingEffect": 0.5,
        "deviceId": 999,
    }
    from garmin_local.sync import _upsert
    row = normalize_activity(raw)
    _upsert(db, "activities", row)
    db.commit()
    _upsert(db, "activities", row)  # second insert — must not raise or duplicate
    db.commit()
    count = db.execute("SELECT COUNT(*) FROM activities WHERE activity_id=1001").fetchone()[0]
    assert count == 1


def test_upsert_daily_summary_updates_value(db):
    from garmin_local.sync import _upsert
    row1 = normalize_daily_summary({
        "calendarDate": "2026-11-20", "totalSteps": 5000, "restingHeartRate": 50
    })
    _upsert(db, "daily_summary", row1)
    db.commit()
    # Same date, updated steps
    row2 = normalize_daily_summary({
        "calendarDate": "2026-11-20", "totalSteps": 8000, "restingHeartRate": 48
    })
    _upsert(db, "daily_summary", row2)
    db.commit()
    result = db.execute(
        "SELECT total_steps FROM daily_summary WHERE calendar_date='2026-11-20'"
    ).fetchone()
    assert result[0] == 8000


# ---------------------------------------------------------------------------
# Full sync idempotency (mock API)
# ---------------------------------------------------------------------------


def _make_mock_api(start: date, end: date):
    """Build a MagicMock Garmin API returning minimal synthetic fixtures."""
    api = MagicMock()
    dates = [(start + timedelta(days=i)) for i in range((end - start).days + 1)]
    date_strs = [str(d) for d in dates]

    api.get_activities_by_date.return_value = [
        {
            "activityId": 9001,
            "activityName": "Test Run",
            "activityType": {"typeKey": "running"},
            "startTimeLocal": f"{date_strs[0]} 07:00:00",
            "startTimeGMT": f"{date_strs[0]} 06:00:00",
            "distance": 5000.0,
            "duration": 1800.0,
            "movingDuration": 1780.0,
            "elapsedDuration": 1800.0,
            "averageSpeed": 2.78,
            "calories": 300.0,
            "averageHR": 140.0,
            "maxHR": 165.0,
            "steps": 4500,
            "aerobicTrainingEffect": 2.5,
            "anaerobicTrainingEffect": 0.5,
            "deviceId": 999,
        }
    ]

    def mock_get_stats(d):
        return {
            "calendarDate": d,
            "totalSteps": 8000,
            "restingHeartRate": 50,
            "totalDistanceMeters": 6400,
        }

    api.get_stats.side_effect = mock_get_stats

    def mock_sleep(d, **kwargs):
        return {
            "dailySleepDTO": {
                "calendarDate": d,
                "sleepStartTimestampGMT": 1763996400000,
                "sleepEndTimestampGMT": 1764025200000,
                "sleepTimeSeconds": 28800,
                "deepSleepSeconds": 5400,
                "lightSleepSeconds": 14400,
                "remSleepSeconds": 7200,
                "awakeSleepSeconds": 1800,
                "napTimeSeconds": 0,
                "awakeCount": 3,
                "sleepScores": {"overall": {"value": 75, "qualifierKey": "GOOD"}},
                "avgHeartRate": 52.0,
                "averageSpO2Value": 96.0,
                "lowestSpO2Value": 93,
                "averageRespirationValue": 14.0,
                "avgSleepStress": 22.0,
                "breathingDisruptionSeverity": "NONE",
            }
        }

    api.get_daily_sleep.side_effect = mock_sleep

    api.get_hrv_data_range.return_value = {
        "hrvSummaries": [
            {
                "calendarDate": d,
                "weeklyAvg": 55,
                "lastNightAvg": 58,
                "lastNight5MinHigh": 72,
                "baseline": {"lowUpper": 45, "balancedLow": 50, "balancedUpper": 65},
                "status": "BALANCED",
                "feedbackPhrase": "HRV_BALANCED_1",
            }
            for d in date_strs
        ]
    }

    def mock_readiness(d):
        return [
            {
                "calendarDate": d,
                "timestamp": f"{d}T07:30:00.0",
                "inputContext": "AFTER_WAKEUP_RESET",
                "score": 70,
                "level": "HIGH",
                "sleepScore": 75,
                "recoveryTime": 0,
                "acuteLoad": 300,
                "hrvWeeklyAverage": 55,
                "sleepScoreFactorPercent": 80,
                "recoveryTimeFactorPercent": 90,
                "acwrFactorPercent": 70,
                "stressHistoryFactorPercent": 65,
                "hrvFactorPercent": 75,
                "sleepHistoryFactorPercent": 68,
            }
        ]

    api.get_training_readiness.side_effect = mock_readiness

    def mock_training_status(d):
        return {
            "latestTrainingStatusData": {
                "999": {
                    "calendarDate": d,
                    "trainingStatus": 4,
                    "fitnessTrend": 2,
                    "trainingStatusFeedbackPhrase": "MAINTAINING_1",
                    "primaryTrainingDevice": True,
                    "acuteTrainingLoadDTO": {
                        "acwrPercent": 80,
                        "acwrStatus": "OPTIMAL",
                        "dailyTrainingLoadAcute": 350,
                        "minTrainingLoadChronic": 300.0,
                        "maxTrainingLoadChronic": 450.0,
                        "dailyAcuteChronicWorkloadRatio": 0.85,
                    },
                }
            }
        }

    api.get_daily_training_status.side_effect = mock_training_status

    return api


def test_sync_first_run(db, monkeypatch):
    monkeypatch.setattr("garmin_local.sync.SLEEP_MIN", 0)
    monkeypatch.setattr("garmin_local.sync.SLEEP_MAX", 0)

    today = date(2026, 11, 20)
    start = today - timedelta(days=3)
    api = _make_mock_api(start, today)

    run_sync(db, api, force=True, backfill_days=3)

    assert get_watermark(db) == date.today()
    assert db.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM daily_summary").fetchone()[0] >= 1
    assert db.execute("SELECT COUNT(*) FROM sleep").fetchone()[0] >= 1
    assert db.execute("SELECT COUNT(*) FROM hrv").fetchone()[0] >= 1


def test_sync_idempotent(db, monkeypatch):
    monkeypatch.setattr("garmin_local.sync.SLEEP_MIN", 0)
    monkeypatch.setattr("garmin_local.sync.SLEEP_MAX", 0)

    today = date(2026, 11, 20)
    start = today - timedelta(days=3)
    api = _make_mock_api(start, today)

    run_sync(db, api, force=True, backfill_days=3)
    count_after_first = db.execute("SELECT COUNT(*) FROM activities").fetchone()[0]

    run_sync(db, api, force=True, backfill_days=3)
    count_after_second = db.execute("SELECT COUNT(*) FROM activities").fetchone()[0]

    assert count_after_first == count_after_second


def test_sync_respects_watermark_cadence(db, monkeypatch):
    monkeypatch.setattr("garmin_local.sync.SLEEP_MIN", 0)
    monkeypatch.setattr("garmin_local.sync.SLEEP_MAX", 0)

    today = date(2026, 11, 20)
    # Set watermark to recent date — sync should skip
    set_watermark(db, today - timedelta(days=2))
    db.commit()

    api = MagicMock()
    run_sync(db, api, force=False, backfill_days=90)

    # API should not have been called
    api.get_activities_by_date.assert_not_called()


def test_sync_force_bypasses_watermark(db, monkeypatch):
    monkeypatch.setattr("garmin_local.sync.SLEEP_MIN", 0)
    monkeypatch.setattr("garmin_local.sync.SLEEP_MAX", 0)

    today = date(2026, 11, 20)
    set_watermark(db, today - timedelta(days=2))
    db.commit()

    start = today - timedelta(days=7)
    api = _make_mock_api(start, today)

    run_sync(db, api, force=True, backfill_days=90)
    api.get_activities_by_date.assert_called_once()
