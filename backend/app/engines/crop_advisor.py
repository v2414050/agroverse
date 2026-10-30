"""Terrain-Aware Agro-Advisory Engine — pure decision functions.

Ranks the crops in config.CROP_PROFILES against the farm's conditions using
transparent, weighted rules:

    soil type    25  — is the soil in the crop's preferred texture list?
    water        25  — seasonal supply (rainfall + irrigation top-up) vs the
                       crop's seasonal water requirement
    temperature  20  — inside the crop's suitable temperature range?
    pH           15  — inside the crop's preferred pH range? (partial score
                       just outside it, to reflect amendable acidity/alkalinity)
    nutrients    15  — measured N/P/K inside the crop's typical kg/ha bands?
                       (only the nutrients actually measured are scored)
    season       10  — is this the crop's normal sowing season?
    slope        10  — field slope within the crop's terrain tolerance?

Suitability score = weighted average of the criteria that could be evaluated,
scaled 0-100. It is a FIT measure against the demo requirement dataset — it is
NOT a yield prediction and carries no guarantee.

Honesty rules (same contract as the other two engines):
  * Nothing is invented. Missing inputs are excluded from the score, listed
    in `missing`, and make the result `provisional`.
  * If literally nothing can be evaluated, the engine returns
    `insufficient_data: True` with no rankings instead of fake numbers.
  * Fertilizer guidance is directional only. Without measured N/P/K the
    advice is "take a soil test" — rates are never fabricated.
  * Every limiting factor carries its explanation; a low score is always
    justified by named criteria.

Data in, plain dict out: no database or HTTP inside.
"""

from ..config import (
    CROP_PROFILES,
    SEASON_LABELS,
    SEASON_MONTHS,
    WATER_LABELS,
    WATER_TOPUP_MM,
    CropProfile,
)

# Criterion weights (must sum sensibly; renormalised over available criteria).
WEIGHTS = {
    "soil": 25.0,
    "water": 25.0,
    "temperature": 20.0,
    "ph": 15.0,
    "nutrients": 15.0,
    "season": 10.0,
    "slope": 10.0,
}

# pH within this many units outside the preferred band is "marginal"
# (amendable) rather than a hard mismatch.
PH_MARGINAL = 0.5

VERDICTS = (
    (75, "recommended", "Recommended"),
    (55, "suitable_with_caution", "Suitable with caution"),
    (35, "marginal", "Marginal fit"),
    (0, "not_recommended", "Not recommended"),
)

# Numeric sanity bounds — anything outside raises ValueError (route -> 422).
BOUNDS = {
    "soil_ph": (0.0, 14.0),
    "temperature_c": (-30.0, 60.0),
    "rainfall_mm": (0.0, 5000.0),
    "nitrogen_kg_ha": (0.0, 1000.0),
    "phosphorus_kg_ha": (0.0, 1000.0),
    "potassium_kg_ha": (0.0, 1000.0),
    "slope_pct": (0.0, 90.0),
}

NUTRIENT_BANDS = (
    ("nitrogen_kg_ha", "Nitrogen (N)", "n"),
    ("phosphorus_kg_ha", "Phosphorus (P)", "p"),
    ("potassium_kg_ha", "Potassium (K)", "k"),
)


def _fmt(value: float) -> str:
    return f"{value:g}"


def _range(lo: float, hi: float) -> str:
    return f"{_fmt(lo)}–{_fmt(hi)}"


def _soil_key(soil_type: str | None) -> str | None:
    """Normalise a soil label ('Loamy', ' black ') to a config key."""
    if not soil_type or not isinstance(soil_type, str):
        return None
    return soil_type.strip().lower()


def validate(conditions: dict) -> None:
    """Raise ValueError on present-but-invalid numbers/enums.

    Missing (None) values are fine — they become 'missing information'.
    """
    for field, (lo, hi) in BOUNDS.items():
        value = conditions.get(field)
        if value is None:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{field} must be a number between {lo:g} and {hi:g}.")
        if not lo <= float(value) <= hi:
            raise ValueError(f"{field} must be between {lo:g} and {hi:g}.")

    season = conditions.get("season")
    if season is not None and season not in SEASON_MONTHS:
        raise ValueError(
            f"season must be one of: {', '.join(SEASON_MONTHS)} (or omitted)."
        )

    water = conditions.get("water_availability")
    if water is not None and water not in WATER_TOPUP_MM:
        raise ValueError(
            f"water_availability must be one of: {', '.join(WATER_TOPUP_MM)} (or omitted)."
        )


