"""Transform raw Garmin JSON payloads into typed Python dicts for DB insertion.

Units stored: distances in metres, durations in seconds, speed in m/s,
HR in bpm, HRV in ms, weight in kg, calories in kcal, stress/battery 0-100.
Timestamps: UTC ISO strings as TEXT; calendar_date as "YYYY-MM-DD".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _epoch_ms_to_iso(epoch_ms: int | float | None) -> str | None:
    """Convert Unix epoch milliseconds to UTC ISO string."""
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )


def normalize_activity(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a raw activity summary to the ``activities`` table row dict."""
    atype = raw.get("activityType") or {}
    start_local = raw.get("startTimeLocal", "")
    calendar_date = start_local[:10] if start_local else ""
    return {
        "activity_id": raw["activityId"],
        "activity_name": raw.get("activityName"),
        "activity_type": atype.get("typeKey", "unknown"),
        "start_time_gmt": raw.get("startTimeGMT", ""),
        "start_time_local": start_local,
        "calendar_date": calendar_date,
        "distance_m": raw.get("distance"),
        "duration_s": raw.get("duration"),
        "moving_duration_s": raw.get("movingDuration"),
        "elapsed_duration_s": raw.get("elapsedDuration"),
        "avg_speed_mps": raw.get("averageSpeed"),
        "calories_kcal": raw.get("calories"),
        "avg_hr_bpm": raw.get("averageHR"),
        "max_hr_bpm": raw.get("maxHR"),
        "steps": raw.get("steps"),
        "aerobic_te": raw.get("aerobicTrainingEffect"),
        "anaerobic_te": raw.get("anaerobicTrainingEffect"),
        "device_id": raw.get("deviceId"),
    }


