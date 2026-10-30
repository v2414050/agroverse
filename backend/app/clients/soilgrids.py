"""ISRIC SoilGrids 2.0 point client — estimated soil properties by coordinate.

Provider investigation (verified live 2026-10-23)
-------------------------------------------------
* SoilGrids REST (rest.isric.org) is the only no-API-key, openly licensed
  (CC BY 4.0), coordinate-based GLOBAL soil service; USDA Soil Data Access
  is US-only, OpenLandMap needs Google Earth Engine credentials, and no
  other free point API covers India.
* ISRIC has published a notice that the REST API had issues and was
  "temporarily paused". Live probes for Kanpur / Delhi / Pune today return
  HTTP 200 but every estimated value is ``null`` — the service answers but
  serves no data. This client therefore treats "all values null" as a
  first-class UNAVAILABLE state, never as zero and never as an invented
  soil type.

Honesty rules (product requirements)
------------------------------------
* Results are MODELLED 250 m grid estimates for the coordinates — regional
  context, not a measurement of the farmer's field; always say so.
* The USDA texture class is DERIVED deterministically from the returned
  sand/silt/clay fractions (transparent classification, not extra data).
* Any provider failure or null payload yields ``available: false`` with a
  truthful reason — the weather feature keeps working regardless.

Reuses the HTTP layer and TTL cache from the Open-Meteo client (single
place to patch in tests, single cache to clear).
"""

from . import open_meteo
from .open_meteo import (
    UpstreamError,
    _cache_get,
    _cache_put,
    _number,
    _validate_coords,
)

SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"

SOIL_TTL_S = 86400.0        # a 250 m soil grid does not change daily

PROVIDER = "ISRIC SoilGrids 2.0"
ATTRIBUTION = "Soil data © ISRIC (World Soil Information), CC BY 4.0"
RESOLUTION = "250 m modelled grid"
DISCLAIMER = (
    "Modelled estimates for this coordinate, not a measurement of your "
    "field — confirm with a local soil test before making decisions."
)

DEPTHS = ("0-5cm", "5-15cm", "15-30cm")
TEXTURE_PROPERTIES = ("clay", "sand", "silt")
EXTRA_PROPERTY = "ocd"  # organic carbon density

PAUSED_MESSAGE = (
    "The global SoilGrids service currently returns no estimates for this "
    "point (ISRIC has its REST API partially paused). Soil information is "
    "unavailable here for now — a local soil test is the reliable source."
)


def usda_texture_class(sand_pct, silt_pct, clay_pct) -> str | None:
    """USDA texture class from sand/silt/clay percentages.

    Ordered decision list following the official USDA texture triangle
    boundaries (sand / loamy sand / sandy loam / loam / silt loam / silt /
    sandy & silt clay loam / sandy clay / silty clay / clay). It is a
    deterministic, transparent derivation from the returned fractions —
    not additional measured data. None when inputs are missing.
    """
    if sand_pct is None or silt_pct is None or clay_pct is None:
        return None
    if sand_pct + silt_pct + clay_pct <= 0:
        return None
    if silt_pct + 1.5 * clay_pct < 15:
        return "Sand"
    if silt_pct + 2 * clay_pct < 30:
        return "Loamy sand"
    if clay_pct < 7 and silt_pct < 50:
        return "Sandy loam"
    if 7 <= clay_pct < 20 and sand_pct > 52:
        return "Sandy loam"
    if 7 <= clay_pct < 27 and sand_pct <= 52 and 28 <= silt_pct < 50:
        return "Loam"
    if 12 <= clay_pct < 27 and silt_pct >= 50:
        return "Silt loam"
    if clay_pct < 12 and 50 <= silt_pct < 80:
        return "Silt loam"
    if silt_pct >= 80 and clay_pct < 12:
        return "Silt"
    if 27 <= clay_pct < 40 and sand_pct <= 20:
        return "Silt clay loam"
    if 27 <= clay_pct < 40 and sand_pct > 20:
        return "Sandy clay loam"
    if clay_pct >= 35 and sand_pct > 45:
        return "Sandy clay"
    if clay_pct >= 40 and silt_pct >= 40:
        return "Silty clay"
    if clay_pct >= 40 and sand_pct <= 45:
        return "Clay"
    return "Unclassified"


def _unavailable(reason: str, message: str) -> dict:
    return {
        "available": False,
        "reason": reason,
        "message": message,
        "texture_class": None,
        "layers": [],
    }


