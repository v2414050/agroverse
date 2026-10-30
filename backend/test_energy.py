"""Tests for the Smart Energy Optimization engine (stdlib only).

Run from backend/:
    python test_energy.py

Covers: normal operation, outside schedule, unnecessary operation while
irrigation is not required, excessive duration, missing power rating,
invalid duration, idle (vampire) draw, peak-tariff window, boundary
values, and the measured-vs-estimated distinction.
"""

from datetime import datetime

from app.engines.energy import (
    analyze_equipment,
    analyze_fleet,
    estimate_kwh,
)

PUMP = {
    "name": "Zone B drip pump",
    "kind": "pump",
    "power_kw": 7.5,
    "schedule_start": "19:00",
    "schedule_end": "23:00",
    "max_hours_per_day": 4.0,
    "is_on": 1,
    "hours_today": 2.0,
    "standby_watts": None,
    "standby_minutes": 0.0,
    "zone": "Zone B",
}

EVENING = datetime(2026, 10, 16, 20, 0)   # inside the pump schedule
MIDDAY = datetime(2026, 10, 16, 12, 0)    # outside it


def issues(result):
    return [f["issue"] for f in result["findings"]]


def test_normal_operation_is_not_waste():
    r = analyze_equipment(dict(PUMP), zone_status="DRY", now=EVENING)
    assert issues(r) == ["normal"], r
    assert r["total_savings_kwh_estimate"] == 0.0
    assert "not waste" in r["findings"][0]["explanation"]


def test_outside_schedule():
    r = analyze_equipment(dict(PUMP), zone_status="DRY", now=MIDDAY)
    assert "outside_schedule" in issues(r), r
    finding = next(f for f in r["findings"] if f["issue"] == "outside_schedule")
    assert finding["savings_kwh_estimate"] is None  # honestly not calculable


def test_peak_tariff_window():
    r = analyze_equipment(dict(PUMP), zone_status="DRY",
                          now=datetime(2026, 10, 16, 15, 0))
    assert "peak_tariff" in issues(r), r


def test_unnecessary_operation_when_irrigation_not_required():
    for status in ("OPTIMAL", "HIGH", "SATURATED"):
        r = analyze_equipment(dict(PUMP), zone_status=status, now=EVENING)
        assert "unnecessary_operation" in issues(r), (status, r)
    finding = next(
        f for f in r["findings"] if f["issue"] == "unnecessary_operation"
    )
    # savings = 7.5 kW x 2 h = 15 kWh
    assert finding["savings_kwh_estimate"] == 15.0, finding
    assert finding["savings_basis"] == "estimate"


def test_unknown_zone_status_is_not_waste():
    r = analyze_equipment(dict(PUMP), zone_status="UNKNOWN", now=EVENING)
    assert "unnecessary_operation" not in issues(r), r
    r = analyze_equipment(dict(PUMP), zone_status=None, now=EVENING)
    assert "unnecessary_operation" not in issues(r), r


def test_excessive_duration():
    eq = dict(PUMP, hours_today=5.5)
    r = analyze_equipment(eq, zone_status="DRY", now=EVENING)
    assert "excessive_duration" in issues(r), r
    finding = next(f for f in r["findings"] if f["issue"] == "excessive_duration")
    # over = 5.5 - 4 = 1.5 h x 7.5 kW = 11.25 kWh
    assert finding["savings_kwh_estimate"] == 11.25, finding


def test_excessive_duration_boundary():
    # exactly cap + tolerance -> no finding; a hair over -> finding
    ok = analyze_equipment(dict(PUMP, hours_today=4.25), zone_status="DRY", now=EVENING)
    assert "excessive_duration" not in issues(ok), ok
    bad = analyze_equipment(dict(PUMP, hours_today=4.26), zone_status="DRY", now=EVENING)
    assert "excessive_duration" in issues(bad), bad