def normalize_exercise_sets(
    activity_id: int, raw: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract strength_sets and exercise_set_exercises rows from exercise sets payload.

    Returns (sets_rows, exercises_rows).
    """
    sets_rows: list[dict[str, Any]] = []
    exercises_rows: list[dict[str, Any]] = []

    for es in raw.get("exerciseSets", []):
        msg_idx = es.get("messageIndex")
        sets_rows.append(
            {
                "activity_id": activity_id,
                "message_index": msg_idx,
                "set_type": es.get("setType", "ACTIVE"),
                "start_time_gmt": es.get("startTime"),
                "duration_s": es.get("duration"),
                "reps": es.get("repetitionCount"),
                "weight_kg": es.get("weight"),
            }
        )
        for rank, ex in enumerate(es.get("exercises", [])):
            exercises_rows.append(
                {
                    "activity_id": activity_id,
                    "message_index": msg_idx,
                    "rank": rank,
                    "category": ex.get("category", "UNKNOWN"),
                    "name": ex.get("name"),
                    "probability": ex.get("probability"),
                }
            )

    return sets_rows, exercises_rows


def normalize_daily_summary(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a raw daily summary to the ``daily_summary`` table row dict."""
    return {
        "calendar_date": raw.get("calendarDate", ""),
        "total_steps": raw.get("totalSteps"),
        "total_distance_m": raw.get("totalDistanceMeters"),
        "resting_hr_bpm": raw.get("restingHeartRate"),
        "min_hr_bpm": raw.get("minHeartRate"),
        "max_hr_bpm": raw.get("maxHeartRate"),
        "avg_stress": raw.get("averageStressLevel"),
        "max_stress": raw.get("maxStressLevel"),
        "body_battery_high": raw.get("bodyBatteryHighestValue"),
        "body_battery_low": raw.get("bodyBatteryLowestValue"),
        "body_battery_at_wake": raw.get("bodyBatteryAtWakeTime"),
        "body_battery_most_recent": raw.get("bodyBatteryMostRecentValue"),
        "total_kcal": raw.get("totalKilocalories"),
        "active_kcal": raw.get("activeKilocalories"),
        "bmr_kcal": raw.get("bmrKilocalories"),
        "highly_active_s": raw.get("highlyActiveSeconds"),
        "active_s": raw.get("activeSeconds"),
        "sedentary_s": raw.get("sedentarySeconds"),
        "sleeping_s": raw.get("sleepingSeconds"),
        "moderate_intensity_min": raw.get("moderateIntensityMinutes"),
        "vigorous_intensity_min": raw.get("vigorousIntensityMinutes"),
        "avg_spo2_pct": raw.get("averageSpo2"),
        "lowest_spo2_pct": raw.get("lowestSpo2"),
        "avg_respiration_brpm": raw.get("avgWakingRespirationValue"),
        "wellness_start_gmt": raw.get("wellnessStartTimeGmt"),
        "wellness_end_gmt": raw.get("wellnessEndTimeGmt"),
    }


def normalize_sleep(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Map a raw sleep payload to the ``sleep`` table row dict.

    Returns None if no sleep data present.
    """
    dto = raw.get("dailySleepDTO")
    if not dto:
        return None

    scores = dto.get("sleepScores") or {}
    overall = scores.get("overall") or {}

    return {
        "calendar_date": dto.get("calendarDate", ""),
        "sleep_start_gmt": _epoch_ms_to_iso(dto.get("sleepStartTimestampGMT")),
        "sleep_end_gmt": _epoch_ms_to_iso(dto.get("sleepEndTimestampGMT")),
        "total_sleep_s": dto.get("sleepTimeSeconds"),
        "deep_sleep_s": dto.get("deepSleepSeconds"),
        "light_sleep_s": dto.get("lightSleepSeconds"),
        "rem_sleep_s": dto.get("remSleepSeconds"),
        "awake_s": dto.get("awakeSleepSeconds"),
        "nap_s": dto.get("napTimeSeconds"),
        "awake_count": dto.get("awakeCount"),
        "sleep_score": overall.get("value"),
        "sleep_score_qualifier": overall.get("qualifierKey"),
        "avg_hr_bpm": dto.get("avgHeartRate"),
        "avg_spo2_pct": dto.get("averageSpO2Value"),
        "lowest_spo2_pct": dto.get("lowestSpO2Value"),
        "avg_respiration_brpm": dto.get("averageRespirationValue"),
        "avg_stress": dto.get("avgSleepStress"),
        "breathing_disruption": dto.get("breathingDisruptionSeverity"),
    }


def normalize_hrv(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Map a raw HRV day payload to the ``hrv`` table row dict."""
    summary = raw.get("hrvSummary")
    if not summary:
        return None

    baseline = summary.get("baseline") or {}
    return {
        "calendar_date": summary.get("calendarDate", ""),
        "weekly_avg_ms": summary.get("weeklyAvg"),
        "last_night_avg_ms": summary.get("lastNightAvg"),
        "last_night_5min_high_ms": summary.get("lastNight5MinHigh"),
        "baseline_low_ms": baseline.get("lowUpper"),
        "baseline_balanced_low_ms": baseline.get("balancedLow"),
        "baseline_balanced_high_ms": baseline.get("balancedUpper"),
        "status": summary.get("status"),
        "feedback_phrase": summary.get("feedbackPhrase"),
    }


def normalize_training_readiness(raw_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map a list of training readiness snapshots to ``training_readiness`` rows."""
    rows = []
    for item in raw_list:
        rows.append(
            {
                "calendar_date": item.get("calendarDate", ""),
                "timestamp_gmt": item.get("timestamp", ""),
                "input_context": item.get("inputContext"),
                "score": item.get("score"),
                "level": item.get("level"),
                "sleep_score": item.get("sleepScore"),
                "recovery_time_h": item.get("recoveryTime"),
                "acute_load": item.get("acuteLoad"),
                "hrv_weekly_avg_ms": item.get("hrvWeeklyAverage"),
                "sleep_score_factor_pct": item.get("sleepScoreFactorPercent"),
                "recovery_time_factor_pct": item.get("recoveryTimeFactorPercent"),
                "acwr_factor_pct": item.get("acwrFactorPercent"),
                "stress_history_factor_pct": item.get("stressHistoryFactorPercent"),
                "hrv_factor_pct": item.get("hrvFactorPercent"),
                "sleep_history_factor_pct": item.get("sleepHistoryFactorPercent"),
            }
        )
    return rows


def normalize_training_status(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Map a raw training status payload to the ``training_status`` table row dict.

    Uses the primary training device's data.
    """
    latest = raw.get("latestTrainingStatusData") or {}
    if not latest:
        return None

    # Find primary device entry
    device_data: dict[str, Any] | None = None
    for entry in latest.values():
        if isinstance(entry, dict) and entry.get("primaryTrainingDevice"):
            device_data = entry
            break
    if device_data is None and latest:
        device_data = next(iter(latest.values()))
    if not device_data:
        return None

    acwr = device_data.get("acuteTrainingLoadDTO") or {}
    return {
        "calendar_date": device_data.get("calendarDate", ""),
        "status_phrase": device_data.get("trainingStatusFeedbackPhrase"),
        "training_status_id": device_data.get("trainingStatus"),
        "fitness_trend": device_data.get("fitnessTrend"),
        "acwr_percent": acwr.get("acwrPercent"),
        "acwr_status": acwr.get("acwrStatus"),
        "acute_load": acwr.get("dailyTrainingLoadAcute"),
        "chronic_load_min": acwr.get("minTrainingLoadChronic"),
        "chronic_load_max": acwr.get("maxTrainingLoadChronic"),
        "acwr_ratio": acwr.get("dailyAcuteChronicWorkloadRatio"),
    }
