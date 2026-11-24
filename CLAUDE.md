# CLAUDE.md — garmin-local

## Goal

Pull my Garmin Connect data on a weekly schedule into a **local SQLite database**, then expose it to any LLM through an **MCP server** (later: a code-writing analysis agent) so I can get insights and data previews from my own training data.

Work **phase by phase** (see "Phases"). Finish a phase, summarize what you built and how to run it, then **stop and wait for my go-ahead** before starting the next one.

## Context

- Device: **Garmin Forerunner 965**. Activity mix: running and gym strength sessions, plus other sports. Store unknown activity types generically; never assume running-only.
- Developer: experienced backend engineer (Java / Spring Boot, Postgres, Kafka). Skip general engineering explanations; briefly flag Python-specific idioms and tooling choices.
- This is personal health/fitness data. It stays on this machine.
- Strava is out of scope for now. Strava has its own official MCP connector, and its API terms restrict feeding API data to AI apps. **Do not call the Strava REST API.**

## Decisions already made (don't re-litigate)

- Source: Garmin Connect via the unofficial `python-garminconnect` library (cyberjunky).
- Storage: **SQLite, WAL mode**, plain `sqlite3` from the stdlib (no ORM).
- Cadence: weekly pull. Cadence must be a config value so it can become daily later.
- Interface: MCP server over **stdio** using the official `mcp` Python SDK (FastMCP).
- UTCP: not now. Possibly later as a thin adapter over the same core.

## Hard rules
  

1. **Never** ask me for, read, print, log, or commit credentials or tokens. I run the interactive login (password + MFA) myself in my own terminal. Tokens live in `~/.garminconnect/garmin_tokens.json`; do not open that file.
2. The only network target is Garmin, through the library. No telemetry, no other APIs.
3. The MCP server and its SQL tool are **read-only** (open SQLite with `mode=ro`).
4. `data/` (database, raw JSON, FIT files), `.env`, and any token files are **gitignored from the first commit**. Do not commit real personal data, even in tests. Use synthetic fixtures.
5. **Ask before:** adding a dependency not listed below, changing the auth approach, any destructive DB operation, or adding any network call.
6. **Don't guess.** The library is unofficial and Garmin changes things. Never invent method names or payload fields. Introspect the installed package (`dir()`, `help()`, read its source in `.venv`) and inspect real raw responses first.
7. Do not retry login in a loop. Reuse the token store. On auth failure, exit non-zero with a clear message telling me to re-run `garmin-local login`.

## Stack

- Python 3.12+ (the library requires it), managed with `uv` (fallback: `venv` + `pip`)
- `garminconnect` + `curl_cffi` (pin exact versions in the lockfile)
- `mcp` (official Python SDK), `pytest`, `ruff`
- Login pattern (from the library README): first run `Garmin(email, password).login("~/.garminconnect")`, later runs `Garmin().login("~/.garminconnect")`. Verify against the installed version.

## Repo layout

```
garmin-local/
  CLAUDE.md
  pyproject.toml
  .env.example            # config names only, no secrets
  .gitignore              # data/, .env, *.db, tokens, .venv
  src/garmin_local/
    cli.py                # `garmin-local login | spike | sync | serve`
    auth.py               # token-store login; interactive first login
    client.py             # thin wrapper: rate limiting, backoff, error mapping
    db.py                 # schema + migrations (user_version pragma)
    sync.py               # watermark sync, upserts
    normalize.py          # raw JSON -> tables
    mcp_server.py         # FastMCP tools/resources
  scripts/spike.py        # Phase 1 throwaway explorer
  docs/spike-findings.md  # output of Phase 1
  data/                   # gitignored: garmin.db, raw/, fit/
  tests/
```

## Phases

### Phase 0: Skeleton (small)
Scaffold the repo above with `uv`, the CLI entry point, `.gitignore`, `ruff` and `pytest` config.
**Done when:** `uv run garmin-local --help` works and `uv run pytest` passes (even with one trivial test).

