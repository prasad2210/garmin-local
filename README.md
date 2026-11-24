# garmin-local

Connect your Garmin watch to Claude. Ask questions about your training, sleep, recovery, and personal records in plain English — no spreadsheets, no dashboards. Get a personalised training plan toward any goal based on your actual data.

Your data never leaves your computer.

---

## What you can do

### Ask questions about your training
> "How has my HRV trended since I increased my mileage?"
> "Am I overtraining? My legs feel heavy."
> "Show me all my runs this month with pace and heart rate."
> "How does my sleep affect my next-day body battery?"

### Get a training plan toward a goal
> "I want to run a sub-2 hour half marathon. Plan my next 12 weeks."
> "Help me break 20 minutes for 5K. What should I do this week?"
> "I want to increase my top speed — give me an 8-week plan."
> "Build me up from 40km to 60km per week safely."
> "Just plan this week's runs based on how I've been recovering."

Claude looks at your actual load, pace, HRV, and recovery before writing the plan — not a generic template.

### Understand your recovery and wellness
> "What was my average sleep score last week?"
> "My HRV dropped — should I take a rest day?"
> "How's my body battery been trending?"
> "What's my resting heart rate trend over the last month?"

### Review your personal records
> "What's my 5K PR and when did I set it?"
> "Have I set any new records in the last 3 months?"
> "What's my longest run ever?"

### Analyse your gym sessions
> "What exercises did I do in my last strength session?"
> "How many sets of pull-ups did I do last week?"

### Write your own queries
> "Show me every run where my average HR was above 160bpm."
> "What's my average pace on Tuesday runs vs Saturday long runs?"

---

## What's under the hood

| Tool | What it does |
|---|---|
| `training_context` | **The planning tool.** Pulls 8 weeks of load, pace, HRV, sleep, and PRs into one snapshot. Tell it your goal and how many weeks to plan — Claude writes the plan from your real numbers. |
| `daily_overview` | Steps, resting HR, stress, body battery, sleep score, HRV, and readiness — one row per day |
| `weekly_summary` | Training volume by activity type, avg sleep, avg HRV, avg readiness — one row per week |
| `training_load` | Acute load, ACWR ratio, training status phrase, fitness trend by week |
| `sleep_analysis` | Sleep duration, stages (deep/REM/light), score, SpO2, HRV, respiration |
| `list_activities` | All workouts for a date range, with distance, pace, HR, calories |
| `activity_detail` | Full detail for one workout — including every set and exercise for gym sessions |
| `personal_records` | All-time bests: 1km, 1 mile, 5K, 10K, half marathon, marathon, longest run |
| `body_composition` | Weight, BMI, body fat %, muscle mass over time (requires Garmin smart scale) |
| `sync_status` | When was the last sync? How many rows in each table? |
| `run_sql` | Write any SQL SELECT against the database for custom analysis |

### Training planner in detail

`training_context(goal, weeks)` assembles everything Claude needs to write a real plan:

- **8 weeks of training load** — acute load, ACWR ratio, fitness trend
- **Weekly running volume** — total km, number of runs, avg HR, pace range
- **Last 4 weeks of runs** — every session with distance, duration, pace, HR
- **14 days of recovery** — HRV, sleep score, body battery, readiness score
- **Personal records** — current 5K, 10K, half marathon times as the baseline

Then Claude derives your pace zones from your actual data, checks whether your load allows hard training (ACWR > 1.3 = back off), and writes sessions with specific distances and paces — not vague advice.

**Supported goals:**
- Race time targets — sub-2h half marathon, sub-20 5K, sub-45 10K, sub-4h marathon
- Top speed / VO2max — includes strides and interval sessions
- Mileage build — applies 10% rule, never stacks two hard weeks in a row
- General weekly plan — matches session count to your current habits

**Examples:**
```
training_context("sub-2h half marathon", weeks=12)   → 12-week block + week 1 detail
training_context("sub-20 5K", weeks=1)               → this week's sessions only
training_context("increase top speed", weeks=8)       → 8 weeks with interval focus
training_context("plan this week's runs")             → recovery-aware weekly schedule
```

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

## Keeping your data fresh

Your data only updates when you run `sync`. A few options:

**Manual** — run `uv run garmin-local sync --now` after a workout or in the morning.

**Automatic on Mac** — add this to your crontab (`crontab -e`) to sync every morning at 7am:
```
0 7 * * * cd /path/to/garmin-local && uv run garmin-local sync >> data/sync.log 2>&1
```

The MCP server also kicks off a background sync automatically on the first request of each session, so it will catch up even if you forgot to run it manually.

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
