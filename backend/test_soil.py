"""Tests for the SoilGrids client and the /api/weather/soil route.

Run from backend/:
    python test_soil.py

All external calls are MOCKED — no internet access is required.
Covers: successful response (unit conversion, derived texture class),
all-null provider payloads (current ISRIC state), unreachable provider,
missing optional properties, invalid coordinates, caching, the USDA
classifier, and the honest unavailable labelling.
"""

from unittest.mock import patch

from fastapi import HTTPException

from app.clients import open_meteo, soilgrids
from app.clients.open_meteo import UpstreamError
from app.routes_weather import soil_info


def soil_fixture(sand=410, silt=350, clay=240, ocd=120):
    """Realistic SoilGrids Feature payload; values in mapped units g/kg."""
    def layer(name, value):
        return {
            "name": name,
            "unit_measure": {
                "d_factor": 10,
                "mapped_units": "g/kg" if name != "ocd" else "dg/kg",
                "target_units": "%" if name != "ocd" else "g/kg",
            },
            "depths": [
                {"label": depth, "values": {"mean": value}}
                for depth in ("0-5cm", "5-15cm", "15-30cm")
            ],
        }

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [80.3319, 26.4499]},
        "properties": {
            "layers": [
                layer("sand", sand), layer("silt", silt),
                layer("clay", clay), layer("ocd", ocd),
            ]
        },
        "query_time_s": 1.4,
    }


def null_fixture():
    return soil_fixture(sand=None, silt=None, clay=None, ocd=None)


def mock_http(payload):
    return patch.object(open_meteo, "_get_json", return_value=payload)


def fetch(lat=26.4499, lon=80.3319):
    open_meteo.clear_cache()
    with mock_http(soil_fixture()):
        return soilgrids.fetch_soil(lat, lon)


# ---------------------------------------------------------------------------
# successful response
# ---------------------------------------------------------------------------

def test_soil_success_converts_units_and_labels_estimates():
    payload, meta = fetch()
    assert payload["available"] is True
    top = payload["layers"][0]
    assert top["depth"] == "0-5cm"
    # g/kg -> % via d_factor 10
    assert top["sand_pct"] == 41.0
    assert top["silt_pct"] == 35.0
    assert top["clay_pct"] == 24.0
    assert top["organic_carbon_density_dg_per_kg"] == 120.0
    assert len(payload["layers"]) == 3
    assert meta["provider"] == "ISRIC SoilGrids 2.0"
    assert "CC BY 4.0" in meta["attribution"]
    assert meta["resolution"] == "250 m modelled grid"
    assert "not a measurement of your field" in meta["disclaimer"]
    assert meta["from_cache"] is False


def test_soil_texture_class_derived_from_fractions():
    payload, _ = fetch()
    # sand 41 / silt 35 / clay 24 -> USDA Loam
    assert payload["texture_class"] == "Loam"
    assert payload["texture_class_depth"] == "0-5cm"
    assert payload["layers"][0]["texture_class"] == "Loam"


def test_usda_texture_classifier_known_classes():
    cases = {
        (90, 5, 5): "Sand",
        (80, 12, 8): "Loamy sand",
        (65, 25, 10): "Sandy loam",
        (40, 40, 20): "Loam",
        (20, 65, 15): "Silt loam",
        (10, 85, 5): "Silt",
        (30, 15, 55): "Clay",
        (60, 10, 30): "Sandy clay loam",
        (10, 50, 40): "Silty clay",
        (33, 34, 33): "Sandy clay loam",
        (None, 30, 30): None,
    }
    for (sand, silt, clay), expected in cases.items():
        got = soilgrids.usda_texture_class(sand, silt, clay)
        assert got == expected, (sand, silt, clay, got, expected)


# ---------------------------------------------------------------------------
# unavailable states — never fabricated
# ---------------------------------------------------------------------------

def test_soil_all_null_values_reported_unavailable():
    open_meteo.clear_cache()
    with mock_http(null_fixture()):
        payload, meta = soilgrids.fetch_soil(26.4499, 80.3319)
    assert payload["available"] is False
    assert payload["reason"] == "provider_paused_or_no_data"
    assert payload["texture_class"] is None
    assert payload["layers"] == []
    assert "unavailable" in payload["message"]
    assert meta["provider"] == "ISRIC SoilGrids 2.0"


def test_soil_unreachable_provider_reports_unavailable_not_crash():
    open_meteo.clear_cache()
    with patch.object(open_meteo, "_get_json", side_effect=UpstreamError("provider timed out")):
        payload, _ = soilgrids.fetch_soil(26.4499, 80.3319)
    assert payload["available"] is False
    assert payload["reason"] == "provider_unreachable"
    assert "provider timed out" in payload["message"]


def test_soil_route_always_200_with_available_flag():
    open_meteo.clear_cache()
    with mock_http(null_fixture()):
        result = soil_info(latitude=26.4499, longitude=80.3319)
    assert result["ok"] is True
    assert result["available"] is False
    assert result["reason"] == "provider_paused_or_no_data"


def test_soil_invalid_response_reports_unavailable():
    for bad in ({}, {"properties": {}}, "not a dict", None):
        open_meteo.clear_cache()
        with mock_http(bad):
            payload, _ = soilgrids.fetch_soil(26.4499, 80.3319)
        assert payload["available"] is False, bad


def test_soil_missing_optional_property_still_available():
    fixture = soil_fixture()
    fixture["properties"]["layers"] = [
        layer for layer in fixture["properties"]["layers"]
        if layer["name"] != "ocd"
    ]
    open_meteo.clear_cache()
    with mock_http(fixture):
        payload, _ = soilgrids.fetch_soil(26.4499, 80.3319)
    assert payload["available"] is True
    assert payload["layers"][0]["organic_carbon_density_dg_per_kg"] is None
    assert payload["texture_class"] == "Loam"


def test_soil_partial_depths_use_first_complete_layer():
    fixture = soil_fixture()
    # 0-5cm null, deeper layers complete -> class comes from 5-15cm
    for layer in fixture["properties"]["layers"]:
        layer["depths"][0]["values"]["mean"] = None
    open_meteo.clear_cache()
    with mock_http(fixture):
        payload, _ = soilgrids.fetch_soil(26.4499, 80.3319)
    assert payload["available"] is True
    assert payload["texture_class_depth"] == "5-15cm"
    assert payload["layers"][0]["sand_pct"] is None


def test_soil_invalid_coordinates_rejected():
    for lat, lon in ((999.0, 0.0), (0.0, -400.0), (float("nan"), 0.0)):
        try:
            soil_info(latitude=lat, longitude=lon)
            raise AssertionError(f"coords ({lat}, {lon}) should be rejected")
        except HTTPException as exc:
            assert exc.status_code == 422, exc.status_code


# ---------------------------------------------------------------------------
# caching
# ---------------------------------------------------------------------------

def test_soil_cache_serves_available_results_only():
    open_meteo.clear_cache()
    with mock_http(soil_fixture()) as mocked:
        _, meta1 = soilgrids.fetch_soil(26.4499, 80.3319)
        _, meta2 = soilgrids.fetch_soil(26.4499, 80.3319)
        assert mocked.call_count == 1
        assert meta1["from_cache"] is False
        assert meta2["from_cache"] is True


def test_soil_unavailable_results_are_not_cached():
    open_meteo.clear_cache()
    with mock_http(null_fixture()) as mocked:
        soilgrids.fetch_soil(26.4499, 80.3319)
        soilgrids.fetch_soil(26.4499, 80.3319)
        # a paused provider must be re-checked, not frozen for 24 h
        assert mocked.call_count == 2


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