### Phase 1: Spike (the important one)
1. `garmin-local login`: interactive first login that saves tokens. I run it myself.
2. `garmin-local spike`: for the last ~7 days, call the endpoints below, dump each raw response to `data/raw/<endpoint>/<date>.json`, and print a summary table (endpoint, date, HTTP/ok, non-empty?).
   - Daily: summary stats, resting HR, stress, body battery
   - Sleep and recovery: sleep, HRV, training readiness, training status
   - Activities: list by date range, plus full detail for one run
   - **Strength:** for one gym session, check whether sets and reps come back (look for an exercise-sets style method in the library)
   - Optionally body composition and device/VO2max-type metrics
3. Write `docs/spike-findings.md`: for every endpoint, whether it returned data on the FR965, the top-level keys, units, and any surprises or gaps.

**Done when:** I've read `docs/spike-findings.md`. **Stop here for review. Schema design depends on it.**

### Phase 2: Schema and weekly sync
- Tables only for metrics the spike proved populated. Likely: `activities`, `daily_summary`, `sleep`, `hrv`, `training_readiness_status`, `body_composition`, `strength_sets` (if available).
- Always keep `raw_payloads(endpoint, date, fetched_at, json, UNIQUE(endpoint, date))`. Normalize from raw so a payload change means re-parse, not re-fetch.
- **Watermark sync:** store `last_success` in a `sync_state` table. Each run pulls from `(last_success - 7 days)` through today and **upserts** on natural keys. The first run is a backfill (`--backfill-days`, default 90). Re-running must change nothing.
- Be polite to Garmin: 1–2 s sleep with jitter between calls, exponential backoff on errors, a hard cap on retries.
- Units: store SI (meters, seconds, m/s) and convert in views. Day-bucketing uses Garmin's calendar date. Store timestamps in UTC alongside the local date.
- Logging to `data/sync.log`. Non-zero exit on failure so a scheduler can alert.
- Scheduling: see "Open questions". Default: a laptop job that runs at login and checks "last sync > 7 days ago?", plus a manual `garmin-local sync --now`.

**Done when:** a fresh backfill works, a second run is a no-op, and tests cover upsert idempotency and watermark logic using synthetic fixtures.

### Phase 3: MCP server
FastMCP over stdio, read-only DB connection. Keep the tool count small (roughly 8–12). Many existing Garmin MCP servers expose 100+ tools, which wastes LLM context. Planned tools:

- `sync_status()`: last success, row counts, date coverage
- `list_activities(start, end, type?, limit)`
- `activity_detail(activity_id)`
- `daily_overview(start, end)`: steps, resting HR, stress, body battery, sleep score, HRV, readiness
- `weekly_summary(weeks)`: volume by type, load, average sleep/HRV
- `run_sql(query)`: `SELECT` only, single statement, row cap (200), timeout, read-only connection
- Resource `garmin://schema`: tables, columns, units, example queries

Tool design rules: ISO dates, units stated in descriptions, compact markdown or JSON output, truncate large results with a "N more rows" note.
**Done when:** it works in MCP Inspector, then registers in Claude Code (`claude mcp add ...`) and answers a real question about my last 6 weeks.

### Phase 4: Analytics and agent (later, separate go-ahead)
Derived metrics (weekly load ramp, pace-vs-HR efficiency, sleep and recovery vs. next-day performance, strength days vs. run days), then a code-writing agent loop that queries the DB and checks its own numbers. FIT-file download and parsing for per-second data also belongs here.

## Conventions

- Type hints everywhere; small functions; `ruff` clean.
- Tests with `pytest`; synthetic fixtures only.
- SQL in plain `.sql` strings or small helpers; migrations tracked with `PRAGMA user_version`.
- Small, focused commits with clear messages.
- Keep a short `README.md` current with exact run commands.

## Open questions (ask me, don't assume)

1. **Where does the weekly job run?** Default assumption: my laptop with catch-up logic. If it's an always-on machine (home server, Pi, VM), the scheduler and failure handling change.
2. Which insights matter most? Default order: running load and trend, sleep/recovery, then strength sessions.

## First task

Do **Phase 0**, then **Phase 1**, and stop after writing `docs/spike-findings.md` (after I run the login and spike commands myself). Tell me exactly which commands to run and in what order.
