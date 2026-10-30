"""SQLite database helper (no external DB required).

Uses Python's stdlib sqlite3 so the project runs without PostgreSQL,
Docker, or any external service.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "krishisync.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    preferred_language TEXT NOT NULL DEFAULT 'en'
);

CREATE TABLE IF NOT EXISTS farms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    area_hectares REAL NOT NULL,
    soil_type TEXT NOT NULL,
    soil_ph REAL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS plots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_id INTEGER NOT NULL REFERENCES farms(id),
    name TEXT NOT NULL,
    crop TEXT NOT NULL,
    crop_variety TEXT NOT NULL,
    growth_stage TEXT NOT NULL,
    health_pct INTEGER NOT NULL,
    area_hectares REAL NOT NULL,
    soil_moisture_pct REAL NOT NULL,
    irrigation_zone TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plot_id INTEGER NOT NULL REFERENCES plots(id),
    recorded_at TEXT NOT NULL,
    soil_moisture_pct REAL NOT NULL,
    temperature_c REAL NOT NULL,
    humidity_pct REAL NOT NULL,
    rainfall_mm REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS water_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plot_id INTEGER NOT NULL REFERENCES plots(id),
    day TEXT NOT NULL,
    litres_used INTEGER NOT NULL,
    litres_target INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS energy_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    kwh_solar INTEGER NOT NULL,
    kwh_grid INTEGER NOT NULL,
    pump_kwh INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_id INTEGER REFERENCES farms(id),
    created_at TEXT NOT NULL,
    severity TEXT NOT NULL,          -- info | warning | critical
    category TEXT NOT NULL,          -- irrigation | energy | crop | weather
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    action TEXT,                     -- recommended action (engine-derived)
    related TEXT,                    -- related farm / plot / equipment label
    issue TEXT,                      -- engine issue code for localization
    params TEXT,                     -- JSON params behind the alert
    acknowledged INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_id INTEGER NOT NULL REFERENCES farms(id),
    category TEXT NOT NULL,          -- irrigation | energy | crops
    recommendation TEXT NOT NULL,
    reason TEXT NOT NULL,
    severity TEXT NOT NULL,          -- info | warning | critical
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS irrigation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plot_id INTEGER NOT NULL REFERENCES plots(id),
    zone TEXT NOT NULL,
    started_at TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    litres INTEGER NOT NULL,
    method TEXT NOT NULL,
    status TEXT NOT NULL             -- completed | scheduled
);

CREATE TABLE IF NOT EXISTS equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,              -- pump | controller | fan | ...
    power_kw REAL,                   -- NULL = rating unknown (simulated)
    schedule_start TEXT,             -- 'HH:MM' window start, NULL = no schedule
    schedule_end TEXT,
    max_hours_per_day REAL,
    is_on INTEGER NOT NULL DEFAULT 0,
    hours_today REAL NOT NULL DEFAULT 0,
    standby_watts REAL,              -- draw while switched off
    standby_minutes REAL NOT NULL DEFAULT 0,
    zone TEXT                        -- irrigation zone served, if any
);
"""


@contextmanager
def get_db():
    """Yield a connection with foreign keys on and automatic commit/rollback."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as db:
        db.executescript(SCHEMA)
        _migrate(db)


def _migrate(db) -> None:
    """Bring pre-existing databases up to the current schema.

    The demo build ships a pre-seeded krishisync.db, so new columns and
    tables must be added in place instead of relying on CREATE TABLE.
    """
    farm_cols = {row["name"] for row in db.execute("PRAGMA table_info(farms)")}
    if "soil_ph" not in farm_cols:
        db.execute("ALTER TABLE farms ADD COLUMN soil_ph REAL")
    if "user_id" not in farm_cols:
        db.execute("ALTER TABLE farms ADD COLUMN user_id INTEGER REFERENCES users(id)")

    alert_cols = {row["name"] for row in db.execute("PRAGMA table_info(alerts)")}
    if "farm_id" not in alert_cols:
        db.execute("ALTER TABLE alerts ADD COLUMN farm_id INTEGER")
    for column in ("action", "related", "issue", "params"):
        if column not in alert_cols:
            db.execute(f"ALTER TABLE alerts ADD COLUMN {column} TEXT")
