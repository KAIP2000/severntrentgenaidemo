from app.tools.common import envelope


CAPABILITY_REGISTRY = [
    {
        "name": "River investigation",
        "description": "Investigate flow anomalies, historical baselines, rainfall and sensor reliability.",
        "tools": [
            "list_rivers",
            "get_river_flow_history",
            "compare_river_flows",
            "get_sensor_history",
            "get_sensor_status",
            "get_weather_history",
        ],
    },
    {
        "name": "Supply forecasting",
        "description": "Assess demand, available supply, capacity and six-day deficit risk.",
        "tools": [
            "get_weather_forecast",
            "list_network_assets",
            "get_asset_history",
            "get_incidents",
            "get_maintenance",
            "run_supply_forecast",
        ],
    },
    {
        "name": "Operational response",
        "description": "Compare available interventions, constraints, cost, risk and expected impact.",
        "tools": [
            "get_operational_options",
            "estimate_operational_impact",
            "execute_operational_action",
        ],
    },
    {
        "name": "Governed action",
        "description": "Pause consequential actions for an explicit operator decision and record the outcome.",
        "tools": ["human_in_the_loop"],
    },
]


def list_capabilities() -> dict:
    """List the assistant's water-operations skills and the tools available to each skill."""
    tool_count = len({tool for capability in CAPABILITY_REGISTRY for tool in capability["tools"]})
    return envelope(
        tool="list_capabilities",
        source="Water Operations Capability Registry",
        query={},
        records=CAPABILITY_REGISTRY,
        summary=f"The assistant exposes {len(CAPABILITY_REGISTRY)} skills across {tool_count} governed tools.",
    )
