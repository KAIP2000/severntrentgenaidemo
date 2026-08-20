from statistics import mean

from app.data import ENVIRONMENT
from app.tools.common import calculation, envelope, filter_rows


def list_rivers() -> dict:
    """List canonical river IDs and names. Use this before asking the user to clarify an unnamed river."""
    records = [
        {"river_id": river["id"], "name": river["name"], "catchment_id": river["catchment_id"]}
        for river in ENVIRONMENT["rivers"].values()
    ]
    return envelope(tool="list_rivers", source="Synthetic River Registry", query={}, records=records, summary=f"{len(records)} rivers are available.")


def get_river_flow_history(river_id: str, start: str, end: str, aggregation: str = "12h") -> dict:
    """Retrieve timestamped river flow for an explicit river and ISO-8601 time range. Base aggregation is 12h."""
    if aggregation != "12h":
        raise ValueError("Only 12h aggregation is available")
    if river_id not in ENVIRONMENT["rivers"]:
        raise ValueError(f"Unknown river_id. Use one of: {', '.join(ENVIRONMENT['rivers'])}")
    river = ENVIRONMENT["rivers"][river_id]
    records = filter_rows(river["flow_history"], start, end)
    calculations = []
    if records:
        first, last = records[0]["flow_ml_day"], records[-1]["flow_ml_day"]
        change = round(last - first, 1)
        change_pct = round((change / first) * 100, 1) if first else None
        calculations = [
            calculation("Mean flow", "sum(flow) / count", {"count": len(records)}, round(mean(row["flow_ml_day"] for row in records), 1), "ML/day"),
            calculation("Period change", "last_flow - first_flow", {"first_flow": first, "last_flow": last}, change, "ML/day"),
            calculation("Period change percent", "(last_flow - first_flow) / first_flow × 100", {"first_flow": first, "last_flow": last}, change_pct, "%"),
        ]
    return envelope(tool="get_river_flow_history", source="Synthetic River Telemetry", query={"river_id": river_id, "start": start, "end": end, "aggregation": aggregation}, records=records, summary=f"Retrieved {len(records)} 12-hour flow intervals for {river['name']}.", calculations=calculations)


def compare_river_flows(river_ids: list[str], start: str, end: str) -> dict:
    """Compare flow trends for an explicit list of river IDs over an ISO-8601 range."""
    if not river_ids:
        raise ValueError("river_ids must contain at least one canonical river ID")
    records, calculations = [], []
    for river_id in river_ids:
        result = get_river_flow_history(river_id, start, end)
        rows = result["records"]
        if rows:
            first, last = rows[0]["flow_ml_day"], rows[-1]["flow_ml_day"]
            change_pct = round(((last - first) / first) * 100, 1)
            records.append({"river_id": river_id, "name": ENVIRONMENT["rivers"][river_id]["name"], "first_flow_ml_day": first, "last_flow_ml_day": last, "change_pct": change_pct, "intervals": len(rows)})
            calculations.append(calculation(f"{river_id} change", "(last - first) / first × 100", {"first": first, "last": last}, change_pct, "%"))
    return envelope(tool="compare_river_flows", source="Synthetic River Telemetry", query={"river_ids": river_ids, "start": start, "end": end}, records=records, summary=f"Compared {len(records)} rivers.", calculations=calculations)


def get_sensor_history(river_id: str, start: str, end: str) -> dict:
    """Retrieve upstream/downstream sensor readings and health for an explicit river and time range."""
    river = ENVIRONMENT["rivers"].get(river_id)
    if not river:
        raise ValueError(f"Unknown river_id. Use one of: {', '.join(ENVIRONMENT['rivers'])}")
    records = []
    for sensor_id in river["sensor_ids"]:
        sensor = ENVIRONMENT["sensors"][sensor_id]
        for row in filter_rows(sensor["readings"], start, end):
            records.append({"sensor_id": sensor_id, "position": sensor["position"], **row})
    degraded = sum(row["health"] != "healthy" for row in records)
    calc = calculation("Degraded reading rate", "degraded_readings / total_readings × 100", {"degraded_readings": degraded, "total_readings": len(records)}, round(degraded / len(records) * 100, 1) if records else 0, "%")
    return envelope(tool="get_sensor_history", source="Synthetic Sensor Network", query={"river_id": river_id, "start": start, "end": end}, records=records, summary=f"Retrieved {len(records)} sensor readings; {degraded} are degraded.", calculations=[calc])


def get_sensor_status(river_ids: list[str], start: str, end: str) -> dict:
    """Return the latest sensor health and reading in a range for explicit river IDs."""
    if not river_ids:
        raise ValueError("river_ids must contain at least one canonical river ID")
    unknown = [river_id for river_id in river_ids if river_id not in ENVIRONMENT["rivers"]]
    if unknown:
        raise ValueError(f"Unknown river IDs: {', '.join(unknown)}")
    records = []
    for river_id in river_ids:
        for sensor_id in ENVIRONMENT["rivers"][river_id]["sensor_ids"]:
            sensor = ENVIRONMENT["sensors"][sensor_id]
            rows = filter_rows(sensor["readings"], start, end)
            if rows:
                records.append({"sensor_id": sensor_id, "river_id": river_id, "position": sensor["position"], **rows[-1]})
    degraded = sum(row["health"] != "healthy" for row in records)
    calc = calculation("Degraded sensor rate", "degraded_sensors / sensors_returned × 100", {"degraded_sensors": degraded, "sensors_returned": len(records)}, round(degraded / len(records) * 100, 1) if records else 0, "%")
    return envelope(tool="get_sensor_status", source="Synthetic Sensor Network", query={"river_ids": river_ids, "start": start, "end": end}, records=records, summary=f"{degraded} of {len(records)} sensors are degraded at their latest reading in the period.", calculations=[calc])
