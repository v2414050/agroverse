"""Smart Energy Optimization Engine — pure decision functions.

Finds unnecessary energy use on farm equipment using transparent,
config-driven rules (Algorithms PDF section 4 + this task's spec):

    Energy (kWh) = power (kW) × operating time (h)      [config.KWH_FORMULA]

    unnecessary_operation — an irrigation pump is running while the
        anti-saturation engine says its zone does not need water
    excessive_duration    — today's running hours exceed the configured cap
    outside_schedule      — running outside the configured window, or inside
        the peak-tariff window
    idle_draw             — switched off but still drawing standby power
        (the PDF's "vampire load": >= IDLE_WATTS for >= IDLE_MINUTES)
    unknown_power_rating  — data-quality note when the rating is missing:
        consumption cannot be estimated (never guessed)

Normal operation is explicitly reported as normal — it is never labelled
waste. Savings figures are ESTIMATES of avoidable energy, not guarantees.
Data in, plain dict out: no database or HTTP inside.
"""

from datetime import datetime

from ..config import (
    DURATION_TOLERANCE_H,
    IDLE_MINUTES,
    IDLE_WATTS,
    KWH_FORMULA,
    PEAK_WINDOW,
)

SEVERITY = {
    "unnecessary_operation": "critical",
    "excessive_duration": "warning",
    "outside_schedule": "warning",
    "peak_tariff": "warning",
    "idle_draw": "info",
    "unknown_power_rating": "info",
}

# Statuses that mean "irrigation is not needed right now". UNKNOWN is
# deliberately excluded: missing data must not be treated as waste.
NO_WATER_NEEDED = ("OPTIMAL", "HIGH", "SATURATED")


def estimate_kwh(power_kw: float | None, hours: float) -> float | None:
    """kWh = kW x h. Returns None when the rating is unknown — never guesses."""
    if power_kw is None or hours is None:
        return None
    if not isinstance(power_kw, (int, float)) or isinstance(power_kw, bool):
        return None
    if not isinstance(hours, (int, float)) or isinstance(hours, bool):
        return None
    if hours < 0 or power_kw < 0:
        raise ValueError("hours and power_kw must be non-negative.")
    return round(power_kw * hours, 2)


def _minutes(hhmm: str) -> int | None:
    try:
        h, m = str(hhmm).split(":")
        value = int(h) * 60 + int(m)
        return value if 0 <= value < 1440 else None
    except (ValueError, AttributeError, TypeError):
        return None


def _in_window(start: str, end: str, now_minutes: int) -> bool:
    """True when now_minutes lies inside [start, end), wrapping midnight."""
    s, e = _minutes(start), _minutes(end)
    if s is None or e is None:
        return True  # unusable schedule — do not accuse on bad config
    if s <= e:
        return s <= now_minutes < e
    return now_minutes >= s or now_minutes < e  # window wraps midnight


