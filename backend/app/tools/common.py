from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.data import DATA_NOW


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def filter_rows(rows: list[dict[str, Any]], start: str, end: str) -> list[dict[str, Any]]:
    start_dt, end_dt = parse_time(start), parse_time(end)
    if start_dt >= end_dt:
        raise ValueError("start must be earlier than end")
    return [row for row in rows if start_dt <= parse_time(row["timestamp"]) < end_dt]


def calculation(label: str, formula: str, inputs: dict[str, Any], result: Any, unit: str | None = None) -> dict[str, Any]:
    return {"label": label, "formula": formula, "inputs": inputs, "result": result, "unit": unit}


def envelope(
    *,
    tool: str,
    source: str,
    query: dict[str, Any],
    records: list[dict[str, Any]],
    summary: str,
    calculations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    identity = json.dumps({"tool": tool, "source": source, "query": query}, sort_keys=True, default=str).encode()
    return {
        "evidence_id": f"EV-{hashlib.sha256(identity).hexdigest()[:10].upper()}",
        "tool": tool,
        "source": source,
        "query": query,
        "period": {"start": query.get("start"), "end": query.get("end"), "semantics": "start-inclusive/end-exclusive"},
        "records": records,
        "summary": summary,
        "calculations": calculations or [],
        "provenance": {"synthetic": True, "generated_at": DATA_NOW.isoformat(), "access": "read-only tool"},
    }
