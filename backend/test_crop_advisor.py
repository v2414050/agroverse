"""Tests for the Terrain-Aware Agro-Advisory engine (stdlib only).

Run from backend/:
    python test_crop_advisor.py

Covers: suitable conditions, unsuitable conditions, missing soil
information, missing weather information, invalid inputs, ranking order,
provisional marking, terrain (slope) limiting, water-supply logic, pH
marginal credit, nutrient/fertilizer rules, and required output fields.
"""

from app.engines.crop_advisor import (
    fertilizer_guidance,
    recommend_crops,
    score_crop,
    validate,
)
from app.config import CROP_PROFILES

# Loamy, neutral pH, rabi winter conditions — good for wheat.
GOOD_WHEAT = {
    "soil_type": "Loamy",
    "soil_ph": 6.8,
    "temperature_c": 18.0,
    "rainfall_mm": 450,
    "water_availability": "limited",
    "season": "rabi",
    "slope_pct": 2.0,
    "nitrogen_kg_ha": 120,
    "phosphorus_kg_ha": 50,
    "potassium_kg_ha": 40,
}

# Sandy, acidic, hot, rainfed and steep — bad for wheat.
BAD_WHEAT = {
    "soil_type": "Sandy",
    "soil_ph": 4.5,
    "temperature_c": 40.0,
    "rainfall_mm": 100,
    "water_availability": "rainfed",
    "season": "zaid",
    "slope_pct": 20.0,
    "nitrogen_kg_ha": 20,
    "phosphorus_kg_ha": 10,
    "potassium_kg_ha": 10,
}


def find(result, crop_key):
    by_key = {r["crop"].split(" ")[0].lower(): r for r in result["recommendations"]}
    return by_key[crop_key]


def test_suitable_crop_conditions():
    result = recommend_crops(GOOD_WHEAT)
    assert result["insufficient_data"] is False
    wheat = find(result, "wheat")
    assert wheat["verdict"] == "recommended", wheat
    assert wheat["score"] >= 75, wheat
    assert wheat["favorable"], wheat          # explained why it IS suitable
    assert wheat["provisional"] is False, wheat
    assert "PROVISIONAL" not in wheat["explanation"]


def test_unsuitable_crop_conditions():
    result = recommend_crops(BAD_WHEAT)
    wheat = find(result, "wheat")
    assert wheat["verdict"] == "not_recommended", wheat
    assert wheat["score"] < 35, wheat
    assert wheat["limiting"], wheat           # explained why it is NOT
    joined = " ".join(wheat["limiting"]).lower()
    assert "soil" in joined and "ph" in joined and "slope" in joined, joined


def test_missing_soil_information():
    cond = dict(GOOD_WHEAT, soil_type=None)
    result = recommend_crops(cond)
    assert result["provisional"] is True
    assert "Soil type not provided." in result["missing"]
    wheat = find(result, "wheat")
    assert wheat["provisional"] is True
    assert any("Soil type not provided" in m for m in wheat["missing"])
    # score still computed from the remaining criteria — nothing invented
    soil = next(c for c in wheat["criteria"] if c["criterion"] == "soil")
    assert soil["provided"] is False and soil["score"] is None


def test_missing_weather_information():
    cond = {
        "soil_type": "Loamy",
        "soil_ph": 6.8,
        "season": "rabi",
        # temperature, rainfall and water_availability all missing
    }
    result = recommend_crops(cond)
    assert result["provisional"] is True
    assert "Temperature not provided." in result["missing"]
    assert "Seasonal rainfall + irrigation access not provided." in result["missing"]
    wheat = find(result, "wheat")
    water = next(c for c in wheat["criteria"] if c["criterion"] == "water")
    assert water["provided"] is False


