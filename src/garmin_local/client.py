"""Thin Garmin Connect client wrapper: rate limiting, backoff, error mapping."""

from __future__ import annotations

from typing import Any


class GarminClient:
    """Wraps a garminconnect.Garmin instance with rate limiting and backoff."""

    def __init__(self, raw_client: object) -> None:
        self._client = raw_client

    def get(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Call *method_name* on the underlying client with rate limiting."""
        raise NotImplementedError("Phase 1")