def analyze_equipment(eq: dict, *, zone_status: str | None = None,
                      now: datetime | None = None) -> dict:
    """Analyse one equipment record (plain dict, DB row shape).

    `zone_status` is the anti-saturation state for the zone this pump
    serves ('DRY' means water IS needed). `now` is injectable for tests.
    """
    now = now or datetime.now()
    now_minutes = now.hour * 60 + now.minute

    name = eq.get("name") or "Equipment"
    kind = eq.get("kind") or "equipment"
    power_kw = eq.get("power_kw")
    is_on = bool(eq.get("is_on"))
    hours_today = float(eq.get("hours_today") or 0.0)

    measured_kwh = eq.get("kwh_today")  # optional meter value
    if measured_kwh is not None:
        energy = {"kwh_today": round(float(measured_kwh), 2), "basis": "measured"}
    else:
        est = estimate_kwh(power_kw, hours_today)
        energy = {
            "kwh_today": est,
            "basis": "estimated" if est is not None else "unknown",
            "formula": KWH_FORMULA if est is not None else None,
        }

    findings: list[dict] = []

    def add(issue, action, explanation, savings_kwh=None):
        findings.append(
            {
                "issue": issue,
                "severity": SEVERITY.get(issue, "info"),
                "action": action,
                "explanation": explanation,
                "savings_kwh_estimate": savings_kwh,
                "savings_basis": "estimate" if savings_kwh is not None else None,
            }
        )

    if not is_on:
        watts = eq.get("standby_watts")
        minutes = float(eq.get("standby_minutes") or 0.0)
        if watts is not None and watts >= IDLE_WATTS and minutes >= IDLE_MINUTES:
            waste = round(watts * minutes / 60 / 1000, 3)
            add(
                "idle_draw",
                "Switch off at the plug or service the device.",
                f"{name} is switched off but still draws {watts:g} W standby for "
                f"{minutes:g} min (>= the {IDLE_WATTS:g} W / {IDLE_MINUTES:g} min "
                f"idle threshold). Small loads add up — this \"vampire\" draw wastes "
                f"about {waste:g} kWh per occurrence.",
                waste,
            )
        status_label = "Off (standby draw)" if findings else "Off"
    else:
        status_label = "Running"
        # 1) pump running while its zone does not need water
        if kind == "pump" and zone_status in NO_WATER_NEEDED:
            waste = estimate_kwh(power_kw, hours_today)
            add(
                "unnecessary_operation",
                "Switch the pump off (simulated) and wait for the DRY signal.",
                f"{name} is running, but the anti-saturation engine reports "
                f"{zone_status} moisture for {eq.get('zone') or 'its zone'} — "
                f"irrigation is not required, so this runtime may be wasted."
                + (f" About {waste:g} kWh so far today (estimate)." if waste is not None else
                   " The power rating is unknown, so the wasted energy cannot be estimated."),
                waste,
            )

        # 2) beyond the configured daily duration
        max_hours = eq.get("max_hours_per_day")
        if max_hours is not None and hours_today > max_hours + DURATION_TOLERANCE_H:
            over = round(hours_today - max_hours, 2)
            waste = estimate_kwh(power_kw, over)
            add(
                "excessive_duration",
                f"Cap the daily run at {max_hours:g} h (simulated).",
                f"{name} has run {hours_today:g} h today, over its configured cap "
                f"of {max_hours:g} h (+{DURATION_TOLERANCE_H:g} h tolerance). The "
                f"extra {over:g} h"
                + (f" wastes about {waste:g} kWh (estimate)." if waste is not None else
                   " cannot be priced — the power rating is unknown."),
                waste,
            )

        # 3) outside its schedule / inside the peak-tariff window
        start, end = eq.get("schedule_start"), eq.get("schedule_end")
        if start and end and not _in_window(start, end, now_minutes):
            add(
                "outside_schedule",
                f"Reschedule to the configured {start}-{end} window.",
                f"{name} is running outside its configured {start}-{end} schedule "
                f"(local time {now.strftime('%H:%M')}). Shifting the run into the "
                f"window keeps the same work at a lower cost. Potential savings "
                f"depend on future runtime, so none is quoted.",
            )
        peak_start, peak_end = PEAK_WINDOW
        if kind == "pump" and _in_window(peak_start, peak_end, now_minutes):
            add(
                "peak_tariff",
                "Move the run outside the peak-tariff window.",
                f"{name} is running inside the demo peak-tariff window "
                f"{peak_start}-{peak_end}. Pumping here costs more per kWh; the "
                f"evening window is cheaper.",
            )

        # 4) data-quality note when the rating is unknown
        if power_kw is None:
            add(
                "unknown_power_rating",
                "Add the nameplate rating to enable estimates.",
                f"{name} has no configured power rating, so its consumption "
                f"cannot be estimated — no waste figure is invented.",
            )

    if not findings:
        findings.append(
            {
                "issue": "normal",
                "severity": "ok",
                "action": "No change needed.",
                "explanation": (
                    f"{name} matches its configured schedule and the farm's "
                    f"irrigation demand — normal operation, not waste."
                ),
                "savings_kwh_estimate": None,
                "savings_basis": None,
            }
        )

    savings = round(
        sum(f["savings_kwh_estimate"] or 0.0 for f in findings), 3
    )

    return {
        "id": eq.get("id"),
        "equipment": name,
        "kind": kind,
        "zone": eq.get("zone"),
        "is_on": is_on,
        "status_label": status_label,
        "power_kw": power_kw,
        "power_basis": "rated" if power_kw is not None else "unknown",
        "hours_today": hours_today,
        "energy": energy,
        "findings": findings,
        "total_savings_kwh_estimate": savings if savings else 0.0,
    }


def analyze_fleet(equipment_rows: list[dict], *, zone_statuses: dict | None = None,
                  daily_usage: list[dict] | None = None,
                  now: datetime | None = None) -> dict:
    """Fleet-level analysis: per-item results plus a farm summary."""
    zone_statuses = zone_statuses or {}
    items = [
        analyze_equipment(eq, zone_status=zone_statuses.get(eq.get("zone")), now=now)
        for eq in equipment_rows
    ]

    problem_items = [i for i in items if i["findings"][0]["issue"] != "normal"]
    total_savings = round(
        sum(i["total_savings_kwh_estimate"] for i in items), 2
    )

    latest = (daily_usage or [None])[-1]
    summary: dict = {
        "equipment_count": len(items),
        "findings_count": sum(
            len([f for f in i["findings"] if f["issue"] != "normal"]) for i in items
        ),
        "running_count": sum(1 for i in items if i["is_on"]),
        "total_savings_kwh_estimate": total_savings,
        "savings_basis": "estimate — not a guaranteed result",
        "latest_day": dict(latest) if latest else None,
        "note": (
            "Off-peak share cannot be split honestly: the demo meter records "
            "daily totals only, so no hourly slot data exists."
        ),
    }

    summary["recommendation"] = (
        f"{len(problem_items)} of {len(items)} devices show avoidable use. "
        f"Potential saving today: ~{total_savings:g} kWh (estimate)."
        if problem_items
        else "All devices match their schedules and demand — no savings to capture."
    )

    return {"equipment": items, "summary": summary}
