# KrishiSync AI

AI-powered sustainable agriculture and resource optimization platform.

Helps farmers avoid unnecessary irrigation, optimize energy use, choose suitable
crops, monitor farm conditions, and receive understandable, actionable
recommendations.

> **Note:** This build runs entirely on **demonstration data**. No live sensors,
> paid APIs, or external databases are used. Every API response carries
> `"demo_data": true`.

## Stack

| Layer    | Tech                                              |
| -------- | ------------------------------------------------- |
| Frontend | React + Vite (JavaScript) with plain CSS — no runtime UI/chart dependencies |
| Backend  | Python FastAPI + Uvicorn                          |
| Database | SQLite (stdlib — no PostgreSQL/Docker required)   |

## Project structure

```
backend/
  app/
    main.py       # FastAPI app + API routes
    database.py   # SQLite connection + schema
    seed.py       # Demonstration data
frontend/
  src/
    components/   # Icon, Sidebar, StatCard, Panel (reusable UI)
    pages/        # Dashboard, My Farm, Irrigation, Energy, Crop Advisor, Alerts, Settings
    data/         # Navigation sections + bundled fallback demo data
    lib/          # Number/date formatting helpers
```

The frontend loads `/api/dashboard`, `/api/farm` and `/api/alerts`. If the
backend is not running it silently falls back to the bundled demo data in
`frontend/src/data/demo.js` and shows a **Backend offline** chip, so the UI
always renders. Navigation uses the URL hash (`#/dashboard`, `#/irrigation`,
…) — no router dependency.

