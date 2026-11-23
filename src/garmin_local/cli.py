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
    typer.echo("[stub] login: not yet implemented")
    raise typer.Exit(code=1)


@app.command()
def spike() -> None:
    """Explore Garmin endpoints and dump raw responses to data/raw/."""
    typer.echo("[stub] spike: not yet implemented")
    raise typer.Exit(code=1)


@app.command()
def sync(
    now: bool = typer.Option(False, "--now", help="Force sync regardless of watermark."),
    backfill_days: int = typer.Option(90, "--backfill-days", help="Days to backfill on first run."),
) -> None:
    """Watermark sync: pull new data from Garmin into the local database."""
    typer.echo("[stub] sync: not yet implemented")
    raise typer.Exit(code=1)


@app.command()
def serve() -> None:
    """Start the MCP server over stdio."""
    typer.echo("[stub] serve: not yet implemented")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
