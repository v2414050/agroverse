"""Configurable thresholds for the anti-saturation irrigation engine.

Every number here is a PROTOTYPE DEFAULT, per the Algorithms PDF
("All numbers below are proposed defaults for a prototype and must be
moved to config and tuned with real agronomic and market data").

The PDF's irrigation scheduler uses per-crop-stage moisture bands
(lower, upper, critical). This engine extends that band with a
saturation threshold above `upper` so moisture can also be classified
HIGH (review/delay) or SATURATED (avoid irrigation).

Tune these tables to match real agronomy before any pilot use.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MoistureBand:
    """Moisture band for a crop, in percent volumetric water content."""

    lower: float        # at/above this and up to `upper` -> OPTIMAL
    upper: float        # above this -> HIGH (review / delay irrigation)
    saturation: float   # above this -> SATURATED (avoid irrigation)
    critical_low: float  # below this -> critical dry, irrigate now (safety override)


# Per-crop default bands (prototype values; stage-specific tables can be
# layered on later — see ROOT_DEPTH_MM for the stage-dependent part).
CROP_BANDS: dict[str, MoistureBand] = {
    "wheat": MoistureBand(lower=35.0, upper=55.0, saturation=70.0, critical_low=20.0),
    "tomato": MoistureBand(lower=40.0, upper=60.0, saturation=75.0, critical_low=25.0),
    "sugarcane": MoistureBand(lower=45.0, upper=65.0, saturation=80.0, critical_low=30.0),
    "cotton": MoistureBand(lower=35.0, upper=55.0, saturation=70.0, critical_low=20.0),
}

# Fallback when the crop is unknown — deliberately the driest-tolerant
# defaults so an unknown crop never silently gets an optimistic band.
DEFAULT_BAND = MoistureBand(lower=35.0, upper=55.0, saturation=70.0, critical_low=20.0)

# Soil texture shifts the whole band by percentage points: sandy soils drain
# faster (irrigate at lower moisture), clay holds water (irrigate later).
SOIL_ADJUSTMENT: dict[str, float] = {
    "sandy": -5.0,
    "loamy": 0.0,
    "silt": 0.0,
    "clay": 5.0,
    "black": 3.0,
    "red": -2.0,
    "laterite": -3.0,
}
SOIL_ADJUSTMENT_DEFAULT = 0.0

# Effective root depth (mm) by growth stage — used only by the refill-volume
# formula below. Missing stages fall back to ROOT_DEPTH_MM_DEFAULT.
ROOT_DEPTH_MM: dict[str, int] = {
    "germination": 200,
    "seedling": 200,
    "tillering": 400,
    "vegetative": 450,
    "squaring": 450,
    "flowering": 500,
    "grand growth": 600,
}
ROOT_DEPTH_MM_DEFAULT = 400

# Recent rain at or above this (mm in the last 24 h) advises pausing a
# non-critical irrigation (PDF: rain_prob >= 0.60 and rain_mm_6h >= 5; we
# have no forecast in this build, so we use measured recent rain instead —
# see the engine docstring for the assumption).
RAIN_PAUSE_MM = 5.0

# Data-quality windows for the confidence indicator.
READING_FRESH_HOURS = 24.0
READING_STALE_HOURS = 48.0

# Pump model for the suggested-cycle estimate
# (PDF: duration_min = volume_L / (flow_lpm * efficiency)).
PUMP_FLOW_LPM = 2000.0
PUMP_EFFICIENCY = 0.85

# ---------------------------------------------------------------------------
# Smart Energy Optimization Engine (prototype defaults — tune before pilot)
# ---------------------------------------------------------------------------

# Energy = power (kW) x operating time (h). Used whenever a measured value
# is unavailable; results are always labelled "estimated".
KWH_FORMULA = "kWh = power_kw * hours"

# PDF section 4: vampire / idle load — a device left drawing above
# IDLE_WATTS for IDLE_MINUTES while switched off raises an idle_draw finding.
IDLE_WATTS = 5.0
IDLE_MINUTES = 30.0

# Peak-tariff demo window (matches the seeded energy alert, 14:00-17:00).
# Running pumps inside this window is flagged for rescheduling.
PEAK_WINDOW = ("14:00", "17:00")

# A pump may exceed its configured daily duration by this much before the
# excessive-duration rule fires (start-up rounding).
DURATION_TOLERANCE_H = 0.25

# Demonstration equipment fleet (all values simulated). power_kw=None
# simulates a device with an unknown rating — the engine must cope.
DEMO_EQUIPMENT = [
    {
        "id": 1,
        "name": "Zone B drip pump",
        "kind": "pump",
        "power_kw": 7.5,
        "schedule_start": "19:00",
        "schedule_end": "23:00",
        "max_hours_per_day": 4.0,
        "is_on": 1,
        "hours_today": 5.5,
        "standby_watts": None,
        "standby_minutes": 0.0,
        "zone": "Zone B",
    },
    {
        "id": 2,
        "name": "South sprinkler pump",
        "kind": "pump",
        "power_kw": 11.0,
        "schedule_start": "05:00",
        "schedule_end": "09:00",
        "max_hours_per_day": 3.0,
        "is_on": 1,
        "hours_today": 1.2,
        "standby_watts": None,
        "standby_minutes": 0.0,
        "zone": "Zone C",
    },
    {
        "id": 3,
        "name": "Drip control unit",
        "kind": "controller",
        "power_kw": 0.3,
        "schedule_start": None,
        "schedule_end": None,
        "max_hours_per_day": None,
        "is_on": 1,
        "hours_today": 6.2,
        "standby_watts": None,
        "standby_minutes": 0.0,
        "zone": None,
    },
    {
        "id": 4,
        "name": "Barn aeration fan",
        "kind": "fan",
        "power_kw": 1.5,
        "schedule_start": None,
        "schedule_end": None,
        "max_hours_per_day": None,
        "is_on": 0,
        "hours_today": 0.0,
        "standby_watts": 9.0,
        "standby_minutes": 45.0,
        "zone": None,
    },
    {
        "id": 5,
        "name": "Old 5 hp irrigation pump",
        "kind": "pump",
        "power_kw": None,  # rating unknown — engine must handle this
        "schedule_start": None,
        "schedule_end": None,
        "max_hours_per_day": None,
        "is_on": 1,
        "hours_today": 2.0,
        "standby_watts": None,
        "standby_minutes": 0.0,
        "zone": "Zone A",
    },
]

# ---------------------------------------------------------------------------
# Terrain-Aware Agro-Advisory Engine (prototype defaults — tune before pilot)
# ---------------------------------------------------------------------------

# Growing seasons for the Indian subcontinent context of the demo farm
# (Nashik, Maharashtra). Values are sowing-window month ranges; Zaid wraps
# around the calendar year (Apr-Jun).
SEASON_MONTHS: dict[str, tuple[int, int]] = {
    "kharif": (6, 10),    # monsoon sowing: Jun-Oct
    "rabi": (11, 3),      # winter sowing: Nov-Mar
    "zaid": (4, 6),       # summer sowing: Apr-Jun
}
SEASON_LABELS: dict[str, str] = {
    "kharif": "Kharif (Jun-Oct, monsoon)",
    "rabi": "Rabi (Nov-Mar, winter)",
    "zaid": "Zaid (Apr-Jun, summer)",
}


def season_for_month(month: int) -> str:
    """Calendar month -> demo season. Deliberately simple and transparent."""
    if 6 <= month <= 10:
        return "kharif"
    if 11 <= month <= 3:
        return "rabi"
    return "zaid"


# Irrigation access options. The engine estimates seasonal water supply as
#     supply_mm = rainfall_mm + WATER_TOPUP_MM[water_availability]
# The top-ups are DEMO ASSUMPTIONS standing in for irrigation capacity
# (limited = a couple of supplemental irrigations, assured = full canal /
# borewell coverage). They are not measured values.
WATER_TOPUP_MM: dict[str, int] = {
    "rainfed": 0,
    "limited": 150,
    "assured": 400,
}
WATER_LABELS: dict[str, str] = {
    "rainfed": "Rainfed only (no irrigation)",
    "limited": "Limited irrigation (supplemental)",
    "assured": "Assured irrigation (canal / borewell)",
}


@dataclass(frozen=True)
class NutrientRange:
    """Typical seasonal N-P-K requirement band in kg/ha."""

    n: tuple[float, float]
    p: tuple[float, float]
    k: tuple[float, float]


@dataclass(frozen=True)
class CropProfile:
    """Requirement profile for one crop in the demo dataset.

    All numbers are published agronomic ranges simplified into prototype
    defaults (India-oriented). They are transparent demonstration data,
    not site-specific advice.
    """

    name: str
    soil_types: tuple[str, ...]        # keys of SOIL_ADJUSTMENT
    ph_min: float
    ph_max: float
    water_requirement_mm: int          # seasonal crop-water need
    temp_min_c: float
    temp_max_c: float
    nutrients: NutrientRange
    seasons: tuple[str, ...]           # keys of SEASON_MONTHS
    max_slope_pct: float               # terrain tolerance, % slope
    note: str = ""


CROP_PROFILES: dict[str, CropProfile] = {
    "rice": CropProfile(
        name="Rice", soil_types=("clay", "silt", "black", "laterite"),
        ph_min=5.5, ph_max=7.5, water_requirement_mm=1200,
        temp_min_c=22.0, temp_max_c=32.0,
        nutrients=NutrientRange(n=(100, 150), p=(40, 60), k=(40, 60)),
        seasons=("kharif",), max_slope_pct=2.0,
        note="Puddled clay soils hold water; needs a reliable water source.",
    ),
    "wheat": CropProfile(
        name="Wheat", soil_types=("loamy", "clay", "black"),
        ph_min=6.0, ph_max=7.5, water_requirement_mm=500,
        temp_min_c=10.0, temp_max_c=25.0,
        nutrients=NutrientRange(n=(100, 140), p=(40, 60), k=(30, 50)),
        seasons=("rabi",), max_slope_pct=6.0,
        note="Winter crop; heat above 25 C during grain fill reduces yield.",
    ),
    "sugarcane": CropProfile(
        name="Sugarcane", soil_types=("loamy", "black", "red"),
        ph_min=6.0, ph_max=7.5, water_requirement_mm=1800,
        temp_min_c=20.0, temp_max_c=35.0,
        nutrients=NutrientRange(n=(150, 200), p=(60, 80), k=(80, 120)),
        seasons=("kharif",), max_slope_pct=4.0,
        note="Long-duration crop (10-12 months) with high water demand.",
    ),
    "cotton": CropProfile(
        name="Cotton", soil_types=("black", "red", "loamy"),
        ph_min=6.0, ph_max=8.0, water_requirement_mm=900,
        temp_min_c=21.0, temp_max_c=35.0,
        nutrients=NutrientRange(n=(60, 100), p=(30, 50), k=(30, 50)),
        seasons=("kharif",), max_slope_pct=5.0,
        note="Deep black soils suit deep roots; sensitive to waterlogging.",
    ),
    "tomato": CropProfile(
        name="Tomato", soil_types=("loamy", "silt", "red"),
        ph_min=6.0, ph_max=7.0, water_requirement_mm=500,
        temp_min_c=18.0, temp_max_c=30.0,
        nutrients=NutrientRange(n=(80, 120), p=(40, 60), k=(60, 80)),
        seasons=("rabi", "zaid"), max_slope_pct=6.0,
        note="Vegetable crop; pH above 7.0 raises micronutrient issues.",
    ),
    "maize": CropProfile(
        name="Maize", soil_types=("loamy", "black", "red"),
        ph_min=5.8, ph_max=7.5, water_requirement_mm=600,
        temp_min_c=18.0, temp_max_c=32.0,
        nutrients=NutrientRange(n=(100, 140), p=(40, 60), k=(30, 50)),
        seasons=("kharif", "zaid"), max_slope_pct=8.0,
        note="Versatile cereal; tolerates somewhat steeper ground than wheat.",
    ),
    "groundnut": CropProfile(
        name="Groundnut", soil_types=("sandy", "red", "loamy", "laterite"),
        ph_min=6.0, ph_max=7.5, water_requirement_mm=450,
        temp_min_c=20.0, temp_max_c=32.0,
        nutrients=NutrientRange(n=(10, 20), p=(25, 40), k=(25, 40)),
        seasons=("kharif",), max_slope_pct=6.0,
        note="Legume: fixes its own N, so the N band is deliberately low.",
    ),
    "soybean": CropProfile(
        name="Soybean", soil_types=("black", "loamy", "red"),
        ph_min=6.0, ph_max=7.5, water_requirement_mm=550,
        temp_min_c=20.0, temp_max_c=32.0,
        nutrients=NutrientRange(n=(15, 30), p=(30, 50), k=(30, 50)),
        seasons=("kharif",), max_slope_pct=6.0,
        note="Legume: most N comes from fixation; usually needs Rhizobium inoculation.",
    ),
    "chickpea": CropProfile(
        name="Chickpea (chana)", soil_types=("black", "loamy", "red"),
        ph_min=6.0, ph_max=8.0, water_requirement_mm=350,
        temp_min_c=10.0, temp_max_c=27.0,
        nutrients=NutrientRange(n=(20, 40), p=(25, 40), k=(20, 40)),
        seasons=("rabi",), max_slope_pct=8.0,
        note="Dry-legume; thrives on residual moisture with low water need.",
    ),
    "onion": CropProfile(
        name="Onion", soil_types=("loamy", "silt", "black"),
        ph_min=6.0, ph_max=7.5, water_requirement_mm=500,
        temp_min_c=13.0, temp_max_c=28.0,
        nutrients=NutrientRange(n=(80, 110), p=(40, 60), k=(40, 60)),
        seasons=("rabi", "zaid"), max_slope_pct=4.0,
        note="Bulbing is day-length sensitive; scheduling matters as much as soil.",
    ),
}
