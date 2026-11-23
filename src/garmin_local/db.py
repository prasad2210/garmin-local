"""SQLite schema and migrations using PRAGMA user_version."""

from __future__ import annotations

import sqlite3
from pathlib import Path

CURRENT_SCHEMA_VERSION = 0


def open_db(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open (or create) the SQLite database at *path*.

    Uses WAL mode for write connections. Read-only connections use the
    ``mode=ro`` URI flag per hard rules.
    """
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Apply any pending schema migrations."""
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == CURRENT_SCHEMA_VERSION:
        return
    raise NotImplementedError("Phase 2")
