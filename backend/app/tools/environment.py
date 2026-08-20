from statistics import mean

from app.data import DATA_NOW, ENVIRONMENT
from app.tools.common import calculation, envelope, filter_rows


def get_weather_history(catchment_id: str, start: str, end: str) -> dict:
    """Retrieve 12-hour rainfall, temperature and soil moisture history for a catchment."""
    if catchment_id not in ENVIRONMENT["weather"]:
        raise ValueError(f"Unknown catchment_id. Use one of: {', '.join(ENVIRONMENT['weather'])}")
    records = filter_rows(ENVIRONMENT["weather"][catchment_id], start, end)
    total_rain = round(sum(row["rainfall_mm"] for row in records), 1)
    calculations = [
        calculation("Total rainfall", "sum(rainfall_mm)", {"intervals": len(records)}, total_rain, "mm"),
        calculation("Mean temperature", "sum(temperature_c) / count", {"count": len(records)}, round(mean(row["temperature_c"] for row in records), 1) if records else None, "°C"),
    ]
    return envelope(tool="get_weather_history", source="Synthetic Catchment Weather", query={"catchment_id": catchment_id, "start": start, "end": end}, records=records, summary=f"Retrieved {len(records)} weather intervals with {total_rain} mm total rainfall.", calculations=calculations)


def get_weather_forecast(catchment_id: str, hours: int = 168) -> dict:
    """Return a deterministic seven-day 12-hour catchment forecast; hours must be 12-168."""
    if catchment_id not in ENVIRONMENT["weather"]:
        raise ValueError(f"Unknown catchment_id. Use one of: {', '.join(ENVIRONMENT['weather'])}")
    if hours < 12 or hours > 168:
        raise ValueError("hours must be between 12 and 168")
    periods = hours // 12
    recent = ENVIRONMENT["weather"][catchment_id][-6:]
    records = []
    from datetime import timedelta
    for index in range(periods):
        seed = recent[index % len(recent)]
        records.append({"timestamp": (DATA_NOW + timedelta(hours=index * 12)).isoformat(), "rainfall_mm": round(seed["rainfall_mm"] * 0.65, 1), "temperature_c": seed["temperature_c"]})
    total = round(sum(row["rainfall_mm"] for row in records), 1)
    return envelope(tool="get_weather_forecast", source="Synthetic Meteorological Forecast", query={"catchment_id": catchment_id, "hours": hours, "start": DATA_NOW.isoformat(), "end": records[-1]["timestamp"] if records else DATA_NOW.isoformat()}, records=records, summary=f"Forecast contains {periods} intervals and {total} mm rainfall.", calculations=[calculation("Forecast rainfall", "sum(rainfall_mm)", {"intervals": periods}, total, "mm")])

