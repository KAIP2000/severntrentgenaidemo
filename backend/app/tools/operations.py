from app.data import DATA_NOW, ENVIRONMENT
from app.tools.common import calculation, envelope


def get_operational_options() -> dict:
    """Return current operational interventions, availability, constraints, costs and risks."""
    return envelope(tool="get_operational_options", source="Synthetic Operational Playbook", query={}, records=ENVIRONMENT["operations"], summary=f"{sum(item['available'] for item in ENVIRONMENT['operations'])} of {len(ENVIRONMENT['operations'])} options are available.")


def estimate_operational_impact(option_id: str, projected_deficit_ml_day: float) -> dict:
    """Calculate the residual deficit for an explicit operational option."""
    option = next((item for item in ENVIRONMENT["operations"] if item["id"] == option_id), None)
    if not option:
        raise ValueError(f"Unknown option_id. Use one of: {', '.join(item['id'] for item in ENVIRONMENT['operations'])}")
    residual = round(max(0.0, projected_deficit_ml_day - option["impact_ml_day"]), 1)
    calc = calculation("Residual deficit", "max(0, projected_deficit - option_impact)", {"projected_deficit": projected_deficit_ml_day, "option_impact": option["impact_ml_day"]}, residual, "ML/day")
    return envelope(tool="estimate_operational_impact", source="Synthetic Operations Impact Model", query={"option_id": option_id, "projected_deficit_ml_day": projected_deficit_ml_day}, records=[{**option, "residual_deficit_ml_day": residual}], summary=f"{option['action']} leaves {residual} ML/day residual deficit.", calculations=[calc])


def execute_operational_action(recommendation_id: str, action: str, approved_by: str) -> dict:
    """Execute an approved mock action. This tool is always protected by human-in-the-loop middleware."""
    record = {
        "action_id": f"OPS-{DATA_NOW:%Y%m%d}-{recommendation_id[-4:]}",
        "recommendation_id": recommendation_id,
        "action": action,
        "approved_by": approved_by,
        "status": "completed",
        "message": f"{action} submitted.",
    }
    return envelope(
        tool="execute_operational_action",
        source="Synthetic Operations Control Log",
        query={"recommendation_id": recommendation_id, "action": action, "approved_by": approved_by},
        records=[record],
        summary=f"Approved mock action {record['action_id']} was submitted.",
    )
