"""Demonstration data for KrishiSync AI.

IMPORTANT: All values below are synthetic demonstration data used to
preview the product before real IoT sensors are connected. Nothing here
comes from a live sensor or a real farm.
"""

from datetime import datetime, timedelta

from .config import DEMO_EQUIPMENT
from .database import get_db


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def _hours_ago(n: int) -> str:
    return (datetime.now() - timedelta(hours=n)).strftime("%Y-%m-%dT%H:%M")


FARM = (
    "Demo Green Valley Farm",
    "Nashik, Maharashtra (demo location)",
    12.5,
    "Loamy",
    6.8,  # soil pH (demo measurement)
    19.9975,
    73.7898,
)

PLOTS = [
    # name, crop, variety, stage, health, area, moisture, zone
    ("North Field", "Wheat", "HD-3086", "Tillering", 88, 4.0, 41.0, "Zone A"),
    ("East Field", "Tomato", "Abhilash", "Flowering", 76, 2.5, 28.0, "Zone B"),
    ("South Field", "Sugarcane", "Co-86032", "Grand Growth", 92, 4.5, 55.0, "Zone C"),
    ("West Field", "Cotton", "Bt-Hybrid", "Squaring", 69, 1.5, 33.0, "Zone A"),
]

# 48 hourly readings per plot (2 days)
READINGS = []
for plot_id in range(1, 5):
    base_moisture = PLOTS[plot_id - 1][6]
    for h in range(48, 0, -1):
        drift = ((h % 12) - 6) * 1.5  # gentle wet/dry cycle
        READINGS.append(
            (
                plot_id,
                _hours_ago(h),
                round(max(12.0, min(70.0, base_moisture + drift)), 1),
                round(24.0 + ((h * 0.35) % 12), 1),
                round(45.0 + ((h * 1.7) % 35), 1),
                0.0 if h % 24 else 2.4,
            )
        )

# 7 days of water use per plot (litres used, litres target)
WATER_USAGE = []
plot_targets = [9500, 6200, 14800, 4100]
for plot_id in range(1, 5):
    target = plot_targets[plot_id - 1]
    for d in range(7, 0, -1):
        factor = 1.0 + (((plot_id * 7 + d) % 5) - 2) * 0.09
        WATER_USAGE.append(
            (plot_id, _days_ago(d - 1), int(target * factor), target)
        )

# 7 days of farm-level energy (kWh): solar generated, grid drawn, pump load
ENERGY_USAGE = []
for d in range(7, 0, -1):
    solar = 38 + ((d * 5) % 14)
    grid = 22 + ((d * 3) % 11)
    pump = 19 + ((d * 7) % 13)
    ENERGY_USAGE.append((_days_ago(d - 1), solar, grid, pump))

# Recent irrigation cycles (demo history) — hours ago, plot, zone, duration, litres, method
IRRIGATION_EVENTS = [
    (3, 3, "Zone C", 55, 14200, "Drip"),
    (27, 2, "Zone B", 35, 6100, "Drip"),
    (50, 1, "Zone A", 40, 9300, "Sprinkler"),
    (74, 3, "Zone C", 55, 13900, "Drip"),
    (98, 4, "Zone A", 25, 4050, "Drip"),
    (122, 2, "Zone B", 35, 6250, "Drip"),
    (146, 1, "Zone A", 40, 9150, "Sprinkler"),
]

ALERTS = [
    (
        _hours_ago(2),
        "critical",
        "irrigation",
        "East Field soil moisture below threshold",
        "East Field (Tomato) is at 28% moisture, under the 35% target. "
        "Schedule a 35-minute drip cycle in the evening to avoid evaporation loss.",
    ),
    (
        _hours_ago(6),
        "warning",
        "energy",
        "Pump running during peak tariff window",
        "Zone B pump drew 6 kWh between 14:00-17:00 (peak tariff). "
        "Shifting this cycle to 19:00 could save an estimated 18% on pumping cost.",
    ),
    (
        _hours_ago(20),
        "warning",
        "crop",
        "West Field crop health dipped below 70%",
        "West Field (Cotton) health index is 69%. Inspect for bollworm pressure "
        "and check nitrogen levels at the next field walk.",
    ),
    (
        _hours_ago(30),
        "info",
        "weather",
        "Rain expected within 48 hours",
        "Demo weather feed shows a 60% chance of 8-12 mm rain. "
        "Consider skipping the next Zone A cycle to avoid waterlogging.",
    ),
    (
        _hours_ago(52),
        "info",
        "irrigation",
        "Zone C irrigation completed",
        "South Field (Sugarcane) cycle finished: 14,200 L applied over 55 minutes. "
        "Within the daily target band.",
    ),
]


