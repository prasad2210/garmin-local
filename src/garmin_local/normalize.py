"""Transform raw Garmin JSON payloads into typed Python dicts for DB insertion."""

from __future__ import annotations

from typing import Any


def normalize_activity(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a raw activity payload to the ``activities`` table row dict.

    Units: distances in metres, durations in seconds, speed in m/s.
    """
    raise NotImplementedError("Phase 2")


def normalize_daily_summary(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a raw daily summary payload to the ``daily_summary`` table row dict."""
    raise NotImplementedError("Phase 2")
