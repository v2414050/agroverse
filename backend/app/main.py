"""KrishiSync AI backend — FastAPI application entry point.

Run from the backend/ directory:
    python -m uvicorn app.main:app --reload --port 8000

All data served by this API is DEMONSTRATION data until real sensors,
weather feeds, and equipment integrations are connected.
"""

import json
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import (
    CROP_PROFILES,
    SEASON_LABELS,
    SEASON_MONTHS,
    SOIL_ADJUSTMENT,
    WATER_LABELS,
    WATER_TOPUP_MM,
    season_for_month,
)
from .database import get_db, init_db
from .engines.alerts import derive_alerts, params_json
from .engines.crop_advisor import recommend_crops
from .engines.energy import analyze_fleet
from .engines.saturation import analyze_moisture
from .routes_weather import router as weather_router
from .seed import (
    seed_if_empty,
    seed_equipment_if_empty,
    seed_irrigation_log_if_empty,
    seed_users_and_link,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    seed_if_empty()
    seed_irrigation_log_if_empty()
    seed_equipment_if_empty()
    seed_users_and_link()
    with get_db() as db:
        _sync_engine_alerts(db)   # engine-derived alerts, deduped
    yield


app = FastAPI(title="KrishiSync AI API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Weather & soil intelligence is an INFORMATION layer (external Open-Meteo
# data). It touches no database tables and none of the decision engines —
# see app/routes_weather.py.
app.include_router(weather_router)

DEMO_NOTE = (
    "Demonstration data only — no live sensors are connected in this build."
)

MOISTURE_TARGET = 40.0
IRRIGATION_THRESHOLD = 35.0

ADVICE_NOTE = (
    "Simulated reading analysed by the demo engine — recommendation only, "
    "this build does not control pumps or valves."
)

ENERGY_NOTE = (
    "Simulated equipment data analysed by the demo engine — the switch "
    "controls are simulated and nothing is physically turned on or off."
)

CROP_ADVISOR_NOTE = (
    "Simulated farm conditions analysed by the demo advisory engine — "
    "suitability scores are a transparent fit indicator against the "
    "demonstration crop dataset, never a yield prediction or guarantee."
)


def _hours_ago(ts: str | None) -> float | None:
    """'YYYY-MM-DDTHH:MM' -> hours since now (None when unparseable)."""
    if not ts:
        return None
    try:
        stamp = datetime.strptime(str(ts)[:16], "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
    return round(max(0.0, (datetime.now() - stamp).total_seconds() / 3600), 1)


def _plot_advice(db, plot, farm, *, overrides=None):
    """Run the anti-saturation engine for one plot using stored demo data.

    `overrides` (sample scenarios / tests) replaces any stored value; an
    explicitly-None moisture override simulates a missing sensor value.
    """
    overrides = overrides or {}
    plot = dict(plot)
    reading = db.execute(
        "SELECT * FROM readings WHERE plot_id=? ORDER BY id DESC LIMIT 1",
        (plot["id"],),
    ).fetchone()
    last = db.execute(
        "SELECT MAX(started_at) AS last_at FROM irrigation_log WHERE plot_id=?",
        (plot["id"],),
    ).fetchone()

    def pick(name, stored):
        return overrides[name] if name in overrides else stored

    moisture = pick(
        "moisture_pct",
        reading["soil_moisture_pct"] if reading else plot.get("soil_moisture_pct"),
    )
    return analyze_moisture(
        moisture,
        crop=pick("crop", plot.get("crop")),
        soil_type=pick("soil_type", farm["soil_type"] if farm else None),
        growth_stage=pick("growth_stage", plot.get("growth_stage")),
        area_hectares=plot.get("area_hectares"),
        rainfall_mm_24h=pick("rainfall_mm", reading["rainfall_mm"] if reading else None),
        hours_since_irrigation=pick(
            "hours_since_irrigation", _hours_ago(last["last_at"] if last else None)
        ),
        reading_age_hours=_hours_ago(reading["recorded_at"] if reading else None),
        source="simulated scenario override" if overrides else "stored demo reading",
    )


def _advice_summary(result):
    """Compact per-zone advice attached to the dashboard payload."""
    if not result:
        return None
    return {
        "status": result["status"],
        "action": result["action"],
        "action_label": result["action_label"],
        "explanation": result["explanation"],
        "rule": result["rule"],
        "confidence": result["confidence"]["level"],
    }


def _zone_statuses(db) -> dict:
    """{zone: saturation status} using the first plot of each zone."""
    plots = db.execute("SELECT * FROM plots ORDER BY id").fetchall()
    farm = db.execute("SELECT * FROM farms ORDER BY id LIMIT 1").fetchone()
    statuses: dict = {}
    for p in plots:
        zone = p["irrigation_zone"]
        if zone in statuses:
            continue
        statuses[zone] = _plot_advice(db, p, farm)["status"]
    return statuses


def _farm_dict(db, farm) -> dict:
    """Spec-shaped farm payload. `current_crop` is derived from the farm's
    first plot, because crops live on plots in this schema (adapted, not
    duplicated)."""
    plot = db.execute(
        "SELECT crop FROM plots WHERE farm_id=? ORDER BY id LIMIT 1", (farm["id"],)
    ).fetchone()
    return {
        "id": farm["id"],
        "user_id": farm["user_id"],
        "name": farm["name"],
        "location": farm["location"],
        "latitude": farm["latitude"],
        "longitude": farm["longitude"],
        "area": farm["area_hectares"],
        "soil_type": farm["soil_type"],
        "soil_ph": farm["soil_ph"],
        "current_crop": plot["crop"] if plot else None,
    }


def _first_farm_id(db) -> int | None:
    row = db.execute("SELECT id FROM farms ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else None


def _persist_recommendations(db, farm_id, category: str, rows: list[tuple]) -> list[str]:
    """Store actionable engine output in the recommendations table.

    `rows` are (recommendation, reason, severity) triples. Deduped by
    (farm_id, category, recommendation) so repeated analyses do not spam.
    """
    created: list[str] = []
    if not farm_id or not rows:
        return created
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    for recommendation, reason, severity in rows:
        existing = db.execute(
            "SELECT id FROM recommendations WHERE farm_id=? AND category=? "
            "AND recommendation=?",
            (farm_id, category, recommendation),
        ).fetchone()
        if existing:
            continue
        db.execute(
            "INSERT INTO recommendations (farm_id, category, recommendation, "
            "reason, severity, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (farm_id, category, recommendation, reason, severity, now),
        )
        created.append(recommendation)
    return created


def _alert_context(db) -> dict:
    """Gather the current engine outputs that alert derivation runs on."""
    farm = db.execute("SELECT * FROM farms ORDER BY id LIMIT 1").fetchone()
    plots = db.execute("SELECT * FROM plots ORDER BY id").fetchall()

    plot_ctx = []
    for p in plots:
        advice = _plot_advice(db, p, farm)
        plot_ctx.append({
            "name": p["name"],
            "zone": p["irrigation_zone"],
            "moisture_pct": (
                advice["current_moisture_pct"]
                if advice["current_moisture_pct"] is not None
                else p["soil_moisture_pct"]
            ),
            "status": advice["status"],
            "rule": advice["rule"],
            "action": advice["action"],
            "action_label": advice["action_label"],
            "saturation_pct": advice["target"]["saturation_pct"],
        })

    # Irrigation cycles from the last 24 h (for the unnecessary-irrigation rule).
    recent: list[dict] = []
    events = db.execute(
        "SELECT l.zone, p.name AS plot, l.started_at FROM irrigation_log l "
        "JOIN plots p ON p.id = l.plot_id ORDER BY l.started_at DESC LIMIT 20"
    ).fetchall()
    for e in events:
        hours = _hours_ago(e["started_at"])
        if hours is None or hours > 24:
            continue
        recent.append({"zone": e["zone"], "plot": e["plot"], "hours_ago": hours})

    zone_status: dict = {}
    for p in plot_ctx:
        zone_status.setdefault(p["zone"], p["status"])
    equipment_rows = [
        dict(r) for r in db.execute("SELECT * FROM equipment ORDER BY id")
    ]
    fleet = (
        analyze_fleet(equipment_rows, zone_statuses=zone_status)["equipment"]
        if equipment_rows
        else []
    )

    # Crop-advisor top match (with its limiting factors) on the farm profile.
    conditions: dict = {"season": season_for_month(datetime.now().month)}
    if farm:
        conditions["soil_type"] = farm["soil_type"]
        conditions["soil_ph"] = farm["soil_ph"]
        temps = [
            r["temperature_c"]
            for r in db.execute(
                "SELECT temperature_c FROM readings WHERE id IN "
                "(SELECT MAX(id) FROM readings GROUP BY plot_id)"
            )
        ]
        if temps:
            conditions["temperature_c"] = round(sum(temps) / len(temps), 1)
    try:
        advisor = recommend_crops(conditions)
    except ValueError:
        advisor = {"insufficient_data": True, "missing": [], "recommendations": []}
    top = None
    if not advisor.get("insufficient_data") and advisor.get("recommendations"):
        top = advisor["recommendations"][0]

    return {
        "target_pct": MOISTURE_TARGET,
        "plots": plot_ctx,
        "recent_irrigation": recent,
        "equipment": fleet,
        "farm": (
            {"name": farm["name"], "soil_type": farm["soil_type"],
             "soil_ph": farm["soil_ph"]}
            if farm else None
        ),
        "crop": {"missing": advisor.get("missing", []), "top": top},
    }


def _sync_engine_alerts(db) -> list[str]:
    """Derive alerts from the engines and persist new ones (deduped by title,
    acknowledged or not, so restarting never re-raises a handled alert)."""
    created: list[str] = []
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    farm_id = _first_farm_id(db)
    for alert in derive_alerts(_alert_context(db)):
        existing = db.execute(
            "SELECT id FROM alerts WHERE title=?", (alert["title"],)
        ).fetchone()
        if existing:
            # Same finding as before: keep the row (and its acknowledgement)
            # but refresh the derived text so numbers/params track the engines.
            db.execute(
                "UPDATE alerts SET severity=?, message=?, action=?, related=?, "
                "issue=?, params=? WHERE id=?",
                (
                    alert["severity"], alert["description"], alert["action"],
                    alert["related"], alert["issue"], params_json(alert),
                    existing["id"],
                ),
            )
            continue
        db.execute(
            "INSERT INTO alerts (farm_id, created_at, severity, category, title, "
            "message, action, related, issue, params) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                farm_id, now, alert["severity"], alert["category"],
                alert["title"], alert["description"], alert["action"],
                alert["related"], alert["issue"], params_json(alert),
            ),
        )
        created.append(alert["title"])
    return created


# Sample scenarios for the Irrigation page — all simulated demo values.
SCENARIOS = [
    # Each scenario pins crop + soil so the outcome is deterministic
    # (bands shift with crop and soil texture — see app/config.py).
    {
        "id": "dry",
        "label": "Dry soil",
        "description": "Tomato on loamy soil at 28% — below the 40% target; irrigation recommended.",
        "overrides": {
            "zone": "Zone B", "moisture_pct": 28.0,
            "crop": "Tomato", "soil_type": "Loamy",
        },
    },
    {
        "id": "optimal",
        "label": "Optimal",
        "description": "Tomato on loamy soil at 50% — inside the 40–60% band; maintain.",
        "overrides": {
            "zone": "Zone A", "moisture_pct": 50.0,
            "crop": "Tomato", "soil_type": "Loamy",
        },
    },
    {
        "id": "high",
        "label": "High moisture",
        "description": "Tomato on loamy soil at 68% — above the 60% band; review and delay.",
        "overrides": {
            "zone": "Zone B", "moisture_pct": 68.0,
            "crop": "Tomato", "soil_type": "Loamy",
        },
    },
    {
        "id": "saturated",
        "label": "Saturated",
        "description": "Tomato on loamy soil at 82% — past the 75% saturation threshold.",
        "overrides": {
            "zone": "Zone C", "moisture_pct": 82.0,
            "crop": "Tomato", "soil_type": "Loamy",
        },
    },
    {
        "id": "heavy_rain",
        "label": "Dry + heavy rain",
        "description": "35% with 8 mm rain in 24 h — pause advised unless critical.",
        "overrides": {
            "zone": "Zone A", "moisture_pct": 35.0, "rainfall_mm": 8.0,
            "crop": "Tomato", "soil_type": "Loamy",
        },
    },
    {
        "id": "no_reading",
        "label": "Missing sensor value",
        "description": "No moisture value — engine reports UNKNOWN with low confidence.",
        "overrides": {"zone": "Zone A", "moisture_pct": None},
    },
]


# ---------------------------------------------------------------------------
# request payloads
# ---------------------------------------------------------------------------

class FarmIn(BaseModel):
    """Farmer-facing farm profile. pH and the crop fields are optional."""

    name: str = Field(min_length=1, max_length=80)
    location: str = Field(min_length=1, max_length=120)
    area_hectares: float = Field(gt=0, le=100_000)
    soil_type: str = Field(min_length=1, max_length=40)
    soil_ph: float | None = Field(default=None, ge=0, le=14)
    crop: str | None = Field(default=None, max_length=60)
    growth_stage: str | None = Field(default=None, max_length=60)
    soil_moisture_pct: float | None = Field(default=None, ge=0, le=100)


class IrrigationIn(BaseModel):
    zone: str = Field(min_length=1, max_length=40)


class AnalyzeIn(BaseModel):
    """Anti-saturation analysis request.

    Any field the client actually sends acts as a scenario override of the
    stored demo values — including an explicit null moisture_pct, which
    simulates a missing sensor value. Invalid numbers are rejected by the
    field constraints (HTTP 422).
    """

    zone: str | None = Field(default=None, max_length=40)
    plot_id: int | None = Field(default=None, gt=0)
    moisture_pct: float | None = Field(default=None, ge=0, le=100)
    crop: str | None = Field(default=None, max_length=60)
    growth_stage: str | None = Field(default=None, max_length=60)
    soil_type: str | None = Field(default=None, max_length=40)
    rainfall_mm: float | None = Field(default=None, ge=0, le=500)
    hours_since_irrigation: float | None = Field(default=None, ge=0, le=8760)


class ToggleIn(BaseModel):
    """Simulated equipment switch — flips a demo flag, nothing physical."""

    is_on: bool


class FarmCreateIn(BaseModel):
    """Create a farm. `area` is in hectares; coordinates are optional and
    default to 0 when unknown — the API never invents geography."""

    name: str = Field(min_length=1, max_length=80)
    location: str = Field(min_length=1, max_length=120)
    area: float = Field(gt=0, le=100_000)
    soil_type: str = Field(min_length=1, max_length=40)
    soil_ph: float | None = Field(default=None, ge=0, le=14)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    current_crop: str | None = Field(default=None, max_length=60)
    user_id: int | None = Field(default=None, gt=0)


class FarmUpdateIn(BaseModel):
    """Partial update: only fields actually sent are changed, everything
    else is preserved — saved data is never silently discarded."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    location: str | None = Field(default=None, min_length=1, max_length=120)
    area: float | None = Field(default=None, gt=0, le=100_000)
    soil_type: str | None = Field(default=None, min_length=1, max_length=40)
    soil_ph: float | None = Field(default=None, ge=0, le=14)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    current_crop: str | None = Field(default=None, max_length=60)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "demo_mode": True, "message": DEMO_NOTE}


@app.get("/api/farm")
def get_farm():
    with get_db() as db:
        farm = db.execute("SELECT * FROM farms ORDER BY id LIMIT 1").fetchone()
        plots = db.execute(
            "SELECT id, name, crop, crop_variety, growth_stage, health_pct, "
            "area_hectares, soil_moisture_pct, irrigation_zone FROM plots ORDER BY id"
        ).fetchall()
    return {
        "demo_data": True,
        "demo_note": DEMO_NOTE,
        "farm": dict(farm) if farm else None,
        "plots": [dict(p) for p in plots],
    }


@app.post("/api/farm")
def save_farm(payload: FarmIn):
    """Create or update the farm profile entered by the farmer.

    Crop / growth stage / moisture are stored on the farm's first plot
    (the "main field"), creating it when the farm had none.
    """
    name = _clean(payload.name)
    location = _clean(payload.location)
    soil_type = _clean(payload.soil_type)
    crop = _clean(payload.crop)
    stage = _clean(payload.growth_stage)

    if not name:
        raise HTTPException(400, "Farm name is required.")
    if not location:
        raise HTTPException(400, "Location is required.")
    if not soil_type:
        raise HTTPException(400, "Soil type is required.")

    with get_db() as db:
        farm = db.execute("SELECT * FROM farms ORDER BY id LIMIT 1").fetchone()
        latitude = farm["latitude"] if farm else 0.0
        longitude = farm["longitude"] if farm else 0.0

        if farm:
            farm_id = farm["id"]
            db.execute(
                "UPDATE farms SET name=?, location=?, area_hectares=?, soil_type=?, "
                "soil_ph=? WHERE id=?",
                (name, location, payload.area_hectares, soil_type, payload.soil_ph, farm_id),
            )
        else:
            farm_id = db.execute(
                "INSERT INTO farms (name, location, area_hectares, soil_type, soil_ph, "
                "latitude, longitude) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, location, payload.area_hectares, soil_type, payload.soil_ph,
                 latitude, longitude),
            ).lastrowid

        plot = db.execute(
            "SELECT * FROM plots WHERE farm_id=? ORDER BY id LIMIT 1", (farm_id,)
        ).fetchone()

        if plot:
            db.execute(
                "UPDATE plots SET crop=?, growth_stage=?, soil_moisture_pct=? WHERE id=?",
                (
                    crop or plot["crop"],
                    stage or plot["growth_stage"],
                    payload.soil_moisture_pct
                    if payload.soil_moisture_pct is not None
                    else plot["soil_moisture_pct"],
                    plot["id"],
                ),
            )
        elif crop:
            db.execute(
                "INSERT INTO plots (farm_id, name, crop, crop_variety, growth_stage, "
                "health_pct, area_hectares, soil_moisture_pct, irrigation_zone) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    farm_id,
                    "Main Field",
                    crop,
                    "—",
                    stage or "Unknown",
                    80,
                    payload.area_hectares,
                    payload.soil_moisture_pct
                    if payload.soil_moisture_pct is not None
                    else MOISTURE_TARGET,
                    "Zone A",
                ),
            )

    return {
        "ok": True,
        "message": "Farm details saved.",
        "demo_data": True,
        "demo_note": DEMO_NOTE,
    }


@app.get("/api/dashboard")
def get_dashboard():
    """Aggregated overview feeding the dashboard widgets."""
    with get_db() as db:
        farm = db.execute("SELECT * FROM farms ORDER BY id LIMIT 1").fetchone()
        plots = db.execute(
            "SELECT id, name, crop, growth_stage, health_pct, soil_moisture_pct, "
            "irrigation_zone FROM plots ORDER BY id"
        ).fetchall()

        # Farm-average moisture per timestamp (simulated hourly readings).
        moisture = db.execute(
            "SELECT recorded_at, AVG(soil_moisture_pct) AS avg_moisture_pct "
            "FROM readings GROUP BY recorded_at "
            "ORDER BY recorded_at DESC LIMIT 24"
        ).fetchall()

        latest_per_plot = db.execute(
            "SELECT plot_id, soil_moisture_pct, recorded_at FROM readings "
            "WHERE id IN (SELECT MAX(id) FROM readings GROUP BY plot_id)"
        ).fetchall()

        water = db.execute(
            "SELECT day, SUM(litres_used) AS used, SUM(litres_target) AS target "
            "FROM water_usage GROUP BY day ORDER BY day"
        ).fetchall()

        energy = db.execute(
            "SELECT day, kwh_solar, kwh_grid, pump_kwh "
            "FROM energy_usage ORDER BY day"
        ).fetchall()

        alerts = db.execute(
            "SELECT id, created_at, severity, category, title, message, acknowledged "
            "FROM alerts ORDER BY created_at DESC LIMIT 5"
        ).fetchall()

        irrigation_history = db.execute(
            "SELECT l.id, l.plot_id, p.name AS plot, l.zone, l.started_at, "
            "l.duration_min, l.litres, l.method, l.status "
            "FROM irrigation_log l LEFT JOIN plots p ON p.id = l.plot_id "
            "ORDER BY l.started_at DESC LIMIT 14"
        ).fetchall()

        # Anti-saturation advice per plot (pure engine on stored demo data).
        area_by_plot = {
            r["id"]: r["area_hectares"]
            for r in db.execute("SELECT id, area_hectares FROM plots")
        }
        advice_by_plot = {
            p["id"]: _advice_summary(
                _plot_advice(db, {**dict(p), "area_hectares": area_by_plot.get(p["id"])}, farm)
            )
            for p in plots
        }

        # Smart-energy summary for the dashboard (pure engine on demo fleet).
        energy_advice = None
        equipment_rows = [
            dict(r) for r in db.execute("SELECT * FROM equipment ORDER BY id")
        ]
        if equipment_rows:
            zone_status = {}
            for p in plots:
                zone_status.setdefault(
                    p["irrigation_zone"],
                    (advice_by_plot.get(p["id"]) or {}).get("status"),
                )
            energy_advice = analyze_fleet(
                equipment_rows,
                zone_statuses=zone_status,
                daily_usage=[dict(e) for e in energy],
            )["summary"]

        # Terrain-aware crop advisor summary for the dashboard. Uses only
        # what the build actually has: the farm's stored soil type / pH and
        # the demo readings' temperatures, plus the calendar season. Rain,
        # NPK and slope are NOT measured, so the result is provisional and
        # says so — nothing is invented.
        crop_advisor = None
        if farm:
            latest_temps = [
                r["temperature_c"]
                for r in db.execute(
                    "SELECT temperature_c FROM readings WHERE id IN "
                    "(SELECT MAX(id) FROM readings GROUP BY plot_id)"
                )
            ]
            avg_temp = (
                round(sum(latest_temps) / len(latest_temps), 1)
                if latest_temps
                else None
            )
            season = season_for_month(datetime.now().month)
            advisor = recommend_crops(
                {
                    "soil_type": farm["soil_type"],
                    "soil_ph": farm["soil_ph"],
                    "temperature_c": avg_temp,
                    "season": season,
                }
            )
            crop_advisor = {
                "season": season,
                "season_label": SEASON_LABELS[season],
                "source": (
                    "farm profile (soil, pH) + demo sensor temperatures + "
                    "calendar season"
                ),
                "provisional": advisor["provisional"],
                "missing": advisor["missing"],
                "top": [
                    {
                        "crop": r["crop"],
                        "score": r["score"],
                        "verdict_label": r["verdict_label"],
                        "provisional": r["provisional"],
                    }
                    for r in advisor["recommendations"][:3]
                ],
                "summary": advisor["summary"],
            }

    latest_by_plot = {r["plot_id"]: r["soil_moisture_pct"] for r in latest_per_plot}
    plot_moisture = [
        {**dict(p), "soil_moisture_pct": latest_by_plot.get(p["id"], p["soil_moisture_pct"])}
        for p in plots
    ]

    avg_moisture = (
        round(sum(r["avg_moisture_pct"] for r in moisture) / len(moisture), 1)
        if moisture
        else 0.0
    )
    total_used = sum(w["used"] for w in water)
    total_target = sum(w["target"] for w in water)
    latest_energy = energy[-1] if energy else None

    return {
        "demo_data": True,
        "demo_note": DEMO_NOTE,
        "farm": dict(farm) if farm else None,
        "soil_moisture": {
            "average_pct": (
                round(
                    sum(latest_by_plot.values()) / len(latest_by_plot), 1
                )
                if latest_by_plot
                else avg_moisture
            ),
            "target_pct": MOISTURE_TARGET,
            "series": [dict(r) for r in reversed(moisture)],
            "per_plot": plot_moisture,
        },
        "water_usage": {
            "total_litres": total_used,
            "target_litres": total_target,
            "series": [dict(w) for w in water],
        },
        "energy": {
            "latest": dict(latest_energy) if latest_energy else None,
            "series": [dict(e) for e in energy],
            "advice": energy_advice,
        },
        "crops": plot_moisture,
        "crop_advisor": crop_advisor,
        "irrigation": {
            "threshold_pct": IRRIGATION_THRESHOLD,
            "zones": [
                {
                    "zone": p["irrigation_zone"],
                    "plot": p["name"],
                    "soil_moisture_pct": p["soil_moisture_pct"],
                    "status": (
                        "needs_water"
                        if p["soil_moisture_pct"] < IRRIGATION_THRESHOLD
                        else "ok"
                    ),
                    "advice": advice_by_plot.get(p["id"]),
                }
                for p in plot_moisture
            ],
            "history": [dict(h) for h in irrigation_history],
        },
        "alerts": [dict(a) for a in alerts],
    }


ALERT_COLUMNS = (
    "id, created_at, severity, category, title, message, action, related, "
    "issue, params, acknowledged"
)


def _alert_row(row) -> dict:
    """Alert row -> API dict, with params decoded from JSON."""
    alert = dict(row)
    raw = alert.pop("params", None)
    try:
        alert["params"] = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        alert["params"] = {}
    return alert


@app.get("/api/alerts")
def list_alerts():
    """All alerts (seeded demo history + engine-derived), newest first.

    Acknowledges are persisted; `issue`+`params` let the UI localize
    engine-derived alerts.
    """
    with get_db() as db:
        rows = db.execute(
            f"SELECT {ALERT_COLUMNS} FROM alerts ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return {
        "demo_data": True,
        "demo_note": DEMO_NOTE,
        "alerts": [_alert_row(r) for r in rows],
    }


@app.post("/api/alerts/sync")
def sync_alerts():
    """Re-run all decision engines and persist any new findings as alerts.

    Deduped by title, so re-syncing never duplicates or resurrects an
    alert the farmer already acknowledged.
    """
    with get_db() as db:
        created = _sync_engine_alerts(db)
    return {
        "ok": True,
        "demo_data": True,
        "created_count": len(created),
        "created": created,
        "message": (
            f"Engines raised {len(created)} new alert(s)."
            if created
            else "Engines raised no new alerts — everything is already known."
        ),
    }


@app.post("/api/alerts/{alert_id}/ack")
def acknowledge_alert(alert_id: int):
    with get_db() as db:
        cursor = db.execute(
            "UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,)
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Alert not found.")
    return {"ok": True, "id": alert_id}


@app.post("/api/irrigation/start")
def start_irrigation(payload: IrrigationIn):
    """Log a demo irrigation cycle for a zone and refresh its moisture.

    No valves are controlled — this records a simulated cycle so the
    irrigation history and zone status update like a real session would.
    """
    zone = _clean(payload.zone)
    if not zone:
        raise HTTPException(400, "Zone is required.")

    now = datetime.now().strftime("%Y-%m-%dT%H:%M")

    with get_db() as db:
        plot = db.execute(
            "SELECT * FROM plots WHERE irrigation_zone=? ORDER BY id LIMIT 1", (zone,)
        ).fetchone()
        if not plot:
            raise HTTPException(404, f"No plot found in {zone}.")

        duration = max(15, round(plot["area_hectares"] * 12))
        litres = round(plot["area_hectares"] * 3200 / 100) * 100

        db.execute(
            "INSERT INTO irrigation_log (plot_id, zone, started_at, duration_min, "
            "litres, method, status) VALUES (?, ?, ?, ?, ?, ?, 'completed')",
            (plot["id"], zone, now, duration, litres, "Drip"),
        )

        new_moisture = min(60.0, round(plot["soil_moisture_pct"] + 8.0, 1))
        db.execute(
            "UPDATE plots SET soil_moisture_pct=? WHERE id=?",
            (new_moisture, plot["id"]),
        )
        db.execute(
            "INSERT INTO readings (plot_id, recorded_at, soil_moisture_pct, "
            "temperature_c, humidity_pct, rainfall_mm) VALUES (?, ?, ?, ?, ?, ?)",
            (plot["id"], now, new_moisture, 26.0, 50.0, 0.0),
        )

    return {
        "ok": True,
        "message": (
            f"{zone} ({plot['name']}) cycle completed: {litres:,} L over "
            f"{duration} minutes."
        ),
        "event": {
            "zone": zone,
            "plot": plot["name"],
            "started_at": now,
            "duration_min": duration,
            "litres": litres,
            "status": "completed",
        },
        "demo_data": True,
    }


@app.get("/api/irrigation/scenarios")
def list_scenarios():
    """Sample scenarios for testing the anti-saturation engine.

    Every scenario is a SIMULATED input — they exist so the four decision
    states (plus missing data) can be demoed without touching a sensor.
    """
    return {
        "demo_data": True,
        "demo_note": DEMO_NOTE,
        "scenarios": [
            {**scenario, "simulated": True, "overrides_zone_only": False}
            for scenario in SCENARIOS
        ],
    }


@app.post("/api/irrigation/analyze")
def analyze_soil(payload: AnalyzeIn):
    """Run the anti-saturation engine for one plot/zone.

    Recommendation only — this build does not control pumps or valves.
    Fields present in the request override the stored demo values, so the
    sample scenarios exercise the real decision logic.
    """
    provided = payload.model_fields_set
    overrides = {
        name: getattr(payload, name)
        for name in (
            "moisture_pct",
            "crop",
            "growth_stage",
            "soil_type",
            "rainfall_mm",
            "hours_since_irrigation",
        )
        if name in provided
    }

    zone = _clean(payload.zone)
    with get_db() as db:
        farm = db.execute("SELECT * FROM farms ORDER BY id LIMIT 1").fetchone()

        if payload.plot_id is not None:
            plot = db.execute(
                "SELECT * FROM plots WHERE id=?", (payload.plot_id,)
            ).fetchone()
        elif zone:
            plot = db.execute(
                "SELECT * FROM plots WHERE irrigation_zone=? ORDER BY id LIMIT 1",
                (zone,),
            ).fetchone()
        else:
            plot = db.execute("SELECT * FROM plots ORDER BY id LIMIT 1").fetchone()

        if not plot:
            raise HTTPException(404, "No plot found for that zone or plot id.")

        result = _plot_advice(db, plot, farm, overrides=overrides)

        # Persist actionable advice in the recommendations table (deduped).
        rec_rows = []
        if result["status"] == "DRY":
            rec_rows.append((
                f"{plot['name']} ({plot['irrigation_zone']}): {result['action_label']}",
                result["explanation"],
                "critical" if result["action"] == "irrigate_now" else "warning",
            ))
        elif result["status"] == "HIGH":
            rec_rows.append((
                f"{plot['name']} ({plot['irrigation_zone']}): {result['action_label']}",
                result["explanation"], "warning",
            ))
        rec_created = _persist_recommendations(
            db, plot["farm_id"], "irrigation", rec_rows
        )

    return {
        "ok": True,
        "demo_data": True,
        "demo_note": ADVICE_NOTE,
        "recommendations_created": rec_created,
        "plot": {
            "id": plot["id"],
            "name": plot["name"],
            "zone": plot["irrigation_zone"],
            "crop": result["crop"],
            "growth_stage": result["growth_stage"],
            "soil_type": result["soil_type"],
        },
        **result,
    }


# ---------------------------------------------------------------------------
# Smart Energy Optimization Engine routes
# ---------------------------------------------------------------------------

@app.get("/api/energy/equipment")
def list_equipment():
    """Demo equipment fleet with per-item engine analysis.

    All equipment values are simulated; the analysis joins each pump to
    the anti-saturation status of the zone it serves.
    """
    with get_db() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM equipment ORDER BY id")]
        zone_status = _zone_statuses(db)
        fleet = analyze_fleet(rows, zone_statuses=zone_status)
    return {
        "demo_data": True,
        "demo_note": ENERGY_NOTE,
        "simulated_controls": True,
        **fleet,
    }


@app.post("/api/energy/analyze")
def analyze_energy():
    """Run the smart-energy analysis and persist new findings as alerts."""
    with get_db() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM equipment ORDER BY id")]
        zone_status = _zone_statuses(db)
        fleet = analyze_fleet(rows, zone_statuses=zone_status)
        created = _sync_engine_alerts(db)
        rec_rows = [
            (
                f"{item['equipment']}: {finding['action']}",
                finding["explanation"],
                finding["severity"],
            )
            for item in fleet["equipment"]
            for finding in item["findings"]
            if finding["issue"] != "normal"
        ]
        rec_created = _persist_recommendations(
            db, _first_farm_id(db), "energy", rec_rows
        )
    return {
        "ok": True,
        "demo_data": True,
        "demo_note": ENERGY_NOTE,
        "alerts_created": created,
        "recommendations_created": rec_created,
        **fleet,
    }


@app.post("/api/energy/equipment/{equipment_id}/toggle")
def toggle_equipment(equipment_id: int, payload: ToggleIn):
    """SIMULATED equipment switch — flips a demo flag in the database.

    Nothing physical happens: no relay, pump, or valve is controlled.
    """
    with get_db() as db:
        cursor = db.execute(
            "UPDATE equipment SET is_on=? WHERE id=?",
            (1 if payload.is_on else 0, equipment_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Equipment not found.")
        row = db.execute(
            "SELECT name, kind FROM equipment WHERE id=?", (equipment_id,)
        ).fetchone()
    return {
        "ok": True,
        "demo_data": True,
        "simulated": True,
        "message": (
            f"{row['name']} marked as {'running' if payload.is_on else 'off'} "
            "(simulated — no physical device was switched)."
        ),
        "equipment": {"id": equipment_id, "name": row["name"], "is_on": payload.is_on},
    }


# ---------------------------------------------------------------------------
# Terrain-Aware Agro-Advisory Engine routes
# ---------------------------------------------------------------------------

class CropAdvisorIn(BaseModel):
    """Farm conditions for the crop advisor. Every field is OPTIONAL.

    Anything the client omits is reported as missing information and makes
    the recommendation provisional — the engine never invents measurements.
    """

    soil_type: str | None = Field(default=None, max_length=40)
    soil_ph: float | None = Field(default=None, ge=0, le=14)
    temperature_c: float | None = Field(default=None, ge=-30, le=60)
    rainfall_mm: float | None = Field(default=None, ge=0, le=5000)
    water_availability: str | None = Field(default=None, max_length=20)
    season: str | None = Field(default=None, max_length=20)
    slope_pct: float | None = Field(default=None, ge=0, le=90)
    nitrogen_kg_ha: float | None = Field(default=None, ge=0, le=1000)
    phosphorus_kg_ha: float | None = Field(default=None, ge=0, le=1000)
    potassium_kg_ha: float | None = Field(default=None, ge=0, le=1000)


@app.get("/api/crops/reference")
def crop_reference():
    """Form options + the demo crop dataset the advisory engine ranks against."""
    season = season_for_month(datetime.now().month)
    return {
        "demo_data": True,
        "demo_note": CROP_ADVISOR_NOTE,
        "soil_types": [
            {"key": key, "label": key.title()} for key in SOIL_ADJUSTMENT
        ],
        "seasons": [
            {"key": key, "label": label, "current": key == season}
            for key, label in SEASON_LABELS.items()
        ],
        "water_availability": [
            {"key": key, "label": label} for key, label in WATER_LABELS.items()
        ],
        "crops": [
            {
                "key": key,
                "name": profile.name,
                "soils": [s.title() for s in profile.soil_types],
                "ph_range": f"{profile.ph_min:g}–{profile.ph_max:g}",
                "temp_range_c": f"{profile.temp_min_c:g}–{profile.temp_max_c:g}",
                "water_need_mm": profile.water_requirement_mm,
                "seasons": [SEASON_LABELS[s] for s in profile.seasons],
                "max_slope_pct": profile.max_slope_pct,
                "note": profile.note,
            }
            for key, profile in CROP_PROFILES.items()
        ],
    }


@app.post("/api/crops/analyze")
def analyze_crops(payload: CropAdvisorIn):
    """Rank the demo crops against the submitted farm conditions.

    Recommendation only — suitability is a rule-based fit against the demo
    requirement dataset, not a yield prediction. Missing fields become
    'missing information' in the response, never invented values.
    """
    provided = payload.model_fields_set
    conditions = {name: getattr(payload, name) for name in provided}
    if "soil_type" in conditions:
        conditions["soil_type"] = _clean(conditions["soil_type"])

    season = conditions.get("season")
    if season is not None and season not in SEASON_MONTHS:
        raise HTTPException(422, f"season must be one of: {', '.join(SEASON_MONTHS)}.")
    water = conditions.get("water_availability")
    if water is not None and water not in WATER_TOPUP_MM:
        raise HTTPException(
            422, f"water_availability must be one of: {', '.join(WATER_TOPUP_MM)}."
        )

    try:
        result = recommend_crops(conditions)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    return {
        "ok": True,
        "demo_data": True,
        "demo_note": CROP_ADVISOR_NOTE,
        "conditions": conditions,
        **result,
    }


class CropRecommendIn(CropAdvisorIn):
    """Crop recommendation: point at a stored farm (its soil type and pH
    become the base conditions) and/or send explicit conditions. Explicit
    fields always override the farm profile."""

    farm_id: int | None = Field(default=None, gt=0)


# ---------------------------------------------------------------------------
# Farm data API — persistence layer (spec entity mapping documented in README)
# ---------------------------------------------------------------------------

DEMO_PERSISTENCE_NOTE = (
    "Data is persisted in the local SQLite database (backend/krishisync.db)."
)


@app.get("/api/farms")
def list_farms():
    """All stored farms in the canonical entity shape."""
    with get_db() as db:
        rows = db.execute("SELECT * FROM farms ORDER BY id").fetchall()
        farms = [_farm_dict(db, f) for f in rows]
    return {
        "demo_data": True,
        "demo_note": DEMO_PERSISTENCE_NOTE,
        "count": len(farms),
        "farms": farms,
    }


@app.post("/api/farms", status_code=201)
def create_farm(payload: FarmCreateIn):
    """Create a farm (persisted). Optional current_crop creates its first
    plot so the value round-trips through GET."""
    name = _clean(payload.name)
    location = _clean(payload.location)
    soil_type = _clean(payload.soil_type)
    if not name:
        raise HTTPException(400, "Farm name is required.")
    if not location:
        raise HTTPException(400, "Location is required.")
    if not soil_type:
        raise HTTPException(400, "Soil type is required.")

    with get_db() as db:
        user_id = payload.user_id
        if user_id is None:
            user = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
            user_id = user["id"] if user else None
        elif not db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
            raise HTTPException(404, "User not found — omit user_id to use the demo user.")

        farm_id = db.execute(
            "INSERT INTO farms (user_id, name, location, area_hectares, soil_type, "
            "soil_ph, latitude, longitude) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, name, location, payload.area, soil_type, payload.soil_ph,
                payload.latitude if payload.latitude is not None else 0.0,
                payload.longitude if payload.longitude is not None else 0.0,
            ),
        ).lastrowid

        if _clean(payload.current_crop):
            db.execute(
                "INSERT INTO plots (farm_id, name, crop, crop_variety, growth_stage, "
                "health_pct, area_hectares, soil_moisture_pct, irrigation_zone) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    farm_id, "Main Field", _clean(payload.current_crop), "—",
                    "Unknown", 80, payload.area, MOISTURE_TARGET, "Zone A",
                ),
            )

        farm = db.execute("SELECT * FROM farms WHERE id=?", (farm_id,)).fetchone()
        created_farm = _farm_dict(db, farm)

    return {
        "ok": True,
        "message": f"Farm '{name}' created and stored.",
        "demo_note": DEMO_PERSISTENCE_NOTE,
        "farm": created_farm,
    }


@app.get("/api/farms/{farm_id}")
def get_farm(farm_id: int):
    with get_db() as db:
        farm = db.execute("SELECT * FROM farms WHERE id=?", (farm_id,)).fetchone()
        if not farm:
            raise HTTPException(404, f"Farm {farm_id} not found.")
        payload = _farm_dict(db, farm)
    return {"demo_data": True, "demo_note": DEMO_PERSISTENCE_NOTE, "farm": payload}


@app.put("/api/farms/{farm_id}")
def update_farm(farm_id: int, payload: FarmUpdateIn):
    """Partial update — unsent fields keep their stored values. An explicit
    current_crop: null leaves the stored crop untouched rather than erasing
    it (saved data is never silently discarded)."""
    provided = payload.model_fields_set
    if not provided:
        raise HTTPException(400, "No fields supplied — nothing to update.")

    columns: dict = {}
    for field, column in (
        ("name", "name"),
        ("location", "location"),
        ("soil_type", "soil_type"),
    ):
        if field in provided:
            value = _clean(getattr(payload, field))
            if not value:
                raise HTTPException(400, f"{field.replace('_', ' ').title()} cannot be empty.")
            columns[column] = value
    for field, column in (
        ("area", "area_hectares"),
        ("soil_ph", "soil_ph"),
        ("latitude", "latitude"),
        ("longitude", "longitude"),
    ):
        if field in provided:
            columns[column] = getattr(payload, field)

    with get_db() as db:
        farm = db.execute("SELECT * FROM farms WHERE id=?", (farm_id,)).fetchone()
        if not farm:
            raise HTTPException(404, f"Farm {farm_id} not found.")

        if columns:
            assignments = ", ".join(f"{col}=?" for col in columns)
            db.execute(
                f"UPDATE farms SET {assignments} WHERE id=?",
                (*columns.values(), farm_id),
            )

        if "current_crop" in provided:
            crop = _clean(payload.current_crop)
            plot = db.execute(
                "SELECT * FROM plots WHERE farm_id=? ORDER BY id LIMIT 1", (farm_id,)
            ).fetchone()
            if plot and crop:
                db.execute("UPDATE plots SET crop=? WHERE id=?", (crop, plot["id"]))
            elif crop:  # farm had no plot yet — create the main field
                db.execute(
                    "INSERT INTO plots (farm_id, name, crop, crop_variety, growth_stage, "
                    "health_pct, area_hectares, soil_moisture_pct, irrigation_zone) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        farm_id, "Main Field", crop, "—", "Unknown", 80,
                        farm["area_hectares"], MOISTURE_TARGET, "Zone A",
                    ),
                )

        farm = db.execute("SELECT * FROM farms WHERE id=?", (farm_id,)).fetchone()
        updated = _farm_dict(db, farm)

    return {
        "ok": True,
        "message": f"Farm {farm_id} updated ({', '.join(sorted(provided))}).",
        "demo_note": DEMO_PERSISTENCE_NOTE,
        "farm": updated,
    }


@app.get("/api/farms/{farm_id}/irrigation-history")
def farm_irrigation_history(farm_id: int, limit: int = 50):
    """Stored irrigation events for one farm (duration + estimated water)."""
    if not 1 <= limit <= 500:
        raise HTTPException(422, "limit must be between 1 and 500.")
    with get_db() as db:
        if not db.execute("SELECT id FROM farms WHERE id=?", (farm_id,)).fetchone():
            raise HTTPException(404, f"Farm {farm_id} not found.")
        rows = db.execute(
            "SELECT l.id, p.name AS plot, l.zone, l.started_at, l.duration_min, "
            "l.litres, l.method, l.status FROM irrigation_log l "
            "JOIN plots p ON p.id = l.plot_id WHERE p.farm_id=? "
            "ORDER BY l.started_at DESC LIMIT ?",
            (farm_id, limit),
        ).fetchall()
    events = [
        {
            "id": r["id"],
            "plot": r["plot"],
            "zone": r["zone"],
            "duration_min": r["duration_min"],
            "estimated_water_usage_litres": r["litres"],
            "timestamp": r["started_at"],
            "method": r["method"],
            "status": r["status"],
        }
        for r in rows
    ]
    return {
        "demo_data": True,
        "demo_note": (
            "Water usage per event is the simulated cycle estimate recorded "
            "when the event was logged — not a physical flow-meter reading."
        ),
        "farm_id": farm_id,
        "count": len(events),
        "events": events,
    }


@app.get("/api/farms/{farm_id}/alerts")
def farm_alerts(farm_id: int):
    """Alerts for one farm. Rows stored before the farm_id column existed
    are treated as belonging to this (the demo) farm — nothing is dropped."""
    with get_db() as db:
        if not db.execute("SELECT id FROM farms WHERE id=?", (farm_id,)).fetchone():
            raise HTTPException(404, f"Farm {farm_id} not found.")
        rows = db.execute(
            f"SELECT {ALERT_COLUMNS} FROM alerts "
            "WHERE farm_id=? OR farm_id IS NULL ORDER BY created_at DESC, id DESC",
            (farm_id,),
        ).fetchall()
    return {
        "demo_data": True,
        "farm_id": farm_id,
        "count": len(rows),
        "alerts": [_alert_row(r) for r in rows],
    }


@app.get("/api/farms/{farm_id}/recommendations")
def farm_recommendations(farm_id: int, limit: int = 50):
    """Persisted engine recommendations for one farm, newest first."""
    if not 1 <= limit <= 500:
        raise HTTPException(422, "limit must be between 1 and 500.")
    with get_db() as db:
        if not db.execute("SELECT id FROM farms WHERE id=?", (farm_id,)).fetchone():
            raise HTTPException(404, f"Farm {farm_id} not found.")
        rows = db.execute(
            "SELECT id, category, recommendation, reason, severity, created_at "
            "FROM recommendations WHERE farm_id=? ORDER BY created_at DESC, id DESC "
            "LIMIT ?",
            (farm_id, limit),
        ).fetchall()
    return {
        "demo_data": True,
        "farm_id": farm_id,
        "count": len(rows),
        "recommendations": [dict(r) for r in rows],
    }


@app.post("/api/crops/recommend")
def recommend_for_farm(payload: CropRecommendIn):
    """Rank crops for a stored farm and/or explicit conditions.

    Runs the same pure advisory engine as /api/crops/analyze; the top
    recommendation is persisted (deduped) in the recommendations table.
    """
    provided = payload.model_fields_set
    conditions = {
        name: getattr(payload, name) for name in provided if name != "farm_id"
    }
    if "soil_type" in conditions:
        conditions["soil_type"] = _clean(conditions["soil_type"])

    farm_echo = None
    with get_db() as db:
        farm_id = payload.farm_id
        if farm_id is not None:
            farm = db.execute("SELECT * FROM farms WHERE id=?", (farm_id,)).fetchone()
            if not farm:
                raise HTTPException(404, f"Farm {farm_id} not found.")
            farm_echo = _farm_dict(db, farm)
            base = {"soil_type": farm["soil_type"], "soil_ph": farm["soil_ph"]}
            base.update(conditions)  # explicit fields override the profile
            conditions = base
        else:
            farm_id = _first_farm_id(db)

        season = conditions.get("season")
        if season is not None and season not in SEASON_MONTHS:
            raise HTTPException(422, f"season must be one of: {', '.join(SEASON_MONTHS)}.")
        water = conditions.get("water_availability")
        if water is not None and water not in WATER_TOPUP_MM:
            raise HTTPException(
                422, f"water_availability must be one of: {', '.join(WATER_TOPUP_MM)}."
            )

        try:
            result = recommend_crops(conditions)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

        created: list[str] = []
        if not result["insufficient_data"]:
            top = result["recommendations"][0]
            if top["verdict"] in ("recommended", "suitable_with_caution"):
                created = _persist_recommendations(db, farm_id, "crops", [(
                    f"Consider {top['crop']} ({top['score']}/100 fit)",
                    top["explanation"], "info",
                )])

    return {
        "ok": True,
        "demo_data": True,
        "demo_note": CROP_ADVISOR_NOTE,
        "farm": farm_echo,
        "conditions": conditions,
        "recommendations_created": created,
        **result,
    }
