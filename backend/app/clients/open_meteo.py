"""External environmental-data client for Open-Meteo (geocoding + weather).

Design notes
------------
* Stdlib only (urllib.request) — no new runtime dependency is added.
* Every external call has a hard timeout and raises ``UpstreamError`` on
  network / HTTP / JSON problems, so routes can answer 502 instead of
  crashing and the rest of the API stays usable.
* Responses are validated and normalized here; raw provider payloads never
  reach the routes or the frontend.
* A small in-memory TTL cache dedupes repeated calls (rate-limit friendly)
  and exposes data freshness (``fetched_at`` / ``age_seconds``).

Honesty rules (product requirements)
------------------------------------
* Open-Meteo ``current`` values are MODEL-INTERPOLATED conditions, not
  station observations — labelled ``kind="model_based_current"``.
* A rolling 24 h rainfall sum is computed from HOURLY data only; if the
  hourly series has gaps (None) the value is reported as unavailable,
  never silently zero-filled.
* Calendar-day rainfall totals are labelled ``historical_daily_totals``
  and are never presented as a rolling-24 h measurement.
* Forecast rows carry ``kind="forecast"`` — predictions, not observations.

Provider: https://open-meteo.com — free for non-commercial use, rate
limited (10,000 calls/day), attribution "Weather data © Open-Meteo
(CC BY 4.0)" is mandatory and is returned in every payload's meta block.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

REQUEST_TIMEOUT_S = 8.0
GEOCODE_TTL_S = 3600.0     # location names change rarely
WEATHER_TTL_S = 600.0      # 10 min: balance freshness vs rate limits

ATTRIBUTION = "Weather data © Open-Meteo (CC BY 4.0)"
PROVIDER = "Open-Meteo"

CURRENT_NOTE = (
    "Model-interpolated current conditions from Open-Meteo weather models "
    "— not a direct measurement from a local weather station."
)
ROLLING_24H_NOTE = (
    "Sum of modelled hourly precipitation over the last 24 hours ending at "
    "the current local time."
)
HISTORY_NOTE = (
    "Calendar-day precipitation totals (local time) for previous days — "
    "daily totals, not a rolling 24-hour measurement."
)
FORECAST_NOTE = (
    "Forecast values are predictions and can change; rain is never guaranteed, "
    "even at high precipitation probability."
)


class UpstreamError(Exception):
    """The external provider could not be reached or answered unusably."""


# WMO weather interpretation codes -> human-readable condition.
WMO_CODES: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers",
    82: "Violent rain showers", 85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}


def condition_for(code) -> str | None:
    """WMO code -> text; None when the code is missing or unknown."""
    if code is None:
        return None
    try:
        return WMO_CODES.get(int(code))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# low-level HTTP + cache
# ---------------------------------------------------------------------------

def _get_json(url: str) -> dict:
    """GET url and parse JSON. Raises UpstreamError on any failure."""
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "KrishiSync-AI/0.1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise UpstreamError(f"provider returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError):
            raise UpstreamError("provider timed out") from exc
        raise UpstreamError(f"provider unreachable: {reason}") from exc
    except TimeoutError as exc:  # pragma: no cover - socket-level timeout
        raise UpstreamError("provider timed out") from exc
    except json.JSONDecodeError as exc:
        raise UpstreamError("provider returned invalid JSON") from exc


_CACHE: dict[str, tuple[float, dict]] = {}


def _cache_get(key: str, ttl_s: float) -> tuple[dict, dict] | None:
    entry = _CACHE.get(key)
    if not entry:
        return None
    fetched_epoch, data = entry
    age = time.time() - fetched_epoch
    if age > ttl_s:
        _CACHE.pop(key, None)
        return None
    return data, {
        "from_cache": True,
        "age_seconds": round(age, 1),
        "fetched_at": _iso_utc(fetched_epoch),
    }


def _cache_put(key: str, data: dict) -> dict:
    fetched_epoch = time.time()
    _CACHE[key] = (fetched_epoch, data)
    return {
        "from_cache": False,
        "age_seconds": 0.0,
        "fetched_at": _iso_utc(fetched_epoch),
    }


def clear_cache() -> None:
    """Drop all cached responses (used by tests and manual refreshes)."""
    _CACHE.clear()


def _iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(
        timespec="seconds"
    )


def _meta(cache_info: dict) -> dict:
    return {
        "provider": PROVIDER,
        "attribution": ATTRIBUTION,
        **cache_info,
    }


def _number(value) -> float | None:
    """Pass through finite numbers; anything else becomes None (never 0)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _validate_coords(latitude: float, longitude: float) -> None:
    for name, value, low, high in (
        ("latitude", latitude, -90.0, 90.0),
        ("longitude", longitude, -180.0, 180.0),
    ):
        # NaN fails every comparison, so it lands here too.
        if not (low <= value <= high):
            raise ValueError(f"{name} must be between {low} and {high}.")