def test_invalid_inputs():
    for bad in (
        dict(GOOD_WHEAT, soil_ph=15),
        dict(GOOD_WHEAT, soil_ph=-1),
        dict(GOOD_WHEAT, temperature_c=100),
        dict(GOOD_WHEAT, rainfall_mm=99999),
        dict(GOOD_WHEAT, slope_pct=-5),
        dict(GOOD_WHEAT, nitrogen_kg_ha=-3),
        dict(GOOD_WHEAT, season="summer"),
        dict(GOOD_WHEAT, water_availability="flooded"),
        dict(GOOD_WHEAT, soil_ph="acidic"),
    ):
        try:
            recommend_crops(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {bad}")


def test_invalid_inputs_pass_none_through():
    # Missing values are not invalid — validate() accepts them.
    validate({"soil_ph": None, "temperature_c": None, "season": None})
    validate({})


def test_ranking_is_sorted_and_complete():
    result = recommend_crops(GOOD_WHEAT)
    scores = [r["score"] for r in result["recommendations"]]
    assert scores == sorted(scores, reverse=True), scores
    assert len(result["recommendations"]) == len(CROP_PROFILES)


def test_insufficient_data_short_circuit():
    result = recommend_crops({})
    assert result["insufficient_data"] is True
    assert result["recommendations"] == []
    assert len(result["missing"]) == 7        # every criterion listed
    assert "does not invent measurements" in result["summary"]["note"]
    result2 = recommend_crops(None)
    assert result2["insufficient_data"] is True


def test_every_crop_has_required_fields():
    result = recommend_crops(GOOD_WHEAT)
    for r in result["recommendations"]:
        for field in ("explanation", "favorable", "limiting", "missing",
                      "next_steps", "fertilizer", "criteria", "requirements",
                      "verdict_label", "provisional"):
            assert field in r, (r["crop"], field)
        assert r["explanation"], r["crop"]
        assert r["next_steps"], r["crop"]
        assert r["requirements"]["water_need_mm"] > 0


def test_provisional_marking_end_to_end():
    result = recommend_crops(dict(GOOD_WHEAT, soil_ph=None, slope_pct=None))
    assert result["provisional"] is True
    wheat = find(result, "wheat")
    assert "PROVISIONAL" in wheat["explanation"]


def test_slope_terrain_limiting():
    # Rice tolerates at most 2% slope; 5% must be flagged by terrain rules.
    cond = dict(GOOD_WHEAT, soil_type="Clay", season="kharif",
                temperature_c=28.0, rainfall_mm=1400,
                water_availability="assured", slope_pct=5.0)
    result = recommend_crops(cond)
    rice = find(result, "rice")
    slope = next(c for c in rice["criteria"] if c["criterion"] == "slope")
    assert slope["score"] == 0.0, rice
    assert any("terrain tolerance" in d for d in rice["limiting"])


def test_water_supply_rules():
    cond = dict(GOOD_WHEAT, soil_type="Clay", season="kharif",
                temperature_c=28.0, rainfall_mm=900, slope_pct=1.0)
    rainfed = find(recommend_crops(dict(cond, water_availability="rainfed")), "rice")
    assured = find(recommend_crops(dict(cond, water_availability="assured")), "rice")
    rainfed_water = next(c for c in rainfed["criteria"] if c["criterion"] == "water")
    assured_water = next(c for c in assured["criteria"] if c["criterion"] == "water")
    assert rainfed_water["score"] < 100 and assured_water["score"] == 100.0
    assert rainfed["score"] < assured["score"]


def test_ph_marginal_gets_partial_credit():
    marginal = score_crop(dict(GOOD_WHEAT, soil_ph=5.6), CROP_PROFILES["wheat"])
    far = score_crop(dict(GOOD_WHEAT, soil_ph=4.5), CROP_PROFILES["wheat"])
    ph_m = next(c for c in marginal["criteria"] if c["criterion"] == "ph")
    ph_f = next(c for c in far["criteria"] if c["criterion"] == "ph")
    assert ph_m["score"] == 60.0 and ph_f["score"] == 10.0
    assert any("just outside" in d for d in marginal["limiting"])


def test_fertilizer_deficiency_from_measurements():
    cond = dict(GOOD_WHEAT, nitrogen_kg_ha=30)   # below wheat's 100-140 band
    result = recommend_crops(cond)
    wheat = find(result, "wheat")
    fert = wheat["fertilizer"]
    assert fert["available"] is True
    assert any("Nitrogen" in d for d in wheat["limiting"])
    assert "does NOT prescribe quantities" in fert["advice"]
    n_row = next(r for r in fert["nutrients"] if r["nutrient"].startswith("Nitrogen"))
    assert n_row["status"] == "below_band" and n_row["band_kg_ha"] == [100, 140]


def test_fertilizer_without_measurements_asks_for_soil_test():
    cond = {k: v for k, v in GOOD_WHEAT.items() if "kg_ha" not in k}
    fert = fertilizer_guidance(cond, CROP_PROFILES["wheat"])
    assert fert["available"] is False
    assert "soil test" in fert["advice"]
    assert len(fert["missing_nutrients"]) == 3
    assert fert["nutrients"] == []              # no invented quantities
    partial = fertilizer_guidance(dict(cond, nitrogen_kg_ha=100), CROP_PROFILES["wheat"])
    assert partial["available"] is False
    assert "Phosphorus" in partial["advice"] and "Potassium" in partial["advice"]


def test_summary_shape():
    result = recommend_crops(GOOD_WHEAT)
    s = result["summary"]
    assert s["count"] == len(CROP_PROFILES)
    assert s["top_crop"] == result["recommendations"][0]["crop"]
    assert s["top_score"] == result["recommendations"][0]["score"]
    assert "not a yield prediction" in s["note"]
    top3 = recommend_crops(GOOD_WHEAT, top=3)
    assert len(top3["recommendations"]) == 3


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
