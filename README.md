# garmin-local

Connect your Garmin watch to Claude. Ask questions about your training, sleep, recovery, and personal records in plain English — no spreadsheets, no dashboards.

> "What was my average sleep last week?"
> "How has my HRV trended since I increased my mileage?"
> "What's my 5K PR and when did I set it?"

Your data never leaves your computer.

---

## What you need

- A Garmin watch (tested on Forerunner 965; most modern Garmin devices work)
- A Garmin Connect account (free)
- A Mac or Linux computer
- About 15 minutes

---

## Step 1 — Install Python

You need Python 3.12 or newer.

**Check if you already have it:**
```
python3 --version
```
If it shows `Python 3.12` or higher, skip to Step 2.

**If not**, download and install it from [python.org/downloads](https://www.python.org/downloads/). Click the big yellow button and follow the installer.

---

## Step 2 — Install uv (the tool that runs everything)

Open your Terminal (press `Cmd + Space`, type "Terminal", press Enter) and paste this:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then close and reopen your Terminal window so it takes effect.

---

## Step 3 — Download garmin-local

```bash
git clone https://github.com/YOUR_USERNAME/garmin-local.git
cd garmin-local
uv sync
```

> If you don't have `git`, download the ZIP from GitHub and unzip it, then `cd` into the folder.

---

## Step 4 — Log in to Garmin Connect

```bash
uv run garmin-local login
```

It will ask for your Garmin Connect email and password. Type them in (the password won't show as you type — that's normal). If you have two-factor authentication, it will prompt for that too.

Your login is saved to your computer (`~/.garminconnect/`). You only need to do this once. garmin-local never sees your password again after this step.

---

## Step 5 — Pull your data

```bash
uv run garmin-local sync
```

This downloads the last 90 days of your training, sleep, HRV, and wellness data into a local database on your computer. It takes 2–5 minutes — Garmin asks us to go slowly so we don't hammer their servers.

You'll see progress messages. When it says `Sync complete`, you're done.

**To pull fresh data later** (after a run, or the next morning):
```bash
uv run garmin-local sync --now
```

---

## Step 6 — Start the MCP server

The MCP server is what lets Claude talk to your data.

**For Claude Desktop (recommended):**
```bash
uv run garmin-local serve
```

**For tools that connect over HTTP (like Joule):**
```bash
GARMIN_DB_PATH=data/garmin.db uv run garmin-local serve streamable-http --port 8080
```
Then connect your tool to: `http://127.0.0.1:8080/mcp`

The server also exposes:
- `http://127.0.0.1:8080/healthz` — is the server running?
- `http://127.0.0.1:8080/readyz` — can it reach the database?

---

## Step 7 — Connect to Claude Desktop

1. Open Claude Desktop
2. Go to **Settings → Developer → Edit Config**
3. Add this to the config file:

```json
{
  "mcpServers": {
    "garmin-local": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/garmin-local", "garmin-local", "serve"],
      "env": {
        "GARMIN_DB_PATH": "/path/to/garmin-local/data/garmin.db"
      }
    }
  }
}
```

Replace `/path/to/garmin-local` with the actual folder path (e.g. `/Users/john/garmin-local`).

4. Restart Claude Desktop
5. You should see a small hammer icon — that means the tools are connected

---

## Asking Claude about your data

Once connected, just ask in plain English:

| Question | What it uses |
|---|---|
| "How did I sleep last week?" | Sleep stages, score, HRV |
| "Am I overtraining?" | Training load, ACWR ratio |
| "Show my runs this month" | Activities list |
| "What's my 5K PR?" | Personal records |
| "How's my body battery been?" | Daily wellness |
| "Compare my HRV to my training load" | HRV + training status |

---

## Keeping your data fresh

Your data only updates when you run `sync`. A few options:

**Manual** — run `uv run garmin-local sync --now` after a workout or in the morning.

**Automatic on Mac** — add this to your crontab (`crontab -e`) to sync every morning at 7am:
```
0 7 * * * cd /path/to/garmin-local && uv run garmin-local sync >> data/sync.log 2>&1
```

The MCP server also kicks off a background sync automatically on the first request of each session, so it will catch up even if you forgot to run it manually.

---

## Available tools

| Tool | What it does |
|---|---|
| `sync_status` | When was the last sync? How many rows? |
| `list_activities` | Your workouts for a date range |
| `activity_detail` | Full detail for one activity (including gym sets) |
| `daily_overview` | Steps, HR, stress, body battery, sleep, HRV |
| `weekly_summary` | Training volume and wellness averages by week |
| `training_load` | Acute load, ACWR, fitness trend |
| `sleep_analysis` | Sleep stages, score, SpO2, HRV |
| `body_composition` | Weight, BMI, body fat % over time |
| `personal_records` | Your all-time bests (5K, 10K, half marathon, etc.) |
| `run_sql` | Write your own SQL query against the database |

---

## Troubleshooting

**"Token expired" or login error**
Run `uv run garmin-local login` again to refresh your session.

**"No data" for recent dates**
Run `uv run garmin-local sync --now` to pull the latest data.

**Server won't start / port already in use**
Another process is using that port. Try a different one:
```bash
GARMIN_DB_PATH=data/garmin.db uv run garmin-local serve streamable-http --port 9090
```

**Data seems old**
The sync cadence checks whether the last sync was within 7 days. Use `--now` to force it regardless.

---

## Your data stays on your computer

- The database lives in `data/garmin.db` on your machine
- No data is sent anywhere except to Garmin's servers (to fetch it)
- The MCP server only allows read-only access — Claude can query but never modify your data
- Credentials are stored in `~/.garminconnect/` and never logged or committed