## Run the backend

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
```

API docs: http://localhost:8000/docs

## Data persistence & REST API

Storage is **SQLite** (`backend/krishisync.db`, Python stdlib — no external
DB, Docker, or service required). Farm edits, irrigation cycles, equipment
toggles, alert acknowledgements and engine recommendations all persist
there; migrations run automatically at startup (`database._migrate`), and
existing rows are backfilled, never discarded.

**Entity mapping** (spec entity → actual table, adapted not duplicated):

| Spec entity        | Storage                                                                    |
| ------------------ | -------------------------------------------------------------------------- |
| Users              | `users` (id, name, preferred_language) — seeded demo user                  |
| Farms              | `farms` (+ `user_id` migration); `current_crop` derived from first `plots` row |
| SensorReadings     | `readings` (per-plot typed columns instead of EAV; `data_source` = demo)    |
| IrrigationEvents   | `irrigation_log` (duration, litres = estimated usage, started_at)          |
| Equipment          | `equipment` (+ simulated schedule / operating status)                      |
| Recommendations    | `recommendations` — written by the irrigation/energy/crop engines (deduped) |
| Alerts             | `alerts` (+ `farm_id` migration)                                           |

**REST endpoints** (all validated with pydantic; 404 for unknown ids,
422 for invalid values, 400 for empty updates):

```
GET    /api/health
GET    /api/dashboard                       # single payload the app shell loads first
GET    /api/farm            POST /api/farm  # demo profile (single-farm build)
GET    /api/alerts          POST /api/alerts/sync | /api/alerts/{id}/ack
POST   /api/irrigation/start                # records a simulated cycle
GET    /api/irrigation/scenarios            # sample inputs for the engine
POST   /api/irrigation/analyze              # anti-saturation decision + reasons
GET    /api/energy/equipment                # fleet + findings summary
POST   /api/energy/analyze
POST   /api/energy/equipment/{id}/toggle    # simulated switch + re-analysis
GET    /api/crops/reference                 # dataset, seasons, form options
POST   /api/crops/analyze                   # per-field inputs, any may be missing
POST   /api/crops/recommend                 # farm profile -> uses stored soil/pH as base
GET    /api/farms           POST /api/farms
GET    /api/farms/{farm_id} PUT  /api/farms/{farm_id}    # partial update
GET    /api/farms/{farm_id}/irrigation-history
GET    /api/farms/{farm_id}/alerts
GET    /api/farms/{farm_id}/recommendations # persisted engine output, newest first
```

Decision logic stays in pure engine modules (`app/engines/`); routes only
load data, call the engine, and persist results. No secrets are used — the
build has no external credentials of any kind.

## Run the frontend

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:5173 (proxies `/api` to the backend)

## Anti-Saturation Engine

The Irrigation page and dashboard are driven by a rule-based engine that
classifies soil moisture as **DRY / OPTIMAL / HIGH / SATURATED** and
recommends irrigating, maintaining, or delaying. It is a pure function
(`backend/app/engines/saturation.py`); routes load data, call it, and return
the recommendation with its explanation and confidence.

**Formula** (from `KrishiSync_4_Algorithms.pdf`, section 3):

```
volume_L  = (upper - moisture) / 100 * root_depth_mm * area_m2
duration  = volume_L / (pump_flow_lpm * pump_efficiency)
```

**Assumptions (prototype defaults, tunable in `backend/app/config.py`):**

- Per-crop moisture bands `(lower, upper, saturation, critical_low)` —
  e.g. Tomato 40/60/75/25 %. Unknown crops fall back to a conservative
  default band and the response says so (lower confidence).
- Soil texture shifts the band (sandy −5 pts … clay +5 pts); growth stage
  sets the root depth used by the refill formula.
- The deck pauses on a 6-hour rain *forecast* (≥ 60 %, ≥ 5 mm); this build
  has no forecast feed, so it uses **measured rainfall of the last 24 h**
  against the same 5 mm threshold. A critical reading always overrides rain.
- Recent irrigation history is reported as context in the confidence notes.
- All readings are simulated demonstration data. The engine **recommends
  only — it does not control pumps or valves.**

**Tests** (stdlib, no extra packages):

```bash
cd backend
python test_saturation.py   # 14 cases: 4 states, missing, invalid, boundaries, rain, soil
```

API: `POST /api/irrigation/analyze` (e.g. `{"zone": "Zone B",
"moisture_pct": 28}`), sample inputs at `GET /api/irrigation/scenarios`.

## Smart Energy Optimization Engine

The Energy page is driven by a second pure engine
(`backend/app/engines/energy.py`) that flags avoidable consumption on the
demonstration equipment fleet:

- **unnecessary_operation** — an irrigation pump running while the
  anti-saturation engine says its zone does not need water
- **excessive_duration** — today's runtime over the configured cap
- **outside_schedule / peak_tariff** — running outside the configured
  window or inside the demo 14:00–17:00 peak window
- **idle_draw** — switched off but still drawing standby power (PDF
  "vampire load": ≥ 5 W for ≥ 30 min)
- **unknown_power_rating** — a data-quality note; consumption is never
  guessed when the rating is missing

Energy is estimated as `kWh = power (kW) × hours`; results labelled
"estimated" are calculations, and savings figures are **estimates, not
guarantees**. Normal operation is explicitly reported as normal.
Off-peak share is honestly reported as unavailable — the demo meter only
records daily totals, so no hourly split exists.

The page's "Switch off/on" buttons and `POST
/api/energy/equipment/{id}/toggle` flip a **simulated** flag in SQLite;
nothing physical is ever switched. New findings are persisted as alerts
(category `energy`). Equipment defaults live in `backend/app/config.py`
(`DEMO_EQUIPMENT`).

**Tests:**

```bash
cd backend
python test_energy.py    # 14 cases: normal, schedule, unnecessary, idle, missing rating, boundaries
```

## Terrain-Aware Agro-Advisory Engine (Crop Advisor)

The Crop Advisor page ranks crops from a small, transparent demo dataset
(`CROP_PROFILES` in `backend/app/config.py`: 10 India-oriented crops with
soil, pH, water, temperature, NPK, season and slope requirements) using a
pure rule engine (`backend/app/engines/crop_advisor.py`):

```
score = weighted average (0-100) of the criteria that could be evaluated:
  soil 25 · water 25 · temperature 20 · pH 15 · nutrients 15 · season 10 · slope 10
```

- **Water** compares estimated seasonal supply
  (`rainfall + irrigation top-up`, top-ups are documented demo assumptions)
  with the crop's seasonal water requirement.
- **Terrain**: field slope above a crop's tolerance scores 0 for that
  criterion and is named as a limiting factor (terracing advice).
- **Provisional**: any missing input makes the result provisional and is
  listed — nothing is ever invented. With *no* inputs the engine returns
  `insufficient_data` instead of fake rankings.
- **Scores are a fit indicator, not a yield prediction** — stated in every
  response.
- **Fertilizer guidance** is directional only: with measured N/P/K it flags
  nutrients outside the crop's typical kg/ha band and points to local
  agronomy advice; without measurements it recommends a soil test instead of
  inventing rates.

API: `GET /api/crops/reference` (form options + dataset),
`POST /api/crops/analyze` (all fields optional; invalid values → 422).
The dashboard carries a provisional top-3 summary (`crop_advisor`).

**Tests:**

```bash
cd backend
python test_crop_advisor.py   # 16 cases: suitable, unsuitable, missing soil/weather, invalid, slope, water, NPK rules
```