def test_missing_power_rating_is_safe():
    eq = dict(PUMP, power_kw=None)
    r = analyze_equipment(eq, zone_status="DRY", now=EVENING)
    assert r["power_basis"] == "unknown"
    assert r["energy"]["basis"] == "unknown"
    assert r["energy"]["kwh_today"] is None
    # with an unnecessary-operation trigger, still no invented savings
    r2 = analyze_equipment(eq, zone_status="OPTIMAL", now=EVENING)
    finding = next(f for f in r2["findings"] if f["issue"] == "unnecessary_operation")
    assert finding["savings_kwh_estimate"] is None
    assert any(f["issue"] == "unknown_power_rating" for f in r2["findings"])


def test_invalid_duration():
    try:
        estimate_kwh(7.5, -1)
    except ValueError:
        pass
    else:
        raise AssertionError("negative hours must raise ValueError")
    assert estimate_kwh(None, 5) is None  # missing power -> None, not a guess


def test_estimate_formula():
    assert estimate_kwh(7.5, 5.5) == 41.25  # kWh = kW x h
    assert estimate_kwh(11, 0) == 0.0


def test_measured_vs_estimated():
    measured = analyze_equipment(
        dict(PUMP, kwh_today=15.9), zone_status="DRY", now=EVENING
    )
    assert measured["energy"]["basis"] == "measured"
    estimated = analyze_equipment(dict(PUMP), zone_status="DRY", now=EVENING)
    assert estimated["energy"]["basis"] == "estimated"
    assert estimated["energy"]["kwh_today"] == 15.0  # 7.5 x 2


def test_idle_draw_vampire_load():
    fan = {
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
    }
    r = analyze_equipment(fan, now=EVENING)
    assert issues(r) == ["idle_draw"], r
    finding = r["findings"][0]
    # 9 W x 45 min = 0.00675 kWh (rounded to 3 dp by the engine -> 0.007)
    assert finding["savings_kwh_estimate"] == 0.007, finding
    assert r["status_label"] == "Off (standby draw)"

    # below thresholds -> quiet, no finding
    quiet = analyze_equipment(dict(fan, standby_watts=3.0, standby_minutes=45.0))
    assert issues(quiet) == ["normal"], quiet


def test_midnight_wrapping_schedule():
    eq = dict(PUMP, schedule_start="22:00", schedule_end="02:00")
    inside = analyze_equipment(eq, zone_status="DRY",
                               now=datetime(2026, 10, 16, 23, 30))
    assert "outside_schedule" not in issues(inside), inside
    outside = analyze_equipment(eq, zone_status="DRY",
                                now=datetime(2026, 10, 16, 3, 0))
    assert "outside_schedule" in issues(outside), outside


def test_fleet_summary():
    rows = [
        dict(PUMP, id=1),
        dict(PUMP, id=2, name="South sprinkler pump", power_kw=11.0,
             schedule_start="05:00", schedule_end="09:00",
             max_hours_per_day=3.0, hours_today=1.2, zone="Zone C"),
        dict(PUMP, id=3, name="Drip control unit", kind="controller",
             power_kw=0.3, schedule_start=None, schedule_end=None,
             max_hours_per_day=None, hours_today=6.2, zone=None),
    ]
    fleet = analyze_fleet(rows, zone_statuses={"Zone B": "DRY", "Zone C": "DRY"},
                          now=EVENING)
    assert len(fleet["equipment"]) == 3
    ctrl = next(i for i in fleet["equipment"] if i["equipment"] == "Drip control unit")
    assert issues(ctrl) == ["normal"], ctrl  # controllers without schedules are fine
    pump = next(i for i in fleet["equipment"] if i["zone"] == "Zone B")
    assert issues(pump) == ["normal"], pump  # pump on while its zone is DRY = fine
    sprinkler = next(i for i in fleet["equipment"] if i["zone"] == "Zone C")
    # at 20:00 the 05:00-09:00 sprinkler is genuinely outside its window
    assert issues(sprinkler) == ["outside_schedule"], sprinkler
    assert fleet["summary"]["findings_count"] == 1
    assert fleet["summary"]["total_savings_kwh_estimate"] == 0.0  # schedule issues quote no savings
    assert "1 of 3" in fleet["summary"]["recommendation"]


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
