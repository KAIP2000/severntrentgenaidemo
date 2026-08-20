"""Deterministic, coherent synthetic water-network data.

The clock is rounded to a twelve-hour boundary at process start. Every historical
series contains 60 start timestamps covering [now - 30 days, now).
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any


def _floor_12h(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return value.replace(hour=12 if value.hour >= 12 else 0)


RIVER_SPECS = [
    {"id": "river-alder", "name": "River Alder", "catchment_id": "alder-catchment", "baseline": 180.0, "profile": "dry_decline"},
    {"id": "bracken-beck", "name": "Bracken Beck", "catchment_id": "bracken-catchment", "baseline": 165.0, "profile": "stable"},
    {"id": "mereford-river", "name": "Mereford River", "catchment_id": "mereford-catchment", "baseline": 142.0, "profile": "sensor_fault"},
    {"id": "highmoor-brook", "name": "Highmoor Brook", "catchment_id": "highmoor-catchment", "baseline": 112.0, "profile": "rain_surge"},
    {"id": "wren-channel", "name": "Wren Channel", "catchment_id": "wren-catchment", "baseline": 156.0, "profile": "maintenance_dip"},
]


def _round(value: float) -> float:
    return round(value, 1)


def _flow_value(spec: dict[str, Any], index: int, rng: random.Random) -> float:
    baseline = spec["baseline"]
    seasonal = math.sin(index / 5.1) * baseline * 0.018
    noise = rng.uniform(-2.0, 2.0)
    profile = spec["profile"]
    adjustment = 0.0
    if profile == "dry_decline" and index >= 42:
        adjustment = -(index - 41) * 3.0
    elif profile == "rain_surge" and index >= 52:
        adjustment = [4, 9, 18, 31, 43, 35, 24, 15][index - 52]
    elif profile == "maintenance_dip" and 50 <= index <= 56:
        adjustment = -22 + abs(53 - index) * 2.5
    return max(20.0, _round(baseline + seasonal + noise + adjustment))


def _rain_value(spec: dict[str, Any], index: int, rng: random.Random) -> float:
    base = max(0.0, rng.gauss(2.7, 2.1))
    if spec["profile"] == "dry_decline" and index >= 42:
        base *= 0.16
    if spec["profile"] == "rain_surge" and 49 <= index <= 55:
        base += [5, 9, 14, 21, 16, 10, 6][index - 49]
    return _round(base)


def generate_environment(clock: datetime) -> dict[str, Any]:
    """Build a repeatable dataset relative to an injected clock."""
    data_now = _floor_12h(clock)
    intervals = [data_now - timedelta(hours=12 * offset) for offset in range(60, 0, -1)]
    rivers: dict[str, Any] = {}
    sensors: dict[str, Any] = {}
    weather: dict[str, list[dict[str, Any]]] = {}
    for river_number, spec in enumerate(RIVER_SPECS, start=1):
        rng = random.Random(700 + river_number)
        flow_history = []
        weather_history = []
        for index, timestamp in enumerate(intervals):
            flow = _flow_value(spec, index, rng)
            rain = _rain_value(spec, index, rng)
            flow_history.append({"timestamp": timestamp.isoformat(), "flow_ml_day": flow, "quality": "validated"})
            weather_history.append({
                "timestamp": timestamp.isoformat(),
                "rainfall_mm": rain,
                "temperature_c": _round(15.5 + math.sin(index / 7) * 4 + rng.uniform(-1, 1)),
                "soil_moisture_pct": _round(49 + rain * 0.7 + math.sin(index / 8) * 5),
            })

        prefix = f"R{river_number}"
        sensor_ids = []
        for sensor_number, position in enumerate(("upstream", "upstream", "downstream"), start=1):
            sensor_id = f"{prefix}-{'U' if position == 'upstream' else 'D'}{sensor_number}"
            sensor_ids.append(sensor_id)
            readings = []
            for index, row in enumerate(flow_history):
                reading = row["flow_ml_day"] + (-1.6 + sensor_number * 1.1)
                health = "healthy"
                if spec["profile"] == "sensor_fault" and sensor_number == 2 and index >= 54:
                    reading *= 0.52
                    health = "degraded"
                readings.append({"timestamp": row["timestamp"], "flow_ml_day": _round(reading), "health": health})
            sensors[sensor_id] = {"id": sensor_id, "river_id": spec["id"], "position": position, "readings": readings}

        rivers[spec["id"]] = {
            **spec,
            "unit": "ML/day",
            "sensor_ids": sensor_ids,
            "flow_history": flow_history,
        }
        weather[spec["catchment_id"]] = weather_history

    sources = []
    for index, spec in enumerate(RIVER_SPECS):
        history = []
        river_history = rivers[spec["id"]]["flow_history"]
        for period, row in enumerate(river_history):
            history.append({
                "timestamp": row["timestamp"],
                "abstraction_ml_day": _round(min(row["flow_ml_day"] * 0.22, 42 + index * 3)),
                "available_capacity_ml_day": float(48 + index * 4),
            })
        sources.append({"id": f"source-{index + 1}", "name": f"{spec['name']} Intake", "river_id": spec["id"], "history": history})

    reservoirs = []
    for index, name in enumerate(("Alderbank Reservoir", "Mereford Storage", "Highmoor Reservoir")):
        rng = random.Random(900 + index)
        reservoirs.append({
            "id": f"reservoir-{index + 1}",
            "name": name,
            "capacity_ml": float(1600 + index * 450),
            "history": [
                {"timestamp": ts.isoformat(), "storage_pct": _round(78 - idx * (0.12 + index * 0.02) + rng.uniform(-0.5, 0.5))}
                for idx, ts in enumerate(intervals)
            ],
        })

    treatments = []
    for index, name in enumerate(("Northgate WTW", "Mereford WTW", "Vale WTW")):
        capacity = 94 + index * 18
        treatments.append({
            "id": f"treatment-{index + 1}",
            "name": name,
            "capacity_ml_day": float(capacity),
            "history": [
                {"timestamp": ts.isoformat(), "output_ml_day": _round(capacity * (0.78 + 0.04 * math.sin(idx / 6))), "status": "operational"}
                for idx, ts in enumerate(intervals)
            ],
        })

    demand_zones = []
    for index, name in enumerate(("North Urban", "Central Vale", "East Ridge", "South Rural")):
        base = 46 + index * 7
        demand_zones.append({
            "id": f"zone-{index + 1}",
            "name": name,
            "history": [
                {"timestamp": ts.isoformat(), "demand_ml_day": _round(base + 4 * math.sin(idx / 3.2) + (2 if ts.hour == 12 else -1))}
                for idx, ts in enumerate(intervals)
            ],
        })

    incidents = [
        {"id": "INC-1042", "asset_id": "R3-U2", "started_at": (data_now - timedelta(days=3)).isoformat(), "status": "open", "severity": "medium", "description": "Intermittent telemetry divergence under investigation."},
        {"id": "INC-1037", "asset_id": "treatment-2", "started_at": (data_now - timedelta(days=11)).isoformat(), "status": "resolved", "severity": "low", "description": "Short-duration filter backwash delay."},
        {"id": "INC-1029", "asset_id": "reservoir-1", "started_at": (data_now - timedelta(days=19)).isoformat(), "status": "resolved", "severity": "low", "description": "Level gauge recalibration."},
    ]
    maintenance = [
        {"id": "MW-208", "asset_id": "source-5", "start": (data_now - timedelta(days=5)).isoformat(), "end": (data_now - timedelta(days=1, hours=12)).isoformat(), "status": "completed", "description": "Planned abstraction pump maintenance."},
        {"id": "MW-211", "asset_id": "treatment-1", "start": (data_now + timedelta(days=2)).isoformat(), "end": (data_now + timedelta(days=3)).isoformat(), "status": "scheduled", "description": "Routine clarifier inspection."},
    ]
    operations = [
        {"id": "increase-source-2", "action": "Increase Bracken Beck abstraction", "impact_ml_day": 9.0, "cost": "medium", "risk": "Low", "available": True, "constraint": "Maximum 48 ML/day abstraction."},
        {"id": "reservoir-release", "action": "Release Alderbank strategic storage", "impact_ml_day": 7.0, "cost": "high", "risk": "Medium", "available": True, "constraint": "Retain storage above 55%."},
        {"id": "demand-comms", "action": "Initiate targeted demand communications", "impact_ml_day": 3.0, "cost": "low", "risk": "Low", "available": True, "constraint": "Expected effect begins after 24 hours."},
        {"id": "increase-source-5", "action": "Increase Wren Channel abstraction", "impact_ml_day": 12.0, "cost": "high", "risk": "High", "available": False, "constraint": "Unavailable during post-maintenance validation."},
    ]
    catchments = [
        {"id": spec["catchment_id"], "name": f"{spec['name']} Catchment", "river_id": spec["id"], "area_km2": 118 + index * 27, "land_use": ["mixed rural", "upland", "agricultural", "moorland", "mixed urban"][index]}
        for index, spec in enumerate(RIVER_SPECS)
    ]
    connections = [
        {"id": "link-1", "from_asset_id": "river-alder", "to_asset_id": "reservoir-1", "kind": "raw-water transfer"},
        {"id": "link-2", "from_asset_id": "bracken-beck", "to_asset_id": "treatment-1", "kind": "abstraction"},
        {"id": "link-3", "from_asset_id": "mereford-river", "to_asset_id": "reservoir-2", "kind": "raw-water transfer"},
        {"id": "link-4", "from_asset_id": "highmoor-brook", "to_asset_id": "reservoir-3", "kind": "raw-water transfer"},
        {"id": "link-5", "from_asset_id": "wren-channel", "to_asset_id": "treatment-3", "kind": "abstraction"},
        {"id": "link-6", "from_asset_id": "reservoir-1", "to_asset_id": "treatment-1", "kind": "supply"},
        {"id": "link-7", "from_asset_id": "reservoir-2", "to_asset_id": "treatment-2", "kind": "supply"},
        {"id": "link-8", "from_asset_id": "reservoir-3", "to_asset_id": "treatment-3", "kind": "supply"},
    ]
    return {
        "generated_at": data_now.isoformat(),
        "rivers": rivers,
        "sensors": sensors,
        "weather": weather,
        "sources": sources,
        "reservoirs": reservoirs,
        "treatments": treatments,
        "demand_zones": demand_zones,
        "incidents": incidents,
        "maintenance": maintenance,
        "operations": operations,
        "catchments": catchments,
        "connections": connections,
    }


DATA_NOW = _floor_12h(datetime.now(timezone.utc))
INTERVALS = [DATA_NOW - timedelta(hours=12 * offset) for offset in range(60, 0, -1)]
ENVIRONMENT = generate_environment(DATA_NOW)
