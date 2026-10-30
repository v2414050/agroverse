"""Weather & location API — INFORMATION LAYER ONLY.

These endpoints expose live, model-based environmental data from Open-Meteo
for a location the farmer searches for. They are deliberately isolated from
the irrigation / energy / crop-advisor engines:

* nothing is written to the database,
* no sensor or demo reading is replaced,
* a provider outage answers 502 here and leaves every other endpoint
  untouched,
* forecast rain is labelled as a prediction and is never fed into the
  irrigation decision rules (that integration, if ever approved, is a
  separate change with its own tests).

Conventions follow app/main.py: plain sync handlers, HTTPException with
short farmer-readable messages, dicts with ok / meta fields.
"""

from fastapi import APIRouter, HTTPException

from .clients import open_meteo, soilgrids
from .clients.open_meteo import UpstreamError

router = APIRouter(prefix="/api/weather", tags=["weather"])


def _upstream(exc: UpstreamError) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail=(
            "Weather service is temporarily unavailable "
            f"({exc}). Please retry in a moment."
        ),
    )


@router.get("/locations")
def search_locations(query: str = "", count: int = 5):
    """Search for a place by name -> candidate list with coordinates.

    Returns every candidate (name, district, state, country, lat/lon) so
    similarly named places can be disambiguated by the user — the API never
    silently picks one. An empty result list is a valid 'no match' state.
    """
    try:
        results, meta = open_meteo.search_locations(query, count)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except UpstreamError as exc:
        raise _upstream(exc)

    return {
        "ok": True,
        "query": query.strip(),
        "count": len(results),
        "results": results,
        "meta": meta,
    }


@router.get("/summary")
def weather_summary(latitude: float, longitude: float):
    """Current weather + recent rainfall + 7-day forecast for one point.

    Values carry explicit `kind` labels:
      current   -> model_based_current (model-interpolated, not a station)
      rainfall  -> modelled_rolling_24h + historical_daily_totals
      forecast  -> forecast (predictions, not observations)
    Unavailable numbers are null — never a fabricated 0.
    """
    try:
        payload, meta = open_meteo.fetch_environment(latitude, longitude)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except UpstreamError as exc:
        raise _upstream(exc)

    return {"ok": True, "source": "external_live", "meta": meta, **payload}


@router.get("/soil")
def soil_info(latitude: float, longitude: float):
    """Estimated soil properties for one point (ISRIC SoilGrids 2.0).

    Always answers 200 with an `available` flag: the global SoilGrids
    service is currently in a degraded state (returns null estimates), and
    soil must never break the weather feature. Unavailable responses carry
    a truthful `reason` and `message` — values are never invented. The
    texture class is derived from the returned sand/silt/clay fractions;
    results are 250 m modelled estimates, not a field soil test.
    """
    try:
        payload, meta = soilgrids.fetch_soil(latitude, longitude)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"ok": True, **payload, "meta": meta}