# ---------------------------------------------------------------------------
# geocoding
# ---------------------------------------------------------------------------

def search_locations(query: str, count: int = 5) -> tuple[list[dict], dict]:
    """Human-readable place name -> normalized candidate list.

    All candidates are returned (never silently picks one) so ambiguous
    names such as "Kanpur" (India vs Pakistan) can be disambiguated by the
    user. Raises ValueError for bad input, UpstreamError when the provider
    fails. An empty result list is a valid outcome, not an error.
    """
    cleaned = (query or "").strip()
    if len(cleaned) < 2:
        raise ValueError("query must be at least 2 characters.")
    if len(cleaned) > 120:
        raise ValueError("query must be at most 120 characters.")
    count = max(1, min(int(count), 10))

    key = f"geocode:{cleaned.lower()}:{count}"
    cached = _cache_get(key, GEOCODE_TTL_S)
    if cached:
        return cached

    url = GEOCODING_URL + "?" + urllib.parse.urlencode(
        {"name": cleaned, "count": count, "language": "en", "format": "json"}
    )
    data = _get_json(url)
    if not isinstance(data, dict):
        raise UpstreamError("provider returned an unexpected payload")

    results: list[dict] = []
    raw_results = data.get("results")
    if isinstance(raw_results, list):
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            lat = _number(item.get("latitude"))
            lon = _number(item.get("longitude"))
            if not name or lat is None or lon is None:
                continue  # skip incomplete entries instead of guessing
            results.append({
                "name": name,
                "admin1": item.get("admin1"),
                "admin2": item.get("admin2"),
                "admin3": item.get("admin3"),
                "country": item.get("country"),
                "country_code": item.get("country_code"),
                "latitude": lat,
                "longitude": lon,
                "elevation_m": _number(item.get("elevation")),
                "timezone": item.get("timezone"),
                "population": item.get("population"),
                "label": _place_label(item),
            })

    # Cache the LIST itself (not a wrapper): a cache hit must return the
    # exact shape of a fresh result, or callers see a dict instead of rows.
    meta = _meta(_cache_put(key, results))
    return results, meta


def _place_label(item: dict) -> str:
    parts = [item.get("name")]
    for key in ("admin2", "admin1", "country"):
        value = item.get(key)
        if value and value not in parts:
            parts.append(value)
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# weather (current + rainfall + forecast in one provider call)
# ---------------------------------------------------------------------------

def fetch_environment(latitude: float, longitude: float) -> tuple[dict, dict]:
    """Current weather, rainfall history and a 7-day forecast for a point.

    One Open-Meteo call returns everything (current + hourly + daily with
    past_days=7), keeping us well inside the free rate limits. Raises
    ValueError for invalid coordinates and UpstreamError when the provider
    fails or returns an incomplete payload.
    """
    _validate_coords(latitude, longitude)

    key = f"env:{round(latitude, 3)}:{round(longitude, 3)}"
    cached = _cache_get(key, WEATHER_TTL_S)
    if cached:
        return cached

    params = {
        "latitude": round(latitude, 4),
        "longitude": round(longitude, 4),
        "current": ",".join((
            "temperature_2m", "relative_humidity_2m", "precipitation",
            "weather_code", "wind_speed_10m", "cloud_cover",
        )),
        "hourly": "precipitation",
        "daily": ",".join((
            "weather_code", "temperature_2m_max", "temperature_2m_min",
            "precipitation_sum", "precipitation_probability_max",
        )),
        "past_days": 7,
        "forecast_days": 7,
        "timezone": "auto",
    }
    data = _get_json(FORECAST_URL + "?" + urllib.parse.urlencode(params))
    payload = _parse_environment(data)

    meta = _meta(_cache_put(key, payload))
    return payload, meta


