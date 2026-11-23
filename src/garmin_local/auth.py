"""Token-store login: interactive first login and token reuse."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import garminconnect

TOKEN_STORE_DEFAULT = Path.home() / ".garminconnect"


def get_token_store() -> Path:
    """Return the path to the garminconnect token directory."""
    return Path(os.environ.get("GARMIN_TOKEN_STORE", str(TOKEN_STORE_DEFAULT)))


def login_interactive(email: str, password: str, token_store: Path) -> None:
    """First-run interactive login. Saves tokens to *token_store*.

    Prompts for MFA via stdin. Never retries in a loop.
    Raises SystemExit(1) on failure.
    """
    import garminconnect

    token_store.mkdir(parents=True, exist_ok=True)

    def prompt_mfa() -> str:
        return input("Enter MFA/2FA code: ").strip()

    api = garminconnect.Garmin(email=email, password=password, prompt_mfa=prompt_mfa)
    try:
        api.login(tokenstore=str(token_store))
    except garminconnect.GarminConnectAuthenticationError as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        print("Check your credentials and try again.", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Login error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Login successful. Tokens saved to {token_store}/")


def get_client(token_store: Path) -> garminconnect.Garmin:
    """Return an authenticated Garmin client using stored tokens.

    Raises SystemExit(1) with a clear message on auth failure.
    Never retries. Caller should not catch SystemExit.
    """
    import garminconnect

    token_file = token_store / "garmin_tokens.json"
    if not token_file.exists():
        print(
            f"No token file found at {token_file}.\n"
            "Run `garmin-local login` first.",
            file=sys.stderr,
        )
        sys.exit(1)

    api = garminconnect.Garmin()
    try:
        api.login(tokenstore=str(token_store))
    except garminconnect.GarminConnectAuthenticationError as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        print("Run `garmin-local login` to refresh your tokens.", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Failed to connect to Garmin: {exc}", file=sys.stderr)
        sys.exit(1)

    return api