def _verdict_for(score: float) -> tuple[str, str]:
    for threshold, key, label in VERDICTS:
        if score >= threshold:
            return key, label
    return VERDICTS[-1][1:]


def _check_soil(cond: dict, profile: CropProfile) -> dict:
    soil = _soil_key(cond.get("soil_type"))
    if soil is None:
        return {
            "provided": False,
            "missing": "Soil type not provided — texture fit is unverified.",
        }
    suitable = ", ".join(profile.soil_types)
    if soil in profile.soil_types:
        return {
            "provided": True, "score": 100.0,
            "detail": f"{soil.title()} soil is well suited to {profile.name}.",
        }
    return {
        "provided": True, "score": 20.0,
        "detail": (
            f"{soil.title()} soil is outside {profile.name}'s preferred textures "
            f"({suitable}) — yield potential drops without significant amendment."
        ),
    }


def _check_ph(cond: dict, profile: CropProfile) -> dict:
    ph = cond.get("soil_ph")
    if ph is None:
        return {
            "provided": False,
            "missing": "Soil pH not provided — pH fit is unverified (take a soil test).",
        }
    ph = float(ph)
    band = _range(profile.ph_min, profile.ph_max)
    if profile.ph_min <= ph <= profile.ph_max:
        return {
            "provided": True, "score": 100.0,
            "detail": f"Soil pH {_fmt(ph)} sits inside the preferred {band} range.",
        }
    distance = min(abs(ph - profile.ph_min), abs(ph - profile.ph_max))
    if distance <= PH_MARGINAL:
        return {
            "provided": True, "score": 60.0,
            "detail": (
                f"Soil pH {_fmt(ph)} is just outside the preferred {band} range "
                f"(by {distance:.1f} units) — usually correctable with lime or "
                f"gypsum, but confirm with a soil test first."
            ),
        }
    side = "below" if ph < profile.ph_min else "above"
    return {
        "provided": True, "score": 10.0,
        "detail": (
            f"Soil pH {_fmt(ph)} is well {side} the preferred {band} range for "
            f"{profile.name} — this is a hard limitation without soil amendment."
        ),
    }


def _check_temperature(cond: dict, profile: CropProfile) -> dict:
    temp = cond.get("temperature_c")
    if temp is None:
        return {
            "provided": False,
            "missing": "Temperature not provided — climate fit is unverified.",
        }
    temp = float(temp)
    band = _range(profile.temp_min_c, profile.temp_max_c)
    if profile.temp_min_c <= temp <= profile.temp_max_c:
        return {
            "provided": True, "score": 100.0,
            "detail": f"Temperature {_fmt(temp)}°C is inside the suitable {band}°C range.",
        }
    distance = (
        profile.temp_min_c - temp if temp < profile.temp_min_c
        else temp - profile.temp_max_c
    )
    score = max(0.0, 100.0 - 25.0 * distance)
    return {
        "provided": True, "score": score,
        "detail": (
            f"Temperature {_fmt(temp)}°C is {distance:.0f}°C outside the suitable "
            f"{band}°C range for {profile.name} — stress or crop failure risk."
        ),
    }


def _check_water(cond: dict, profile: CropProfile) -> dict:
    rainfall = cond.get("rainfall_mm")
    availability = cond.get("water_availability")
    if rainfall is None and availability is None:
        return {
            "provided": False,
            "missing": (
                "Seasonal rainfall and irrigation access not provided — water "
                "fit is unverified."
            ),
        }
    if rainfall is None or availability is None:
        return {
            "provided": False,
            "missing": (
                "Both seasonal rainfall AND irrigation access are needed to "
                "estimate water supply — one of them is missing."
            ),
        }
    topup = WATER_TOPUP_MM[availability]
    supply = float(rainfall) + topup
    need = float(profile.water_requirement_mm)
    ratio = supply / need
    supply_note = (
        f"{_fmt(float(rainfall))} mm rain + {topup} mm from "
        f"{WATER_LABELS[availability].split(' (')[0].lower()} irrigation"
    )
    if ratio >= 1.0:
        return {
            "provided": True, "score": 100.0,
            "detail": (
                f"Estimated seasonal supply (~{_fmt(supply)} mm: {supply_note}) "
                f"covers {profile.name}'s ~{_fmt(need)} mm water need."
            ),
        }
    if ratio >= 0.7:
        score = 100.0 - (1.0 - ratio) / 0.3 * 60.0   # 40–100
        return {
            "provided": True, "score": score,
            "detail": (
                f"Estimated seasonal supply (~{_fmt(supply)} mm: {supply_note}) "
                f"falls short of {profile.name}'s ~{_fmt(need)} mm need — "
                f"supplemental irrigation would be required."
            ),
        }
    score = 15.0 + ratio / 0.7 * 25.0               # 15–40
    return {
        "provided": True, "score": score,
        "detail": (
            f"Estimated seasonal supply (~{_fmt(supply)} mm: {supply_note}) is "
            f"far below {profile.name}'s ~{_fmt(need)} mm need — water would be "
            f"the binding constraint."
        ),
    }


