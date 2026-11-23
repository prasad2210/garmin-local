"""CLI entry point: garmin-local login | spike | sync | serve."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="garmin-local",
    help="Pull Garmin Connect data into SQLite and expose via MCP.",
    add_completion=False,
)


@app.command()
def login() -> None:
    """Interactive first login -- saves tokens to ~/.garminconnect."""
    from garmin_local.auth import get_token_store, login_interactive

    email = typer.prompt("Garmin Connect email")
    password = typer.prompt("Garmin Connect password", hide_input=True)
    token_store = get_token_store()
    login_interactive(email, password, token_store)


@app.command()
def spike() -> None:
    """Explore Garmin endpoints and dump raw responses to data/raw/."""
    from garmin_local.auth import get_client, get_token_store
    from garmin_local.spike import run_spike

    token_store = get_token_store()
    api = get_client(token_store)
    run_spike(api)


@app.command()
def sync(
    now: bool = typer.Option(False, "--now", help="Force sync regardless of watermark."),
    backfill_days: int = typer.Option(90, "--backfill-days", help="Days to backfill on first run."),
) -> None:
    """Watermark sync: pull new data from Garmin into the local database."""
    import logging
    import os
    from pathlib import Path

    from garmin_local.auth import get_client, get_token_store
    from garmin_local.db import migrate, open_db
    from garmin_local.sync import run_sync

    log_path = Path(os.environ.get("GARMIN_LOG_PATH", "data/sync.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
    )

    db_path = Path(os.environ.get("GARMIN_DB_PATH", "data/garmin.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = open_db(db_path)
    migrate(conn)

    token_store = get_token_store()
    api = get_client(token_store)

    run_sync(conn, api, force=now, backfill_days=backfill_days)
    conn.close()


@app.command()
def serve() -> None:
    """Start the MCP server over stdio."""
    typer.echo("[stub] serve: not yet implemented")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
