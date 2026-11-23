#!/usr/bin/env python
"""Phase 1 spike: explore Garmin endpoints and dump raw responses.

Run via:
    uv run garmin-local spike

Dumps JSON to data/raw/<endpoint>/<date>.json and prints a summary table.
"""

from __future__ import annotations

import json
import random
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DAYS_BACK = 7
RAW_DIR = Path("data/raw")
SLEEP_MIN = 1.0
SLEEP_MAX = 2.0


def _sleep() -> None:
    time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))


def _save(endpoint: str, key: str, payload: Any) -> Path:
    """Dump *payload* to data/raw/<endpoint>/<key>.json. Returns the path."""
    out_dir = RAW_DIR / endpoint
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{key}.json"
    with out_path.open("w") as f:
        json.dump(payload, f, indent=2, default=str)
    return out_path


def _top_keys(payload: Any) -> str:
    """Return a short string describing the top-level keys of *payload*."""
    if isinstance(payload, dict):
        keys = list(payload.keys())
        preview = ", ".join(keys[:6])
        return f"{{{preview}{'...' if len(keys) > 6 else ''}}}"
    if isinstance(payload, list):
        return f"[list len={len(payload)}]"
    return type(payload).__name__


# ---------------------------------------------------------------------------
# Main spike runner
# ---------------------------------------------------------------------------

def run_spike(api: Any) -> None:
    today = date.today()
    start = today - timedelta(days=DAYS_BACK)
    start_str = str(start)
    today_str = str(today)

    rows: list[tuple[str, str, bool, str]] = []  # endpoint, key, ok, top_keys

    def probe(endpoint: str, key: str, fn, *args, **kwargs):
        """Call fn(*args, **kwargs), save result, record outcome."""
        try:
            result = fn(*args, **kwargs)
            _save(endpoint, key, result)
            rows.append((endpoint, key, True, _top_keys(result)))
            return result
        except Exception as exc:
            rows.append((endpoint, key, False, f"ERROR: {exc}"))
            return None
        finally:
            _sleep()

    # ------------------------------------------------------------------
    # Daily wellness — iterate last 7 days for context
    # ------------------------------------------------------------------
    for d in [str(today - timedelta(days=i)) for i in range(DAYS_BACK, -1, -1)]:
        probe("daily_summary", d, api.get_stats, d)

    _sleep()
    probe("resting_hr_range", f"{start_str}_{today_str}",
          api.get_rhr_daily, start_str, today_str)

    for d in [str(today - timedelta(days=i)) for i in range(DAYS_BACK, -1, -1)]:
        probe("stress", d, api.get_stress_data, d)

    probe("body_battery_range", f"{start_str}_{today_str}",
          api.get_body_battery, start_str, today_str)

    # ------------------------------------------------------------------
    # Sleep and recovery
    # ------------------------------------------------------------------
    for d in [str(today - timedelta(days=i)) for i in range(DAYS_BACK, -1, -1)]:
        probe("sleep", d, api.get_daily_sleep, d)

    probe("hrv_range", f"{start_str}_{today_str}",
          api.get_hrv_data_range, start_str, today_str)

    for d in [str(today - timedelta(days=i)) for i in range(DAYS_BACK, -1, -1)]:
        probe("hrv_day", d, api.get_hrv_data, d)

    probe("training_readiness_range", f"{start_str}_{today_str}",
          api.get_training_readiness_range, start_str, today_str)

    for d in [str(today - timedelta(days=i)) for i in range(DAYS_BACK, -1, -1)]:
        probe("training_readiness_day", d, api.get_training_readiness, d)
        probe("training_status_day", d, api.get_daily_training_status, d)

    # ------------------------------------------------------------------
    # Activities
    # ------------------------------------------------------------------
    activities_raw = probe("activities_by_date", f"{start_str}_{today_str}",
                           api.get_activities_by_date, start_str, today_str)

    activities = activities_raw if isinstance(activities_raw, list) else []

    # Find one run and one strength session for detailed probes
    run_activity = None
    strength_activity = None
    for act in activities:
        atype = str(act.get("activityType", {}).get("typeKey", "")).lower()
        if run_activity is None and "run" in atype:
            run_activity = act
        if strength_activity is None and atype in ("strength_training", "fitness_equipment"):
            strength_activity = act

    if run_activity:
        aid = run_activity["activityId"]
        probe("activity_detail_run", str(aid), api.get_activity_details, aid)
        probe("activity_splits_run", str(aid), api.get_activity_splits, aid)
        probe("activity_laps_run", str(aid), api.get_activity_laps, aid)
    else:
        rows.append(("activity_detail_run", "n/a", False, "No run found in last 7 days"))
        rows.append(("activity_splits_run", "n/a", False, "No run found in last 7 days"))

    if strength_activity:
        aid = strength_activity["activityId"]
        probe("activity_detail_strength", str(aid), api.get_activity_details, aid)
        probe("activity_exercise_sets", str(aid), api.get_activity_exercise_sets, aid)
    else:
        rows.append(("activity_exercise_sets", "n/a", False, "No strength session in last 7 days"))

    # ------------------------------------------------------------------
    # Body composition and VO2max
    # ------------------------------------------------------------------
    probe("body_composition", f"{start_str}_{today_str}",
          api.get_body_composition, start_str, today_str)

    probe("max_metrics_latest", today_str, api.get_max_metrics_latest, today_str)

    for d in [str(today - timedelta(days=i)) for i in range(DAYS_BACK, -1, -1)]:
        probe("max_metrics_day", d, api.get_max_metrics, d)

    probe("current_biometrics", "latest", api.get_current_biometrics)

    # Device info (once)
    probe("devices", "list", api.get_devices)

    # ------------------------------------------------------------------
    # Print summary table
    # ------------------------------------------------------------------
    print()
    print(f"{'Endpoint':<35} {'Key':<28} {'OK':>4}  Top-level keys")
    print("-" * 100)
    for endpoint, key, ok, keys_str in rows:
        ok_marker = "YES" if ok else " NO"
        print(f"{endpoint:<35} {key:<28} {ok_marker:>4}  {keys_str}")
    print()
    print(f"Raw responses saved to {RAW_DIR}/")
    print()

    n_ok = sum(1 for _, _, ok, _ in rows if ok)
    print(f"Summary: {n_ok}/{len(rows)} endpoints returned data.")
