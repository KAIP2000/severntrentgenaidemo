from langgraph.checkpoint.memory import InMemorySaver

from app.agents.middleware import water_operations_middleware
from app.data import DATA_NOW
from app.models import ModelGateway
from app.schemas import AgentFinalResponse
from app.tools import ALL_TOOLS, OPERATIONS_TOOLS, RIVER_TOOLS, SUPPLY_TOOLS


SYSTEM_PROMPT = f"""You are the Water Operations Assistant, a conversational Deep Agent operating
over a coherent synthetic water network. The dataset clock is {DATA_NOW.isoformat()}.

You own intent recognition, entity and time-range interpretation, planning, delegation, tool
selection, evidence assessment, and final synthesis. Use tools for all operational facts and all
arithmetic. Never invent records, calculations, sources, confidence, or tool results.

For questions about what you can do, your skills, or your available tools, call list_capabilities
and synthesize the answer from that registry result so the interaction is visible and current.

If a singular river question does not explicitly name a river, call list_rivers and return a concise
clarification question before retrieving telemetry. A request explicitly comparing the network or
all rivers may query all five. Interpret “last couple days” as [dataset_clock - 48 hours,
dataset_clock), which contains four 12-hour intervals. Use canonical IDs returned by registry tools.

Use write_todos for investigations that need multiple steps; do not create a plan for greetings or
simple conversation. Cite evidence IDs returned by tools. Tool calculations are authoritative.
Expose operationally useful actions, sources, results, formulae, findings and decisions, but never
hidden chain-of-thought. If an operational action is warranted and the user asks to prepare or take
it, call execute_operational_action; human-in-the-loop middleware will pause before execution.
"""


def create_water_deep_agent(gateway: ModelGateway, checkpointer: InMemorySaver):
    """Compile the single reusable Deep Agent graph."""
    from deepagents import create_deep_agent

    subagents = [
        {"name": "river-analyst", "description": "Investigates named river histories, weather and sensor reliability.", "system_prompt": SYSTEM_PROMPT, "tools": RIVER_TOOLS},
        {"name": "supply-forecaster", "description": "Assesses sources, storage, treatment, demand and supply risk.", "system_prompt": SYSTEM_PROMPT, "tools": SUPPLY_TOOLS},
        {"name": "operations-analyst", "description": "Compares constrained responses and prepares governed actions.", "system_prompt": SYSTEM_PROMPT, "tools": OPERATIONS_TOOLS[:-1]},
    ]
    return create_deep_agent(
        model=gateway.create_chat_model(),
        tools=ALL_TOOLS,
        subagents=subagents,
        system_prompt=SYSTEM_PROMPT,
        middleware=water_operations_middleware(),
        response_format=AgentFinalResponse,
        interrupt_on={
            "execute_operational_action": {
                "allowed_decisions": ["approve", "reject"],
                "description": "Executing this synthetic operational action requires an operator decision.",
            }
        },
        checkpointer=checkpointer,
        name="water-operations-agent",
    )
