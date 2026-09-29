from .capabilities import list_capabilities
from .environment import get_weather_forecast, get_weather_history
from .operations import execute_operational_action, estimate_operational_impact, get_operational_options
from .river import compare_river_flows, get_river_flow_history, get_sensor_history, get_sensor_status, list_rivers
from .supply import get_asset_history, get_incidents, get_maintenance, list_network_assets, run_supply_forecast

RIVER_TOOLS = [list_rivers, get_river_flow_history, compare_river_flows, get_sensor_history, get_sensor_status, get_weather_history, get_weather_forecast]
SUPPLY_TOOLS = [list_rivers, list_network_assets, get_asset_history, get_incidents, get_maintenance, run_supply_forecast, get_weather_forecast]
OPERATIONS_TOOLS = [get_operational_options, estimate_operational_impact, execute_operational_action]
ALL_TOOLS = [list_capabilities, *RIVER_TOOLS, *SUPPLY_TOOLS, *OPERATIONS_TOOLS]

__all__ = ["ALL_TOOLS", "RIVER_TOOLS", "SUPPLY_TOOLS", "OPERATIONS_TOOLS", "compare_river_flows", "execute_operational_action", "get_asset_history", "get_incidents", "get_maintenance", "get_operational_options", "get_river_flow_history", "get_sensor_history", "get_sensor_status", "get_weather_forecast", "get_weather_history", "list_network_assets", "list_rivers", "run_supply_forecast"]