def _check_nutrients(cond: dict, profile: CropProfile) -> dict:
    provided_rows = []
    missing_labels = []
    for field, label, attr in NUTRIENT_BANDS:
        value = cond.get(field)
        if value is None:
            missing_labels.append(label)
            continue
        lo, hi = getattr(profile.nutrients, attr)
        value = float(value)
        if value < lo:
            provided_rows.append({
                "nutrient": label, "status": "below_band", "score": 25.0,
                "detail": (
                    f"Measured {label} {_fmt(value)} kg/ha is below the typical "
                    f"{_range(lo, hi)} kg/ha band for {profile.name}."
                ),
            })
        elif value > hi:
            provided_rows.append({
                "nutrient": label, "status": "above_band", "score": 60.0,
                "detail": (
                    f"Measured {label} {_fmt(value)} kg/ha is above the typical "
                    f"{_range(lo, hi)} kg/ha band — excess may leach or delay "
                    f"maturity."
                ),
            })
        else:
            provided_rows.append({
                "nutrient": label, "status": "adequate", "score": 100.0,
                "detail": (
                    f"Measured {label} {_fmt(value)} kg/ha is inside the typical "
                    f"{_range(lo, hi)} kg/ha band for {profile.name}."
                ),
            })

    if not provided_rows:
        return {
            "provided": False,
            "missing": "N/P/K not provided — nutrient fit is unverified (take a soil test).",
        }
    score = sum(row["score"] for row in provided_rows) / len(provided_rows)
    return {"provided": True, "score": score, "nutrients": provided_rows,
            "missing_nutrients": missing_labels}


def _check_season(cond: dict, profile: CropProfile) -> dict:
    season = cond.get("season")
    if season is None:
        return {
            "provided": False,
            "missing": "Season not provided — sowing-window fit is unverified.",
        }
    labels = " / ".join(SEASON_LABELS[s] for s in profile.seasons)
    if season in profile.seasons:
        return {
            "provided": True, "score": 100.0,
            "detail": f"{SEASON_LABELS[season]} matches {profile.name}'s normal sowing window ({labels}).",
        }
    return {
        "provided": True, "score": 20.0,
        "detail": (
            f"{SEASON_LABELS[season]} is outside {profile.name}'s normal sowing "
            f"window ({labels}) — off-season sowing is possible only with extra "
            f"management."
        ),
    }


def _check_slope(cond: dict, profile: CropProfile) -> dict:
    slope = cond.get("slope_pct")
    if slope is None:
        return {
            "provided": False,
            "missing": "Field slope not provided — terrain compatibility is unverified.",
        }
    slope = float(slope)
    if slope <= profile.max_slope_pct:
        return {
            "provided": True, "score": 100.0,
            "detail": (
                f"Slope {_fmt(slope)}% is within {profile.name}'s {_fmt(profile.max_slope_pct)}% "
                f"terrain tolerance — erosion risk is manageable."
            ),
        }
    return {
        "provided": True, "score": 0.0,
        "detail": (
            f"Slope {_fmt(slope)}% exceeds {profile.name}'s {_fmt(profile.max_slope_pct)}% "
            f"terrain tolerance — without terracing or contour bunding, erosion "
            f"and runoff make this a poor fit."
        ),
    }


