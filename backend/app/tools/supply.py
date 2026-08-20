from statistics import mean

from app.data import ENVIRONMENT
from app.tools.common import calculation, envelope, filter_rows, parse_time


DATASETS = {
    "sources": ("Synthetic Abstraction Operations", "history"),
    "reservoirs": ("Synthetic Reservoir Operations", "history"),
    "treatments": ("Synthetic Treatment Operations", "history"),
    "demand_zones": ("Synthetic Demand Planning", "history"),
}


def get_asset_history(dataset: str, asset_ids: list[str], start: str, end: str) -> dict:
    """Retrieve source, reservoir, treatment or demand-zone history for explicit asset IDs."""
    if dataset not in DATASETS:
        raise ValueError(f"dataset must be one of: {', '.join(DATASETS)}")
    assets = {asset["id"]: asset for asset in ENVIRONMENT[dataset]}
    if not asset_ids:
        raise ValueError("asset_ids must not be empty")
    records = []
    for asset_id in asset_ids:
        if asset_id not in assets:
            raise ValueError(f"Unknown {dataset} asset {asset_id}. Available: {', '.join(assets)}")
        for row in filter_rows(assets[asset_id]["history"], start, end):
            records.append({"asset_id": asset_id, "asset_name": assets[asset_id]["name"], **row})
    numeric_fields = sorted({key for row in records for key, value in row.items() if isinstance(value, (int, float))})
    calculations = [calculation(f"Mean {field}", f"sum({field}) / count", {"count": len(records)}, round(mean(row[field] for row in records if field in row), 1), None) for field in numeric_fields]
    source = DATASETS[dataset][0]
    return envelope(tool="get_asset_history", source=source, query={"dataset": dataset, "asset_ids": asset_ids, "start": start, "end": end}, records=records, summary=f"Retrieved {len(records)} {dataset} records.", calculations=calculations)


def list_network_assets(asset_type: str) -> dict:
    """List sources, reservoirs, treatments, demand_zones, incidents or maintenance records."""
    if asset_type not in ("sources", "reservoirs", "treatments", "demand_zones", "incidents", "maintenance", "catchments", "connections"):
        raise ValueError("Unsupported asset_type")
    records = []
    for item in ENVIRONMENT[asset_type]:
        records.append({key: value for key, value in item.items() if key != "history"})
    return envelope(tool="list_network_assets", source="Synthetic Network Registry", query={"asset_type": asset_type}, records=records, summary=f"Found {len(records)} {asset_type} records.")


def get_incidents(start: str, end: str, status: str | None = None) -> dict:
    """Query incidents whose start timestamp falls in a start-inclusive/end-exclusive range."""
    start_dt, end_dt = parse_time(start), parse_time(end)
    if start_dt >= end_dt:
        raise ValueError("start must be earlier than end")
    records = [item for item in ENVIRONMENT["incidents"] if start_dt <= parse_time(item["started_at"]) < end_dt and (status is None or item["status"] == status)]
    open_count = sum(item["status"] == "open" for item in records)
    return envelope(tool="get_incidents", source="Synthetic Incident Register", query={"start": start, "end": end, "status": status}, records=records, summary=f"Found {len(records)} incidents; {open_count} are open.", calculations=[calculation("Open incident count", "count(status = open)", {"records": len(records)}, open_count, "incidents")])


def get_maintenance(start: str, end: str, asset_ids: list[str] | None = None) -> dict:
    """Query maintenance windows overlapping a start-inclusive/end-exclusive range."""
    start_dt, end_dt = parse_time(start), parse_time(end)
    if start_dt >= end_dt:
        raise ValueError("start must be earlier than end")
    records = [item for item in ENVIRONMENT["maintenance"] if parse_time(item["start"]) < end_dt and parse_time(item["end"]) > start_dt and (not asset_ids or item["asset_id"] in asset_ids)]
    return envelope(tool="get_maintenance", source="Synthetic Maintenance Scheduler", query={"start": start, "end": end, "asset_ids": asset_ids or []}, records=records, summary=f"Found {len(records)} overlapping maintenance windows.", calculations=[])


def run_supply_forecast(river_ids: list[str], horizon_days: int = 6) -> dict:
    """Run a deterministic supply-demand forecast using explicit rivers for a 1-7 day horizon."""
    if horizon_days < 1 or horizon_days > 7:
        raise ValueError("horizon_days must be 1-7")
    unknown = [river_id for river_id in river_ids if river_id not in ENVIRONMENT["rivers"]]
    if unknown or not river_ids:
        raise ValueError(f"Provide valid river_ids. Unknown: {unknown}")
    from datetime import timedelta
    from app.data import DATA_NOW
    current_source = sum(source["history"][-1]["abstraction_ml_day"] for source in ENVIRONMENT["sources"] if source["river_id"] in river_ids)
    current_treatment = sum(asset["history"][-1]["output_ml_day"] for asset in ENVIRONMENT["treatments"])
    current_demand = sum(asset["history"][-1]["demand_ml_day"] for asset in ENVIRONMENT["demand_zones"])
    records, calculations = [], []
    for day in range(1, horizon_days + 1):
        available = round(current_treatment + current_source * 0.08 - day * 1.15, 1)
        demand = round(current_demand + day * 1.8, 1)
        balance = round(available - demand, 1)
        records.append({"date": (DATA_NOW + timedelta(days=day)).date().isoformat(), "available_ml_day": available, "demand_ml_day": demand, "balance_ml_day": balance})
        calculations.append(calculation(f"Day {day} balance", "available_supply - forecast_demand", {"available_supply": available, "forecast_demand": demand}, balance, "ML/day"))
    return envelope(tool="run_supply_forecast", source="Synthetic Supply Forecast Model v2", query={"river_ids": river_ids, "horizon_days": horizon_days, "start": DATA_NOW.isoformat(), "end": (DATA_NOW + timedelta(days=horizon_days)).isoformat()}, records=records, summary=f"Forecast minimum balance is {min(row['balance_ml_day'] for row in records)} ML/day.", calculations=calculations)
