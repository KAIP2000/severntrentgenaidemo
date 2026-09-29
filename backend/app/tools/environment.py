from statistics import mean

from app.data import DATA_NOW, ENVIRONMENT
from app.tools.common import calculation, envelope, filter_rows


def _resolve_catchment_id(identifier: str) -> str:
    """Accept a canonical catchment ID or its associated river ID."""
    if identifier in ENVIRONMENT["weather"]:
        return identifier
    river = ENVIRONMENT["rivers"].get(identifier)
    if river and river["catchment_id"] in ENVIRONMENT["weather"]:
        return river["catchment_id"]
    raise ValueError(f"Unknown catchment_id or river_id. Use one of: {', '.join(ENVIRONMENT['weather'])}")


def get_weather_history(catchment_id: str, start: str, end: str) -> dict:
    """Retrieve weather history using a catchment or associated river ID."""
    resolved_catchment_id = _resolve_catchment_id(catchment_id)
    records = filter_rows(ENVIRONMENT["weather"][resolved_catchment_id], start, end)
    total_rain = round(sum(row["rainfall_mm"] for row in records), 1)
    calculations = [
        calculation("Total rainfall", "sum(rainfall_mm)", {"intervals": len(records)}, total_rain, "mm"),
        calculation("Mean temperature", "sum(temperature_c) / count", {"count": len(records)}, round(mean(row["temperature_c"] for row in records), 1) if records else None, "°C"),
    ]
    return envelope(tool="get_weather_history", source="Synthetic Catchment Weather", query={"catchment_id": resolved_catchment_id, "start": start, "end": end}, records=records, summary=f"Retrieved {len(records)} weather intervals with {total_rain} mm total rainfall.", calculations=calculations)


def get_weather_forecast(catchment_id: str, hours: int = 168) -> dict:
    """Return a deterministic forecast using a catchment or associated river ID; hours must be 12-168."""
    resolved_catchment_id = _resolve_catchment_id(catchment_id)
    if hours < 12 or hours > 168:
        raise ValueError("hours must be between 12 and 168")
    periods = hours // 12
    recent = ENVIRONMENT["weather"][resolved_catchment_id][-6:]
    records = []
    from datetime import timedelta
    for index in range(periods):
        seed = recent[index % len(recent)]
        records.append({"timestamp": (DATA_NOW + timedelta(hours=index * 12)).isoformat(), "rainfall_mm": round(seed["rainfall_mm"] * 0.65, 1), "temperature_c": seed["temperature_c"]})
    total = round(sum(row["rainfall_mm"] for row in records), 1)
    return envelope(tool="get_weather_forecast", source="Synthetic Meteorological Forecast", query={"catchment_id": resolved_catchment_id, "hours": hours, "start": DATA_NOW.isoformat(), "end": records[-1]["timestamp"] if records else DATA_NOW.isoformat()}, records=records, summary=f"Forecast contains {periods} intervals and {total} mm rainfall.", calculations=[calculation("Forecast rainfall", "sum(rainfall_mm)", {"intervals": periods}, total, "mm")])
