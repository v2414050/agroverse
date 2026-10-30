from unittest.mock import patch

from app.clients import open_meteo  # noqa: E402


KANPUR_FIXTURE = {
    "results": [
        {
            "name": "Kanpur",
            "admin1": "Uttar Pradesh",
            "admin2": "Kanpur Nagar",
            "admin3": "Kanpur",
            "country": "India",
            "country_code": "IN",
            "latitude": 26.4499,
            "longitude": 80.3319,
            "elevation_m": 137.0,
            "timezone": "Asia/Kolkata",
            "population": 2823249,
            "label": "Kanpur, Kanpur Nagar, Uttar Pradesh, India",
        }
    ]
}


def test_cache_serves_repeat_requests_and_clear_works():
    open_meteo.clear_cache()
    with patch.object(open_meteo, "_get_json", return_value=KANPUR_FIXTURE) as mocked:
        first, meta1 = open_meteo.search_locations("Kanpur")
        second, meta2 = open_meteo.search_locations("Kanpur")
        assert mocked.call_count == 1, mocked.call_count
        assert meta1["from_cache"] is False
        assert meta2["from_cache"] is True
        assert meta2["age_seconds"] >= 0
        # A cache hit must return the SAME shape as a fresh result: a list
        # of place dicts — never a wrapped object (regression: the wrapper
        # once leaked through and broke the frontend candidates table).
        for value in (first, second):
            assert isinstance(value, list), type(value)
            assert value and isinstance(value[0], dict), value
            assert value[0]["name"] == "Kanpur"

        open_meteo.clear_cache()
        open_meteo.search_locations("Kanpur")
        assert mocked.call_count == 2
