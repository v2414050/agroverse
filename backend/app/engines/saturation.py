"""Anti-saturation irrigation engine — pure decision functions.

Implements the project's documented irrigation model (Algorithms PDF,
section 3 "Irrigation scheduler with weather pause") extended with the
SATURATED state required by the Anti-Saturation task:

    volume_L = (upper - moisture) / 100 * root_depth_mm * area_m2
    duration_min = volume_L / (pump_flow_lpm * pump_efficiency)

Decision states, driven by the configured crop band (config.py):

    SATURATED  moisture > saturation threshold -> avoid irrigation, monitor
    HIGH       upper < moisture <= saturation  -> review / delay irrigation
    OPTIMAL    lower <= moisture <= upper      -> maintain current conditions
    DRY        moisture < lower                -> irrigate (schedule, or now
                                                  when below critical_low)
    UNKNOWN    moisture missing                -> ask for a reading

Rainfall assumption: the PDF pauses on a *forecast* (prob >= 0.60 and
>= 5 mm in 6 h). This build has no forecast feed, so we use measured
rainfall of the last 24 h against the same 5 mm threshold instead, and
say so in the explanation. A critical reading still overrides rain.

This module is a pure function library: data in, plain dict out, no
database or HTTP calls.
"""

from ..config import (
    CROP_BANDS,
    DEFAULT_BAND,
    PUMP_EFFICIENCY,
    PUMP_FLOW_LPM,
    RAIN_PAUSE_MM,
    READING_FRESH_HOURS,
    READING_STALE_HOURS,
    ROOT_DEPTH_MM,
    ROOT_DEPTH_MM_DEFAULT,
    SOIL_ADJUSTMENT,
    SOIL_ADJUSTMENT_DEFAULT,
    MoistureBand,
)

DRY = "DRY"
OPTIMAL = "OPTIMAL"
HIGH = "HIGH"
SATURATED = "SATURATED"
UNKNOWN = "UNKNOWN"


def band_for(crop: str | None, soil_type: str | None, growth_stage: str | None = None) -> dict:
    """Resolve the configured moisture band for a crop/soil/stage.

    Returns the band shifted by the soil-texture adjustment (percentage
    points) plus the effective root depth used by the refill formula.
    """
    crop_key = (crop or "").strip().lower()
    band: MoistureBand = CROP_BANDS.get(crop_key, DEFAULT_BAND)
    crop_known = crop_key in CROP_BANDS

    soil_key = (soil_type or "").strip().lower()
    delta = SOIL_ADJUSTMENT.get(soil_key, SOIL_ADJUSTMENT_DEFAULT)
    soil_known = soil_key in SOIL_ADJUSTMENT

    stage_key = (growth_stage or "").strip().lower()
    root_depth = ROOT_DEPTH_MM.get(stage_key, ROOT_DEPTH_MM_DEFAULT)

    return {
        "lower": round(max(0.0, band.lower + delta), 1),
        "upper": round(max(0.0, band.upper + delta), 1),
        "saturation": round(max(0.0, band.saturation + delta), 1),
        "critical_low": round(max(0.0, band.critical_low + delta), 1),
        "root_depth_mm": root_depth,
        "soil_adjustment_pct": delta,
        "crop_band_known": crop_known,
        "soil_known": soil_known,
    }


def _confidence(*, moisture_known: bool, band: dict, reading_age_hours: float | None) -> dict:
    """Data-quality indicator: high / medium / low plus human-readable why."""
    reasons: list[str] = []
    score = 0

    if moisture_known:
        score += 2
    else:
        reasons.append("No moisture reading available.")

    if band["crop_band_known"]:
        score += 2
    else:
        reasons.append(f"Unknown crop — using the default band instead of a crop-specific one.")

    if band["soil_known"]:
        score += 1
    else:
        reasons.append("Soil type missing — no texture adjustment applied.")

    if reading_age_hours is None:
        reasons.append("Reading timestamp unknown — freshness cannot be checked.")
        score += 0
    elif reading_age_hours <= READING_FRESH_HOURS:
        score += 2
    elif reading_age_hours <= READING_STALE_HOURS:
        score += 1
        reasons.append(f"Reading is {reading_age_hours:.0f} h old — verify before acting.")
    else:
        reasons.append(f"Reading is {reading_age_hours:.0f} h old (stale) — treat as indicative only.")

    if not moisture_known:
        level = "low"
    elif score >= 6:
        level = "high"
    elif score >= 4:
        level = "medium"
    else:
        level = "low"

    return {"level": level, "reasons": reasons}