def seed_if_empty() -> bool:
    """Seed the database with demonstration data. Returns True if seeded."""
    with get_db() as db:
        count = db.execute("SELECT COUNT(*) FROM farms").fetchone()[0]
        if count > 0:
            return False

        db.execute(
            "INSERT INTO farms (name, location, area_hectares, soil_type, soil_ph, "
            "latitude, longitude) VALUES (?, ?, ?, ?, ?, ?, ?)",
            FARM,
        )
        db.executemany(
            "INSERT INTO plots (farm_id, name, crop, crop_variety, growth_stage, health_pct, "
            "area_hectares, soil_moisture_pct, irrigation_zone) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
            PLOTS,
        )
        db.executemany(
            "INSERT INTO readings (plot_id, recorded_at, soil_moisture_pct, temperature_c, "
            "humidity_pct, rainfall_mm) VALUES (?, ?, ?, ?, ?, ?)",
            READINGS,
        )
        db.executemany(
            "INSERT INTO water_usage (plot_id, day, litres_used, litres_target) "
            "VALUES (?, ?, ?, ?)",
            WATER_USAGE,
        )
        db.executemany(
            "INSERT INTO energy_usage (day, kwh_solar, kwh_grid, pump_kwh) VALUES (?, ?, ?, ?)",
            ENERGY_USAGE,
        )
        db.executemany(
            "INSERT INTO alerts (created_at, severity, category, title, message) "
            "VALUES (?, ?, ?, ?, ?)",
            ALERTS,
        )
    seed_irrigation_log_if_empty()
    return True


def seed_equipment_if_empty() -> bool:
    """Seed the demonstration equipment fleet (all values simulated)."""
    with get_db() as db:
        count = db.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]
        if count > 0:
            return False
        db.executemany(
            "INSERT INTO equipment (id, name, kind, power_kw, schedule_start, "
            "schedule_end, max_hours_per_day, is_on, hours_today, standby_watts, "
            "standby_minutes, zone) VALUES "
            "(:id, :name, :kind, :power_kw, :schedule_start, :schedule_end, "
            ":max_hours_per_day, :is_on, :hours_today, :standby_watts, "
            ":standby_minutes, :zone)",
            DEMO_EQUIPMENT,
        )
    return True


def seed_users_and_link() -> bool:
    """Ensure a demo user exists and link existing rows to it.

    The shipped single-user demo farm predates the users table, so this
    backfills farms.user_id and alerts.farm_id instead of leaving them NULL
    (never discards existing rows — only fills the new columns).
    """
    with get_db() as db:
        user = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        if not user:
            db.execute(
                "INSERT INTO users (name, preferred_language) VALUES (?, ?)",
                ("Demo Farmer", "en"),
            )
            user = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        user_id = user["id"]

        farm = db.execute("SELECT id FROM farms ORDER BY id LIMIT 1").fetchone()
        db.execute(
            "UPDATE farms SET user_id=? WHERE user_id IS NULL", (user_id,)
        )
        if farm:
            db.execute(
                "UPDATE alerts SET farm_id=? WHERE farm_id IS NULL", (farm["id"],)
            )
    return True


def seed_irrigation_log_if_empty() -> bool:
    """Seed demo irrigation cycles if the log is empty.

    Kept separate from seed_if_empty() so databases created before the
    irrigation_log table existed still get a populated history.
    """
    with get_db() as db:
        count = db.execute("SELECT COUNT(*) FROM irrigation_log").fetchone()[0]
        if count > 0:
            return False
        db.executemany(
            "INSERT INTO irrigation_log (plot_id, zone, started_at, duration_min, "
            "litres, method, status) VALUES (?, ?, ?, ?, ?, ?, 'completed')",
            [
                (plot_id, zone, _hours_ago(hours), duration, litres, method)
                for hours, plot_id, zone, duration, litres, method in IRRIGATION_EVENTS
            ],
        )
    return True