def _parse_environment(data: dict) -> dict:
    """Validate and normalize a /v1/forecast payload. Raises UpstreamError."""
    if not isinstance(data, dict):
        raise UpstreamError("provider returned an unexpected payload")

    current = data.get("current")
    daily = data.get("daily")
    hourly = data.get("hourly") if isinstance(data.get("hourly"), dict) else {}
    if not isinstance(current, dict) or not isinstance(daily, dict):
        raise UpstreamError("provider response is missing core fields")
    if not isinstance(daily.get("time"), list) or _number(current.get("temperature_2m")) is None:
        raise UpstreamError("provider response is missing core fields")

    local_time = current.get("time")
    today = str(local_time)[:10] if local_time else date.today().isoformat()

    current_block = {
        "temperature_c": _number(current.get("temperature_2m")),
        "humidity_pct": _number(current.get("relative_humidity_2m")),
        "precipitation_mm": _number(current.get("precipitation")),
        "wind_speed_kmh": _number(current.get("wind_speed_10m")),
        "cloud_cover_pct": _number(current.get("cloud_cover")),
        "weather_code": _number(current.get("weather_code")),
        "condition": condition_for(current.get("weather_code")),
        "observed_local": local_time,
        "kind": "model_based_current",
        "note": CURRENT_NOTE,
    }

    rolling_sum, covered = _rolling_precipitation(
        hourly.get("time"), hourly.get("precipitation"), local_time
    )
    rainfall_block = {
        "rolling_24h_mm": rolling_sum,
        "rolling_24h_hours_covered": covered,
        "rolling_24h_period": (
            f"24 hours ending {local_time}" if local_time else None
        ),
        "rolling_24h_kind": "modelled_rolling_24h",
        "rolling_24h_note": ROLLING_24H_NOTE,
        "daily_history": _daily_history(daily, today),
        "daily_history_kind": "historical_daily_totals",
        "daily_history_note": HISTORY_NOTE,
    }

    forecast_block = {
        "days": _forecast_days(daily, today),
        "kind": "forecast",
        "note": FORECAST_NOTE,
    }

    return {
        "location": {
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "timezone": data.get("timezone"),
            "elevation_m": _number(data.get("elevation")),
        },
        "current": current_block,
        "rainfall": rainfall_block,
        "forecast": forecast_block,
    }


def _at(values, index: int):
    if isinstance(values, list) and 0 <= index < len(values):
        return values[index]
    return None


def _rolling_precipitation(hourly_times, hourly_precip, local_time):
    """Sum hourly precipitation over the last <=24 h ending at local_time.

    Returns (sum_mm | None, hours_covered). None means the data cannot
    honestly answer the question (gap in the series / no usable data) —
    callers must display "unavailable", never 0.
    """
    if not isinstance(hourly_times, list) or not isinstance(hourly_precip, list):
        return None, 0
    if not local_time:
        return None, 0
    hour_key = str(local_time)[:13] + ":00"

    end = None
    for i, stamp in enumerate(hourly_times):
        if str(stamp) <= hour_key:
            end = i
        else:
            break
    if end is None:
        return None, 0

    window = hourly_precip[max(0, end - 23): end + 1]
    if not window or any(v is None for v in window):
        # A gap in the hourly series makes any sum an under-count; report
        # unavailable rather than a quietly wrong (lower) number.
        return None, sum(1 for v in window if v is not None)
    return round(sum(float(v) for v in window), 2), len(window)


def _daily_history(daily: dict, today: str) -> list[dict]:
    """Previous calendar days (local) with their daily precipitation totals."""
    days: list[dict] = []
    times = daily.get("time") or []
    sums = daily.get("precipitation_sum")
    for i, stamp in enumerate(times):
        stamp = str(stamp)
        if stamp >= today:
            continue
        days.append({"date": stamp, "precipitation_mm": _number(_at(sums, i))})
    return days[-7:]


def _forecast_days(daily: dict, today: str) -> list[dict]:
    """Today + next 6 days: min/max temp, precipitation, probability, condition."""
    days: list[dict] = []
    times = daily.get("time") or []
    for i, stamp in enumerate(times):
        stamp = str(stamp)
        if stamp < today:
            continue
        if len(days) >= 7:
            break
        code = _at(daily.get("weather_code"), i)
        days.append({
            "date": stamp,
            "weekday": _weekday(stamp),
            "temp_min_c": _number(_at(daily.get("temperature_2m_min"), i)),
            "temp_max_c": _number(_at(daily.get("temperature_2m_max"), i)),
            "precipitation_mm": _number(_at(daily.get("precipitation_sum"), i)),
            "precipitation_probability_max_pct": _number(
                _at(daily.get("precipitation_probability_max"), i)
            ),
            "weather_code": _number(code),
            "condition": condition_for(code),
        })
    return days


def _weekday(stamp: str) -> str | None:
    try:
        return date.fromisoformat(stamp[:10]).strftime("%A")
    except ValueError:
        return None
