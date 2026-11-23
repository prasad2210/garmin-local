"""Token-store login: interactive first login and token reuse."""

from __future__ import annotations

import os
from pathlib import Path

TOKEN_STORE_DEFAULT = Path.home() / ".garminconnect"


def get_token_store() -> Path:
    """Return the path to the garminconnect token directory."""
    return Path(os.environ.get("GARMIN_TOKEN_STORE", str(TOKEN_STORE_DEFAULT)))


def login_interactive(email: str, password: str, token_store: Path) -> None:
    """First-run interactive login. Saves tokens to *token_store*.

    Raises RuntimeError on failure. Never retries in a loop.
    """
    raise NotImplementedError("Phase 1")


def get_client(token_store: Path) -> object:
    """Return an authenticated Garmin client using stored tokens.

    Raises SystemExit(1) with a clear message on auth failure --
    never retries. Caller should not catch SystemExit.
    Tell the user to re-run `garmin-local login` on failure.
    """
    raise NotImplementedError("Phase 1")
