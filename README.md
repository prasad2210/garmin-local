# garmin-local

Pull Garmin Connect data into a local SQLite database and expose it via an MCP server.

## Setup

```bash
uv sync
```

## Usage

```bash
# Show all commands
uv run garmin-local --help

# Run tests
uv run pytest

# Lint / format check
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

## Phases

- **Phase 0** (current): repo scaffold, CLI wires up, tests pass
- **Phase 1**: spike explorer, login, raw data dump to `data/raw/`, findings doc
- **Phase 2**: schema, watermark sync, upserts
- **Phase 3**: MCP server