def fertilizer_guidance(cond: dict, profile: CropProfile) -> dict:
    """Directional nutrient advice — only from measured values, never invented rates."""
    measured = {label: cond.get(field) for field, label, _ in NUTRIENT_BANDS}
    missing = [label for label, value in measured.items() if value is None]
    if len(missing) == len(measured):
        return {
            "available": False,
            "advice": (
                "No N/P/K measurements were provided, so no fertilizer guidance "
                "can be given — precise rates would be invented. Take a soil "
                "test (N, P, K and pH) and re-run the advisor."
            ),
            "missing_nutrients": missing,
            "nutrients": [],
        }
    if missing:
        return {
            "available": False,
            "advice": (
                f"{', '.join(missing)} not measured — fertilizer advice would be "
                f"incomplete. Take a soil test covering all of N, P and K before "
                f"buying inputs."
            ),
            "missing_nutrients": missing,
            "nutrients": [],
        }

    rows = []
    deficits = []
    for field, label, attr in NUTRIENT_BANDS:
        value = float(cond[field])
        lo, hi = getattr(profile.nutrients, attr)
        if value < lo:
            status, text = "below_band", "below"
            deficits.append(label)
        elif value > hi:
            status, text = "above_band", "above"
        else:
            status, text = "adequate", "inside"
        rows.append({
            "nutrient": label, "status": status,
            "measured_kg_ha": value, "band_kg_ha": [lo, hi],
            "detail": (
                f"{label} {_fmt(value)} kg/ha is {text} the typical "
                f"{_range(lo, hi)} kg/ha band for {profile.name}."
            ),
        })

    if deficits:
        advice = (
            f"Measured {', '.join(deficits)} {'is' if len(deficits) == 1 else 'are'} "
            f"below {profile.name}'s typical requirement band. Correcting the "
            f"deficit usually lifts yield most, but this engine deliberately does "
            f"NOT prescribe quantities — set rates with a local agronomy advisor "
            f"or your district soil-test laboratory."
        )
    else:
        advice = (
            f"Measured N, P and K all sit inside {profile.name}'s typical bands — "
            f"no nutrient deficit is flagged. Base any top-dressing on local "
            f"advisor guidance rather than this demo."
        )
    return {"available": True, "advice": advice,
            "missing_nutrients": [], "nutrients": rows}


def score_crop(conditions: dict, profile: CropProfile) -> dict:
    """Score one crop against the given (validated) farm conditions."""
    checks = {
        "soil": _check_soil(conditions, profile),
        "ph": _check_ph(conditions, profile),
        "water": _check_water(conditions, profile),
        "temperature": _check_temperature(conditions, profile),
        "nutrients": _check_nutrients(conditions, profile),
        "season": _check_season(conditions, profile),
        "slope": _check_slope(conditions, profile),
    }

    favorable: list[str] = []
    limiting: list[str] = []
    missing: list[str] = []
    criteria = []
    weight_sum = 0.0
    weighted = 0.0

    for name, weight in WEIGHTS.items():
        result = checks[name]
        if not result["provided"]:
            missing.append(result["missing"])
            criteria.append({"criterion": name, "provided": False,
                             "weight": weight, "score": None})
            continue
        score = float(result["score"])
        weight_sum += weight
        weighted += weight * score
        criteria.append({"criterion": name, "provided": True,
                         "weight": weight, "score": round(score, 1)})
        for row in result.get("nutrients", []):
            (favorable if row["score"] >= 80 else limiting).append(row["detail"])
        if "detail" in result:               # nutrients report per-row instead
            if score >= 80:
                favorable.append(result["detail"])
            elif score < 80:
                limiting.append(result["detail"])

    if weight_sum == 0:
        # Nothing at all could be evaluated — handled by recommend_crops.
        overall = None
    else:
        overall = round(weighted / weight_sum)

    verdict_key, verdict_label = _verdict_for(overall if overall is not None else 0)
    provisional = bool(missing)

    crop = profile.name
    if overall is None:
        explanation = f"No farm conditions were provided, so {crop} cannot be assessed."
    elif verdict_key == "recommended":
        explanation = (
            f"{crop} scores {overall}/100 against the provided conditions — the "
            f"measured factors fit its requirement profile well."
        )
    elif verdict_key == "suitable_with_caution":
        explanation = (
            f"{crop} scores {overall}/100 — broadly suitable, but the limiting "
            f"factors below should be addressed before committing."
        )
    elif verdict_key == "marginal":
        explanation = (
            f"{crop} scores {overall}/100 — only a marginal fit; at least one "
            f"major requirement is not met."
        )
    else:
        explanation = (
            f"{crop} scores {overall}/100 — the conditions do not meet its core "
            f"requirements, so it is not recommended."
        )
    if provisional:
        explanation += (
            f" PROVISIONAL: {len(missing)} input(s) were missing, so the score is "
            f"based on partial information — not a complete assessment."
        )

    next_steps: list[str] = []
    if missing:
        next_steps.append("Take a soil test (NPK + pH) and note seasonal rainfall to move from provisional to confident.")
    if any(c["criterion"] == "slope" and c["score"] == 0 for c in criteria):
        next_steps.append("Measure field slope properly; if steep, plan terracing or pick a better-suited crop.")
    if any(c["criterion"] == "soil" and c["score"] is not None and c["score"] < 60 for c in criteria):
        next_steps.append(f"Either amend the soil or choose a crop suited to {_soil_key(conditions.get('soil_type')) or 'the local'} texture.")
    if any(c["criterion"] == "water" and c["score"] is not None and c["score"] < 60 for c in criteria):
        next_steps.append("Budget for irrigation capacity or shift to a lower-water crop for this plot.")
    next_steps.append("Confirm this shortlist with a local agronomy advisor before buying seed.")

    return {
        "crop": crop,
        "score": overall,
        "verdict": verdict_key,
        "verdict_label": verdict_label,
        "provisional": provisional,
        "explanation": explanation,
        "favorable": favorable,
        "limiting": limiting,
        "missing": missing,
        "next_steps": next_steps[:4],
        "fertilizer": fertilizer_guidance(conditions, profile),
        "criteria": criteria,
        "requirements": {
            "soils": [s.title() for s in profile.soil_types],
            "ph_range": _range(profile.ph_min, profile.ph_max),
            "temp_range_c": _range(profile.temp_min_c, profile.temp_max_c),
            "water_need_mm": profile.water_requirement_mm,
            "seasons": [SEASON_LABELS[s] for s in profile.seasons],
            "max_slope_pct": profile.max_slope_pct,
            "note": profile.note,
        },
    }


