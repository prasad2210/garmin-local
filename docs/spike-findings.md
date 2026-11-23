# Spike Findings — Garmin FR965

Spike run: 2026-11-23, last 7 days (2026-11-16 to 2026-11-23).
All endpoints returned data (`YES`). Body composition is empty (no smart scale).

---

## Endpoints

### daily_summary
**Method:** `get_stats(cdate)` — single object per day

Key fields (all populated):
- `calendarDate` — `"YYYY-MM-DD"`
- `totalSteps`, `totalDistanceMeters` (int, metres)
- `restingHeartRate`, `minHeartRate`, `maxHeartRate` (int, bpm)
- `averageStressLevel`, `maxStressLevel` (int, 0–100)
- `bodyBatteryHighestValue`, `bodyBatteryLowestValue`, `bodyBatteryMostRecentValue`, `bodyBatteryAtWakeTime` (int, 0–100)
- `totalKilocalories`, `activeKilocalories`, `bmrKilocalories` (float, kcal)
- `highlyActiveSeconds`, `activeSeconds`, `sedentarySeconds`, `sleepingSeconds` (int, seconds)
- `moderateIntensityMinutes`, `vigorousIntensityMinutes` (int, minutes)
- `avgWakingRespirationValue`, `lowestRespirationValue`, `highestRespirationValue` (float, breaths/min)
- `averageSpo2`, `lowestSpo2` (float/int, %)
- `wellnessStartTimeGmt` / `wellnessEndTimeGmt` — `"YYYY-MM-DDTHH:MM:SS.s"`

Unused for now: intraday body battery event arrays (stored in raw_payloads).

---

### resting_hr_range
**Method:** `get_rhr_daily(start, end)` — array of `{calendarDate, value}` (bpm)

Simple daily series. `restingHeartRate` in `daily_summary` is equivalent; this endpoint is a convenient range query.

---

### stress
**Method:** `get_stress_data(cdate)` — single object with intraday arrays

Summary fields: `avgStressLevel`, `maxStressLevel`, `calendarDate`

Intraday: `stressValuesArray` — 2D array `[epochMs, stressLevel]` at ~3-min intervals.
stressLevel: -2 = no data/active, -1 = unknown; positive values 0–100.

Also contains full `bodyBatteryValuesArray` at 3-min resolution (richer than body_battery_range).

**Decision:** store daily summaries in `daily_summary`. Raw intraday stays in `raw_payloads`.

---

### body_battery_range
**Method:** `get_body_battery(start, end)` — array of `{date, charged, drained, ...}`

Daily charged/drained values. Highest/lowest/most-recent already in `daily_summary`.
Sparse intraday key-frames only (6 values/day vs 3-min resolution in stress endpoint).

**Decision:** store charged/drained in `daily_summary`. Full intraday from stress raw.

---

### sleep
**Method:** `get_daily_sleep(cdate)` — large object with `dailySleepDTO` + `sleepMovement`

Key fields in `dailySleepDTO`:
- `calendarDate` — `"YYYY-MM-DD"`
- `sleepStartTimestampGMT`, `sleepEndTimestampGMT` — Unix epoch **milliseconds** (integer)
- `sleepTimeSeconds`, `deepSleepSeconds`, `lightSleepSeconds`, `remSleepSeconds`, `awakeSleepSeconds`, `napTimeSeconds` (int, seconds)
- `avgHeartRate` (float, bpm)
- `averageSpO2Value`, `lowestSpO2Value` (float/int, %)
- `averageRespirationValue` (float, breaths/min)
- `avgSleepStress` (float)
- `awakeCount` (int)
- `sleepScores.overall.value` (int, 0–100)
- `sleepScores.overall.qualifierKey` (string, e.g. `"GOOD"`)
- `breathingDisruptionSeverity` (string, e.g. `"NONE"`)

`sleepMovement` — per-minute array `{startGMT, endGMT, activityLevel}` — very large, store in raw only.

---

### hrv_day
**Method:** `get_hrv_data(cdate)` — object with `hrvSummary` + `hrvReadings`

`hrvSummary` fields:
- `calendarDate` — `"YYYY-MM-DD"`
- `weeklyAvg`, `lastNightAvg`, `lastNight5MinHigh` (int, ms RMSSD)
- `baseline.lowUpper`, `baseline.balancedLow`, `baseline.balancedUpper` (int, ms)
- `status` (string, e.g. `"BALANCED"`)
- `feedbackPhrase` (string)

`hrvReadings` — 5-min interval array `{hrvValue (ms), readingTimeGMT}` — stored in raw only.

---

### hrv_range
**Method:** `get_hrv_data_range(start, end)` — `{hrvSummaries: [...]}` array

Same fields as `hrvSummary` above, one entry per day. Convenient for backfill.

---

### training_readiness_day
**Method:** `get_training_readiness(cdate)` — **array** (multiple snapshots per day)

Each element:
- `calendarDate` + `timestamp` (string, `"YYYY-MM-DDTHH:MM:SS.s"`) — natural key is `(calendarDate, timestamp)`
- `score` (int, 0–100)
- `level` (string: `"LOW"`, `"MODERATE"`, `"HIGH"`)
- `inputContext` (string: `"AFTER_WAKEUP_RESET"`, `"AFTER_POST_EXERCISE_RESET"`, `"UPDATE_REALTIME_VARIABLES"`)
- `sleepScore`, `recoveryTime` (int hours), `acuteLoad`, `hrvWeeklyAverage` (int ms)
- 6 factor percentages + feedback phrases

