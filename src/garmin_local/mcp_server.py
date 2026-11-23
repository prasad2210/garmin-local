"""MCP server exposing read-only Garmin data via MCP stdio transport."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    "garmin-local",
    instructions="Read-only access to your local Garmin Connect SQLite database.",
)


@mcp.tool()
def sync_status() -> str:
    """Return last sync timestamp and row counts for each table."""
    raise NotImplementedError("Phase 3")


@mcp.tool()
def run_sql(query: str) -> str:
    """Execute a read-only SELECT query. Max 200 rows returned."""
    raise NotImplementedError("Phase 3")


def serve() -> None:
    """Start the MCP server over stdio."""
    mcp.run(transport="stdio")