def _refill_estimate(moisture: float, band: dict, area_hectares: float | None) -> tuple[float | None, float | None]:
    """Documented refill volume (litres) and pump duration (minutes)."""
    if area_hectares is None or area_hectares <= 0:
        return None, None
    deficit = max(0.0, band["upper"] - moisture)
    area_m2 = area_hectares * 10_000
    volume_l = deficit / 100 * band["root_depth_mm"] * area_m2
    duration_min = volume_l / (PUMP_FLOW_LPM * PUMP_EFFICIENCY)
    return round(volume_l), round(duration_min)


def analyze_moisture(
    moisture_pct: float | None,
    *,
    crop: str | None = None,
    soil_type: str | None = None,
    growth_stage: str | None = None,
    area_hectares: float | None = None,
    rainfall_mm_24h: float | None = None,
    hours_since_irrigation: float | None = None,
    reading_age_hours: float | None = None,
    source: str = "stored demo reading",
) -> dict:
    """Analyse one soil-moisture value and recommend an irrigation action.

    Raises ValueError when the moisture value is present but invalid —
    callers (the API route) translate that into a 422.
    """
    if moisture_pct is not None:
        if not isinstance(moisture_pct, (int, float)) or isinstance(moisture_pct, bool):
            raise ValueError("moisture_pct must be a number between 0 and 100.")
        if not 0 <= float(moisture_pct) <= 100:
            raise ValueError("moisture_pct must be between 0 and 100 percent.")

    band = band_for(crop, soil_type, growth_stage)
    confidence = _confidence(
        moisture_known=moisture_pct is not None, band=band, reading_age_hours=reading_age_hours
    )

    rain_mm = rainfall_mm_24h if isinstance(rainfall_mm_24h, (int, float)) else None
    rain_pause = rain_mm is not None and rain_mm >= RAIN_PAUSE_MM

    target = {
        "lower_pct": band["lower"],
        "upper_pct": band["upper"],
        "saturation_pct": band["saturation"],
        "critical_low_pct": band["critical_low"],
        "root_depth_mm": band["root_depth_mm"],
        "soil_adjustment_pct": band["soil_adjustment_pct"],
    }

    base = {
        "current_moisture_pct": moisture_pct,
        "target": target,
        "crop": crop,
        "growth_stage": growth_stage,
        "soil_type": soil_type,
        "rainfall_mm_24h": rain_mm,
        "rain_pause_threshold_mm": RAIN_PAUSE_MM,
        "rain_advises_pause": rain_pause,
        "hours_since_irrigation": hours_since_irrigation,
        "confidence": confidence,
        "source": source,
        "formula": "volume_L = (upper - moisture)/100 * root_depth_mm * area_m2; "
        "duration_min = volume_L / (flow_lpm * efficiency)",
    }

    # --- missing sensor value ------------------------------------------
    if moisture_pct is None:
        return {
            **base,
            "status": UNKNOWN,
            "action": "add_sensor_reading",
            "action_label": "Add a soil-moisture reading",
            "explanation": (
                "No soil-moisture value is available, so no irrigation decision can be "
                "made. Enter a reading or connect a sensor, then analyse again."
            ),
            "rule": "missing_moisture",
            "suggested_volume_l": None,
            "suggested_duration_min": None,
        }

    m = float(moisture_pct)
    volume_l, duration_min = _refill_estimate(m, band, area_hectares)

    # --- SATURATED ------------------------------------------------------
    if m > band["saturation"]:
        return {
            **base,
            "status": SATURATED,
            "action": "avoid_irrigation_monitor",
            "action_label": "Do not irrigate — monitor conditions",
            "explanation": (
                f"Soil moisture {m:g}% is above the {band['saturation']:g}% saturation "
                f"threshold. The root zone is at or beyond field capacity, so irrigation "
                f"would be wasted and risks waterlogging. Avoid unnecessary irrigation, "
                f"watch for standing water or poor drainage, and re-analyse after the "
                f"soil drains."
                + (
                    f" The last 24 h saw {rain_mm:g} mm of rain, which supports the high reading."
                    if rain_mm
                    else ""
                )
            ),
            "rule": "saturation_exceeded",
            "suggested_volume_l": None,
            "suggested_duration_min": None,
        }

    # --- HIGH -----------------------------------------------------------
    if m > band["upper"]:
        rain_note = (
            f" Recent rainfall ({rain_mm:g} mm / 24 h) reinforces the delay"
            if rain_pause
            else (
                f" Measured rain ({rain_mm:g} mm / 24 h) is below the "
                f"{RAIN_PAUSE_MM:g} mm pause threshold, but the soil is already wet."
                if rain_mm
                else ""
            )
        )
        return {
            **base,
            "status": HIGH,
            "action": "review_and_delay",
            "action_label": "Review and delay irrigation",
            "explanation": (
                f"Soil moisture {m:g}% is above the preferred range of "
                f"{band['lower']:g}–{band['upper']:g}%, so the crop does not need water "
                f"now. Delay the next cycle, review the schedule, and re-analyse once "
                f"moisture falls back into the target band.{rain_note}"
            ),
            "rule": "above_preferred_band",
            "suggested_volume_l": None,
            "suggested_duration_min": None,
        }

    # --- DRY (below lower bound) ---------------------------------------
    if m < band["lower"]:
        critical = m < band["critical_low"]
        irrigate_now = critical or not rain_pause

        if critical:
            explanation = (
                f"Soil moisture {m:g}% is below the critical level of "
                f"{band['critical_low']:g}% for {crop or 'this crop'}. Irrigation may be "
                f"required now — the safety override beats the rain-pause rule because "
                f"the crop is at risk of stress."
            )
            rule = "critical_dry"
            action = "irrigate_now"
            action_label = "Irrigate now (critical)"
        elif rain_pause:
            explanation = (
                f"Soil moisture {m:g}% is below the {band['lower']:g}% target, but the "
                f"last 24 h recorded {rain_mm:g} mm of rain (>= the {RAIN_PAUSE_MM:g} mm "
                f"pause threshold). Delay irrigation and re-analyse after the rain "
                f"effect shows in the reading."
            )
            rule = "rain_pause"
            action = "delay_for_rain"
            action_label = "Delay — recent rainfall"
        else:
            explanation = (
                f"Soil moisture {m:g}% is below the {band['lower']:g}% target for "
                f"{crop or 'this crop'}"
                + (f" ({growth_stage} stage)" if growth_stage else "")
                + f", so irrigation may be required. Schedule a refill toward "
                f"{band['upper']:g}% — the estimated cycle is shown below."
            )
            rule = "below_target"
            action = "schedule_irrigation"
            action_label = "Schedule irrigation"

        return {
            **base,
            "status": DRY,
            "action": action,
            "action_label": action_label,
            "explanation": explanation,
            "rule": rule,
            "suggested_volume_l": volume_l if irrigate_now else volume_l,
            "suggested_duration_min": duration_min if irrigate_now else duration_min,
        }

    # --- OPTIMAL ---------------------------------------------------------
    extra = (
        f" The last irrigation was {hours_since_irrigation:.0f} h ago, which explains "
        f"the good level."
        if hours_since_irrigation is not None and hours_since_irrigation < 24
        else ""
    )
    return {
        **base,
        "status": OPTIMAL,
        "action": "maintain",
        "action_label": "Maintain current conditions",
        "explanation": (
            f"Soil moisture {m:g}% sits inside the {band['lower']:g}–{band['upper']:g}% "
            f"target band for {crop or 'this crop'}"
            + (f" at the {growth_stage} stage" if growth_stage else "")
            + f". Additional irrigation would push moisture toward the "
            f"{band['saturation']:g}% saturation threshold and waste water, so no cycle "
            f"is needed — keep the current schedule and monitor.{extra}"
        ),
        "rule": "in_band",
        "suggested_volume_l": None,
        "suggested_duration_min": None,
    }