**Decision:** store one row per snapshot. The `AFTER_WAKEUP_RESET` entry is the most meaningful.

---

### training_status_day
**Method:** `get_daily_training_status(cdate)` — object keyed by deviceId

Per device: `trainingStatusFeedbackPhrase`, `trainingStatus` (int), `fitnessTrend` (int), `acuteTrainingLoadDTO` fields.

Relatively stable day-to-day. Store the primary device's row per day.

**Decision:** include key fields in a `training_status` table (calendarDate, status phrase, ACWR, acute/chronic load).

---

### activities_by_date
**Method:** `get_activities_by_date(start, end)` — array of activity summaries

Key fields per activity:
- `activityId` (int) — primary key
- `activityName`, `startTimeLocal` / `startTimeGMT` (`"YYYY-MM-DD HH:MM:SS"` with **space**, not `T`)
- `activityType.typeKey` (string, e.g. `"running"`, `"strength_training"`)
- `distance` (float, metres), `duration` / `movingDuration` (float, seconds)
- `averageSpeed` (float, m/s), `calories` (float, kcal)
- `averageHR`, `maxHR` (float, bpm)
- `steps` (int)
- `aerobicTrainingEffect`, `anaerobicTrainingEffect` (float)
- `summarizedExerciseSets` (array, strength only) — per-exercise `{category, reps, sets, volume, maxWeight (g), duration (ms)}`

---

### activity_detail_run
**Method:** `get_activity_details(activity_id)` — per-second time-series

25 metric channels including: distance (m), speed (m/s), HR (bpm), cadence (spm), elevation (m), power (W), vertical oscillation (cm), ground contact time (ms), stride length (cm), stamina.
Raw values use divisor factor from `metricDescriptors`.

**Decision:** store in `raw_payloads` for now. Phase 4 for per-second FIT parsing.

---

### activity_exercise_sets
**Method:** `get_activity_exercise_sets(activity_id)` — object with `exerciseSets` array

Per set:
- `messageIndex` (int) — 0-based, alternates ACTIVE/REST
- `setType` (`"ACTIVE"` or `"REST"`)
- `startTime` (string, `"YYYY-MM-DDTHH:MM:SS.s"` GMT)
- `duration` (float, seconds)
- `repetitionCount` (int|null — null for REST)
- `weight` (float|null — kg; null = no weight sensor/manual entry)
- `exercises` array: `[{category, name, probability}]` — Garmin's classification of the exercise

**Weight note:** `weight` is null throughout because no weight sensor or manual entry was used. Field is typed float|null in schema.

---

### body_composition
**Method:** `get_body_composition(start, end)` — `{dateWeightList: [], totalAverage: {...}}`

**Empty** — no Garmin smart scale. `dateWeightList` is `[]`. All `totalAverage` fields null.
Schema will include the table with nullable columns in case a scale is added later.

---

### max_metrics_day
**Method:** `get_max_metrics(cdate)` — array (empty `[]` for today; use a past date)

`generic.vo2MaxPreciseValue` (float), `generic.vo2MaxValue` (int), `generic.fitnessAge` (null for FR965).
`heatAltitudeAcclimation` block — acclimation percentages, current altitude.
`cycling` — null (no cycling VO2max profile).

---

### devices
**Method:** `get_devices()` — array of device objects

Device ID: `3627040193`, model: `"Forerunner 965"`, firmware: `"29.05"`.
200+ capability flags — store key scalar fields; raw JSON blob for capabilities.

---

## Schema Decisions

| Table | Source | Natural key |
|-------|--------|-------------|
| `activities` | `get_activities_by_date` | `activity_id` |
| `daily_summary` | `get_stats(cdate)` | `calendar_date` |
| `sleep` | `get_daily_sleep(cdate)` | `calendar_date` |
| `hrv` | `get_hrv_data(cdate)` | `calendar_date` |
| `training_readiness` | `get_training_readiness(cdate)` | `(calendar_date, timestamp_gmt)` |
| `training_status` | `get_daily_training_status(cdate)` | `calendar_date` |
| `strength_sets` | `get_activity_exercise_sets(id)` | `(activity_id, message_index)` |
| `exercise_set_exercises` | nested in exercise_sets | `(activity_id, message_index, rank)` |
| `body_composition` | `get_body_composition(start, end)` | `calendar_date` |
| `raw_payloads` | all endpoints | `(endpoint, date_key)` |
| `sync_state` | internal | `key` |

**Units stored:** distances in metres, durations in seconds, speed in m/s, HR in bpm, HRV in ms, weight in kg, calories in kcal, stress/battery 0–100.

**Timestamps:** store UTC ISO strings as TEXT; store `calendar_date` as TEXT `"YYYY-MM-DD"`.
Sleep start/end: Garmin returns epoch ms integers — convert to UTC ISO string on insert.

**Not included (Phase 4):** per-second activity metrics (store in raw_payloads only), intraday stress/battery arrays.
