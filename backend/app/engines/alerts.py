"""Alert derivation — pure mapping from engine outputs to structured alerts.

Takes the results the three decision engines already produce (saturation
advice per plot, energy fleet findings, crop-advisory summary) plus the
stored farm profile, and derives farmer-facing alerts:

    low_moisture          saturation status DRY (critical only when the
                          engine's own critical_dry rule fired)
    excessive_moisture    saturation status SATURATED
    unnecessary_irrigation  a zone was watered recently but currently does
                          not need water (engine status OPTIMAL/HIGH/SATURATED)
    unnecessary_equipment an energy-engine finding (any non-normal issue —
                          severity comes from the energy engine itself)
    missing_farm_info     the farm profile or advisory inputs are incomplete
    crop_limitation       the crop advisor flags limiting factors on the
                          best-matching crop

Honesty rules:
  * Every alert is traceable to an engine result — nothing is random, and
    "critical" is only ever inherited from an engine severity (critical_dry
    moisture, or the energy engine's unnecessary_operation).
  * `params` carries the numbers behind each alert so the UI can render a
    localized template without re-deriving anything.
  * Data in, plain list-of-dicts out: no database or HTTP inside.
"""

import json

# Issue codes the UI can localize. Anything else falls back to the stored
# English title/description.
KNOWN_ISSUES = (
    "low_moisture",
    "excessive_moisture",
    "unnecessary_irrigation",
    "unnecessary_equipment",
    "missing_farm_info",
    "crop_limitation",
)

ENERGY_ISSUES = (
    "unnecessary_operation",
    "excessive_duration",
    "outside_schedule",
    "peak_tariff",
    "idle_draw",
    "unknown_power_rating",
)


def _alert(issue, severity, category, title, description, action, related, **params):
    return {
        "issue": issue,
        "severity": severity,
        "category": category,
        "title": title,
        "description": description,
        "action": action,
        "related": related,
        "params": params,
    }


def _plot_alerts(context) -> list[dict]:
    """Low / excessive moisture from the anti-saturation engine."""
    alerts: list[dict] = []
    target = context.get("target_pct", 40)
    for plot in context.get("plots", []):
        name = plot.get("name") or "Plot"
        zone = plot.get("zone") or "—"
        related = f"{name} ({zone})"
        moisture = plot.get("moisture_pct")
        status = plot.get("status")

        if status == "DRY":
            critical = plot.get("rule") == "critical_dry"
            alerts.append(_alert(
                "low_moisture",
                "critical" if critical else "warning",
                "irrigation",
                f"{related}: low soil moisture",
                (
                    f"{name} in {zone} reads {moisture:g}% moisture, below the "
                    f"{target:g}% target"
                    + (" and under the critical level — the crop is at risk of stress."
                       if critical else ".")
                ),
                plot.get("action_label") or "Schedule irrigation",
                related,
                plot=name, zone=zone, moisture=moisture, target=target,
                critical=critical, action_code=plot.get("action"),
            ))
        elif status == "SATURATED":
            saturation = plot.get("saturation_pct")
            alerts.append(_alert(
                "excessive_moisture", "warning", "irrigation",
                f"{related}: soil is saturated",
                (
                    f"{name} in {zone} reads {moisture:g}% moisture — at or above "
                    f"the {saturation:g}% saturation threshold. Irrigation would be "
                    f"wasted and risks waterlogging."
                ),
                "Do not irrigate — let the soil drain and re-check the reading.",
                related,
                plot=name, zone=zone, moisture=moisture, saturation=saturation,
            ))
    return alerts


def _irrigation_alerts(context) -> list[dict]:
    """Potentially unnecessary irrigation: a recent cycle on a zone whose
    current engine status says water is NOT needed."""
    alerts: list[dict] = []
    status_by_zone = {p.get("zone"): p.get("status") for p in context.get("plots", [])}
    no_need = {"OPTIMAL", "HIGH", "SATURATED"}
    for event in context.get("recent_irrigation", []):
        zone = event.get("zone")
        status = status_by_zone.get(zone)
        if status not in no_need:
            continue
        hours = event.get("hours_ago")
        alerts.append(_alert(
            "unnecessary_irrigation", "warning", "irrigation",
            f"{zone}: recent cycle may be unnecessary",
            (
                f"{zone} was watered {hours:g} h ago, but the anti-saturation "
                f"engine now reports {status} moisture — the next cycle would "
                f"likely be wasted."
            ),
            f"Delay the next cycle in {zone} until the engine reports DRY.",
            f"{zone} ({event.get('plot') or 'plot'})",
            zone=zone, plot=event.get("plot"), status=status, hours_ago=hours,
        ))
    return alerts


