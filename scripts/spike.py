#!/usr/bin/env python
"""Phase 1 spike shim — delegates to garmin_local.spike.

Run via:
    uv run garmin-local spike
or directly:
    uv run python scripts/spike.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from garmin_local.auth import get_client, get_token_store
from garmin_local.spike import run_spike

if __name__ == "__main__":
    api = get_client(get_token_store())
    run_spike(api)
