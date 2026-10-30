"""Tests for the anti-saturation engine (stdlib only — no pytest needed).

Run from backend/:
    python test_saturation.py

Covers: dry, optimal, high, saturated, missing sensor value, invalid input,
boundary values, rain pause, critical override, soil adjustment, and the
data-quality/confidence indicator.
"""

from app.engines.saturation import (
    DRY,
    HIGH,
    OPTIMAL,
    SATURATED,
    UNKNOWN,
    analyze_moisture,
    band_for,
)

TOMATO = dict(crop="Tomato", soil_type="Loamy", growth_stage="Flowering", area_hectares=2.5)


def test_dry():
    r = analyze_moisture(28, **TOMATO)
    assert r["status"] == DRY, r
    assert r["action"] == "schedule_irrigation", r
    assert "28%" in r["explanation"] and "40" in r["explanation"], r["explanation"]
    assert r["suggested_volume_l"] and r["suggested_volume_l"] > 0
    assert r["suggested_duration_min"] and r["suggested_duration_min"] > 0


def test_optimal():
    r = analyze_moisture(50, **TOMATO)
    assert r["status"] == OPTIMAL, r
    assert r["action"] == "maintain", r
    assert "no cycle" in r["explanation"].lower() or "no water" not in r["explanation"].lower()
    assert r["suggested_volume_l"] is None


def test_high():
    r = analyze_moisture(70, **TOMATO)
    assert r["status"] == HIGH, r
    assert r["action"] == "review_and_delay", r
    assert "delay" in r["explanation"].lower()


def test_saturated():
    r = analyze_moisture(80, **TOMATO)
    assert r["status"] == SATURATED, r
    assert r["action"] == "avoid_irrigation_monitor", r
    assert "waterlogging" in r["explanation"].lower()


def test_missing_sensor_value():
    r = analyze_moisture(None, **TOMATO)
    assert r["status"] == UNKNOWN, r
    assert r["action"] == "add_sensor_reading", r
    assert r["confidence"]["level"] == "low", r["confidence"]


def test_invalid_input():
    for bad in (150, -1, float("nan")):
        try:
            analyze_moisture(bad, **TOMATO)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for moisture={bad}")


def test_boundaries():
    # band for Tomato/Loamy = 40..60, saturation 75, critical 25
    band = band_for("Tomato", "Loamy")
    assert (band["lower"], band["upper"], band["saturation"]) == (40.0, 60.0, 75.0)

    assert analyze_moisture(40.0, **TOMATO)["status"] == OPTIMAL  # exactly lower
    assert analyze_moisture(60.0, **TOMATO)["status"] == OPTIMAL  # exactly upper
    assert analyze_moisture(60.01, **TOMATO)["status"] == HIGH    # just above upper
    assert analyze_moisture(75.0, **TOMATO)["status"] == HIGH     # exactly saturation
    assert analyze_moisture(75.01, **TOMATO)["status"] == SATURATED  # just above
    assert analyze_moisture(39.99, **TOMATO)["status"] == DRY     # just below lower
    assert analyze_moisture(0, **TOMATO)["status"] == DRY         # floor
    assert analyze_moisture(100, **TOMATO)["status"] == SATURATED  # ceiling


def test_critical_dry_is_below_critical_low():
    band = band_for("Tomato", "Loamy")
    just_below_lower = analyze_moisture(band["lower"] - 0.01, **TOMATO)
    assert just_below_lower["status"] == DRY
    assert just_below_lower["action"] == "schedule_irrigation"

    below_critical = analyze_moisture(band["critical_low"] - 0.01, **TOMATO)
    assert below_critical["status"] == DRY
    assert below_critical["action"] == "irrigate_now", below_critical


def test_rain_pause_and_critical_override():
    # Dry but rainy: delay
    r = analyze_moisture(35, rainfall_mm_24h=8, **TOMATO)
    assert r["status"] == DRY
    assert r["action"] == "delay_for_rain", r
    assert r["rain_advises_pause"] is True

    # Below the 5 mm threshold: rain does not change the decision
    r = analyze_moisture(35, rainfall_mm_24h=2.4, **TOMATO)
    assert r["action"] == "schedule_irrigation", r

    # Critical dry overrides the rain pause
    r = analyze_moisture(20, rainfall_mm_24h=8, **TOMATO)
    assert r["status"] == DRY and r["action"] == "irrigate_now", r


def test_soil_adjustment_moves_band():
    clay = band_for("Wheat", "Clay")
    sandy = band_for("Wheat", "Sandy")
    assert clay["lower"] == 40.0 and sandy["lower"] == 30.0  # +5 / -5 points
    # same moisture: DRY on clay (band 40-60) but OPTIMAL on sandy (band 30-50)
    assert analyze_moisture(37, crop="Wheat", soil_type="Clay")["status"] == DRY
    assert analyze_moisture(37, crop="Wheat", soil_type="Sandy")["status"] == OPTIMAL
    # and 52%: OPTIMAL on clay, HIGH on sandy
    assert analyze_moisture(52, crop="Wheat", soil_type="Clay")["status"] == OPTIMAL
    assert analyze_moisture(52, crop="Wheat", soil_type="Sandy")["status"] == HIGH


def test_unknown_crop_uses_default_band_and_flags_confidence():
    r = analyze_moisture(45, crop="Dragonfruit", soil_type="Loamy", reading_age_hours=2)
    band = band_for("Dragonfruit", "Loamy")
    assert band["lower"] == 35.0  # default band
    assert any("default band" in reason for reason in r["confidence"]["reasons"])
    assert r["confidence"]["level"] == "medium"


def test_confidence_drops_with_stale_reading():
    fresh = analyze_moisture(50, **TOMATO, reading_age_hours=2)
    stale = analyze_moisture(50, **TOMATO, reading_age_hours=60)
    assert fresh["confidence"]["level"] == "high"
    assert stale["confidence"]["level"] == "medium"
    assert any("old" in reason for reason in stale["confidence"]["reasons"])


def test_refill_estimate_uses_documented_formula():
    # Deficit to upper=60 from 28% over 0.4 m root depth on 2.5 ha:
    # 0.32 * 400 mm * 25000 m2 = 3,200,000 L... root depth by stage 'Flowering'=500
    r = analyze_moisture(28, **TOMATO)
    expected = round((60 - 28) / 100 * 500 * 2.5 * 10_000)
    assert r["suggested_volume_l"] == expected, (r["suggested_volume_l"], expected)


def test_all_outputs_have_required_fields():
    required = {
        "current_moisture_pct", "target", "status", "action", "action_label",
        "explanation", "source", "confidence", "rule",
    }
    for value in (None, 10, 50, 70, 90):
        r = analyze_moisture(value, **TOMATO)
        missing = required - set(r)
        assert not missing, f"missing {missing} for moisture={value}"


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