def _equipment_alerts(context) -> list[dict]:
    """One alert per non-normal energy-engine finding."""
    alerts: list[dict] = []
    for item in context.get("equipment", []):
        name = item.get("equipment") or "Equipment"
        for finding in item.get("findings", []):
            issue = finding.get("issue")
            if issue == "normal" or issue not in ENERGY_ISSUES:
                continue
            alerts.append(_alert(
                "unnecessary_equipment",  # normalized code for localization
                finding.get("severity") or "info",
                "energy",
                f"{name}: {issue.replace('_', ' ')}",
                finding.get("explanation") or "",
                finding.get("action") or "Review this equipment's schedule.",
                name,
                equipment=name, finding=issue, detail=issue,
                savings_kwh=finding.get("savings_kwh_estimate"),
            ))
    return alerts


def _farm_alerts(context) -> list[dict]:
    """Missing farm information (profile gaps + advisory inputs not measured)."""
    alerts: list[dict] = []
    farm = context.get("farm")
    if not farm:
        alerts.append(_alert(
            "missing_farm_info", "warning", "crop",
            "No farm registered",
            "No farm profile is stored, so per-farm advice cannot be personalised.",
            "Open My Farm and save your farm details.",
            "Farm profile",
            items=["farm profile"], registered=False,
        ))
        return alerts

    items: list[str] = []
    if farm.get("soil_ph") is None:
        items.append("soil pH")
    if not farm.get("soil_type"):
        items.append("soil type")
    for missing in (context.get("crop") or {}).get("missing", []):
        # crop-advisor wording -> short item labels
        for key, label in (
            ("rainfall", "seasonal rainfall"),
            ("irrigation", "irrigation access"),
            ("N/P/K", "soil NPK test"),
            ("slope", "field slope"),
            ("Temperature", "temperature"),
            ("Season", "season"),
            ("Soil type", "soil type"),
        ):
            if key.lower() in missing.lower() and label not in items:
                items.append(label)
    if not items:
        return alerts

    name = farm.get("name") or "Farm"
    alerts.append(_alert(
        "missing_farm_info", "info", "crop",
        f"{name}: farm information incomplete",
        (
            "The advisory engines could not evaluate everything: "
            + ", ".join(items)
            + " not provided. Recommendations stay provisional until these are filled in."
        ),
        "Add the missing details on the My Farm / Crop Advisor pages.",
        name,
        items=items, registered=True, name=name,
    ))
    return alerts


def _crop_alerts(context) -> list[dict]:
    """Important crop suitability limitations from the advisory engine."""
    crop = context.get("crop") or {}
    top = crop.get("top")
    if not top or top.get("score") is None:
        return []
    limiting = top.get("limiting") or []
    verdict = top.get("verdict")
    if verdict == "recommended" and not limiting:
        return []
    if verdict in ("marginal", "not_recommended"):
        severity = "warning"
    else:
        severity = "info"
    name = top.get("crop") or "Crop"
    first_limit = limiting[0] if limiting else "no single dominant limitation"
    return [_alert(
        "crop_limitation", severity, "crop",
        f"Best crop match has limitations: {name}",
        (
            f"{name} is the best match for the current farm conditions at "
            f"{top['score']}/100 ({top.get('verdict_label', verdict)}). "
            f"Top limitation: {first_limit}"
        ),
        (top.get("next_steps") or ["Review the limiting factors on the Crop Advisor page."])[0],
        name,
        crop=name, score=top["score"], verdict=verdict,
        verdict_label=top.get("verdict_label", verdict),
        limitation_count=len(limiting),
        first_limit=limiting[0] if limiting else None,
    )]


def derive_alerts(context: dict) -> list[dict]:
    """Derive all farmer-facing alerts from one engine run (plain dict out)."""
    return (
        _plot_alerts(context)
        + _irrigation_alerts(context)
        + _equipment_alerts(context)
        + _farm_alerts(context)
        + _crop_alerts(context)
    )


def params_json(alert: dict) -> str:
    """Serialize the alert params for the alerts.params TEXT column."""
    return json.dumps(alert.get("params", {}), ensure_ascii=False)