def fetch_soil(latitude: float, longitude: float) -> tuple[dict, dict]:
    """Soil estimates for one coordinate.

    Returns (payload, meta). ``payload['available']`` is False (with a
    truthful ``reason`` / ``message``) instead of raising when the provider
    is paused, empty or unreachable — soil must never break the weather
    feature. Raises ValueError only for invalid coordinates.
    """
    _validate_coords(latitude, longitude)

    key = f"soil:{round(latitude, 3)}:{round(longitude, 3)}"
    cached = _cache_get(key, SOIL_TTL_S)
    if cached:
        return cached

    params = [("lon", longitude), ("lat", latitude), ("value", "mean")]
    for prop in TEXTURE_PROPERTIES + (EXTRA_PROPERTY,):
        params.append(("property", prop))
    for depth in DEPTHS:
        params.append(("depth", depth))
    query = "&".join(f"{k}={v}" for k, v in params)

    try:
        # via the module attribute so tests can patch the single HTTP layer
        data = open_meteo._get_json(f"{SOILGRIDS_URL}?{query}")
    except UpstreamError as exc:
        # Unavailable results are NOT cached: the provider may recover at
        # any moment and the next visit should see fresh truth.
        payload = _unavailable(
            "provider_unreachable",
            f"The soil data service could not be reached ({exc}).",
        )
        return payload, _meta(_fresh())

    payload = _parse_soil(data)
    if not payload["available"]:
        return payload, _meta(_fresh())
    return payload, _meta(_cache_put(key, payload))


def _fresh() -> dict:
    """Cache info for a deliberately-uncached (unavailable) response."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {"from_cache": False, "age_seconds": 0.0, "fetched_at": now}


def _meta(cache_info: dict) -> dict:
    return {
        "provider": PROVIDER,
        "attribution": ATTRIBUTION,
        "resolution": RESOLUTION,
        "disclaimer": DISCLAIMER,
        **cache_info,
    }


def _pct(value, d_factor) -> float | None:
    """SoilGrids returns mapped units (g/kg) with a division factor to %."""
    number = _number(value)
    if number is None:
        return None
    factor = _number(d_factor) or 1.0
    return round(number / factor, 1)


def _parse_soil(data: dict) -> dict:
    """Normalize a SoilGrids Feature payload; honest unavailable on nulls."""
    if not isinstance(data, dict):
        return _unavailable("invalid_response", PAUSED_MESSAGE)

    layers_raw = (data.get("properties") or {}).get("layers")
    if not isinstance(layers_raw, list):
        return _unavailable("invalid_response", PAUSED_MESSAGE)

    by_name: dict[str, dict] = {}
    for layer in layers_raw:
        if not isinstance(layer, dict) or layer.get("name") not in (
            *TEXTURE_PROPERTIES, EXTRA_PROPERTY
        ):
            continue
        d_factor = (layer.get("unit_measure") or {}).get("d_factor")
        for depth in layer.get("depths") or []:
            label = depth.get("label")
            mean = (depth.get("values") or {}).get("mean")
            by_name.setdefault(label, {})[layer["name"]] = (mean, d_factor)

    layers: list[dict] = []
    for label in DEPTHS:
        entry = by_name.get(label)
        if not entry:
            continue
        sand = _pct(*entry.get("sand", (None, None)))
        silt = _pct(*entry.get("silt", (None, None)))
        clay = _pct(*entry.get("clay", (None, None)))
        ocd = _number((entry.get("ocd") or (None, None))[0])
        layers.append({
            "depth": label,
            "sand_pct": sand,
            "silt_pct": silt,
            "clay_pct": clay,
            "organic_carbon_density_dg_per_kg": ocd,
            "texture_class": usda_texture_class(sand, silt, clay),
        })

    if not layers or all(
        layer["sand_pct"] is None
        and layer["silt_pct"] is None
        and layer["clay_pct"] is None
        for layer in layers
    ):
        # The provider answered but serves no estimates (its published
        # "temporarily paused" state) — report unavailable, invent nothing.
        return _unavailable("provider_paused_or_no_data", PAUSED_MESSAGE)

    top = next(
        (
            layer
            for layer in layers
            if layer["sand_pct"] is not None
            and layer["silt_pct"] is not None
            and layer["clay_pct"] is not None
        ),
        None,
    )
    return {
        "available": True,
        "reason": None,
        "message": None,
        "texture_class": top["texture_class"] if top else None,
        "texture_class_depth": top["depth"] if top else None,
        "layers": layers,
    }