def recommend_crops(conditions: dict, profiles: dict[str, CropProfile] | None = None,
                    *, top: int | None = None) -> dict:
    """Rank all demo crops against the conditions (plain dict in, dict out).

    `conditions` keys (all optional, None = not provided):
        soil_type, soil_ph, temperature_c, rainfall_mm, season,
        water_availability, slope_pct, nitrogen_kg_ha, phosphorus_kg_ha,
        potassium_kg_ha
    """
    conditions = conditions or {}
    validate(conditions)
    profiles = profiles if profiles is not None else CROP_PROFILES

    missing_all: list[str] = []
    evaluated_any = False
    probe = score_crop(conditions, next(iter(profiles.values())))
    missing_label = {
        "soil": "Soil type not provided.",
        "ph": "Soil pH not provided.",
        "water": "Seasonal rainfall + irrigation access not provided.",
        "temperature": "Temperature not provided.",
        "nutrients": "N/P/K measurements not provided.",
        "season": "Season not provided.",
        "slope": "Field slope not provided.",
    }
    for criterion in probe["criteria"]:
        if criterion["provided"]:
            evaluated_any = True
        else:
            missing_all.append(missing_label[criterion["criterion"]])

    if not evaluated_any:
        return {
            "insufficient_data": True,
            "provisional": True,
            "recommendations": [],
            "missing": missing_all,
            "provided": [],
            "summary": {
                "count": 0,
                "recommended_count": 0,
                "top_crop": None,
                "top_score": None,
                "provisional": True,
                "note": (
                    "No farm conditions were provided, so no ranking was produced "
                    "— the engine does not invent measurements."
                ),
            },
        }

    ranked = sorted(
        (
            score_crop(conditions, profile)
            for profile in profiles.values()
        ),
        key=lambda r: (-(r["score"] or 0), r["crop"]),
    )
    if top is not None:
        ranked = ranked[:top]

    provided = [c["criterion"] for c in probe["criteria"] if c["provided"]]
    provisional = any(r["provisional"] for r in ranked)

    return {
        "insufficient_data": False,
        "provisional": provisional,
        "recommendations": ranked,
        "missing": missing_all,
        "provided": provided,
        "summary": {
            "count": len(ranked),
            "recommended_count": sum(
                1 for r in ranked if r["verdict"] == "recommended"
            ),
            "top_crop": ranked[0]["crop"],
            "top_score": ranked[0]["score"],
            "top_verdict": ranked[0]["verdict_label"],
            "provisional": provisional,
            "note": (
                "Scores are a transparent rule-based fit against the demo "
                "requirement dataset (config.CROP_PROFILES) — a suitability "
                "indicator, not a yield prediction or guarantee."
            ),
        },
    }
