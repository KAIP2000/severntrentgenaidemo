import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

os.environ["AGENT_EXECUTION_MODE"] = "simulation"

from app.agents.orchestrator import WaterOperationsHarness
from app.config import Settings
from app.data import DATA_NOW, ENVIRONMENT, generate_environment
from app.main import app
from app.schemas import AgentFinalResponse
from app.agents.deep_agent import SYSTEM_PROMPT
from app.tools.capabilities import list_capabilities
from app.tools.river import compare_river_flows, get_river_flow_history, list_rivers


def final_response(status="complete", title="Answer", answer="Done.", evidence_ids=None):
    return AgentFinalResponse(
        status=status,
        title=title,
        answer_markdown=answer,
        evidence_ids=evidence_ids or [],
    )


class ScriptedAgent:
    def __init__(self, script, final):
        self.script = script
        self.final = final
        self.inputs = []

    async def astream(self, input_value, **_kwargs):
        self.inputs.append(input_value)
        for event in self.script:
            yield event

    async def aget_state(self, _config):
        return SimpleNamespace(values={"structured_response": self.final}, tasks=())


class FailingAgent:
    async def astream(self, _input_value, **_kwargs):
        raise RuntimeError("scripted Gemini outage")
        yield

    async def aget_state(self, _config):
        return SimpleNamespace(values={}, tasks=())


class ApprovalAgent:
    def __init__(self):
        self.resumed = False
        self.final = final_response(answer="Approved action completed.")

    async def astream(self, input_value, **_kwargs):
        self.resumed = not isinstance(input_value, dict)
        if False:
            yield None

    async def aget_state(self, _config):
        if self.resumed:
            return SimpleNamespace(values={"structured_response": self.final}, tasks=())
        interrupt = SimpleNamespace(value={"tool": "execute_operational_action", "description": "Approval required"})
        return SimpleNamespace(values={}, tasks=(SimpleNamespace(interrupts=(interrupt,)),))


async def wait_terminal(harness, investigation_id, terminal=None):
    expected = terminal or harness.TERMINAL
    for _ in range(200):
        record = harness.get(investigation_id)
        if record.status in expected:
            return record
        await asyncio.sleep(0.005)
    raise AssertionError("investigation did not reach a terminal state")


def test_five_rivers_have_exact_ordered_seeded_histories_and_scenario_signatures():
    fixed_clock = datetime(2026, 8, 19, 17, 42, tzinfo=timezone.utc)
    first = generate_environment(fixed_clock)
    second = generate_environment(fixed_clock)
    assert first == second
    assert len(first["rivers"]) == 5
    assert len(first["sensors"]) == 15
    assert len(first["catchments"]) == 5
    assert len(first["connections"]) >= 5
    assert len(first["reservoirs"]) == 3
    assert len(first["treatments"]) == 3
    assert len(first["demand_zones"]) == 4
    for river in first["rivers"].values():
        rows = river["flow_history"]
        assert len(rows) == 60
        assert [row["timestamp"] for row in rows] == sorted(row["timestamp"] for row in rows)
        assert len(river["sensor_ids"]) == 3

    alder = first["rivers"]["river-alder"]["flow_history"]
    stable = first["rivers"]["bracken-beck"]["flow_history"]
    highmoor = first["rivers"]["highmoor-brook"]["flow_history"]
    wren = first["rivers"]["wren-channel"]["flow_history"]
    assert alder[-1]["flow_ml_day"] < alder[-12]["flow_ml_day"]
    assert max(row["flow_ml_day"] for row in highmoor[-8:]) > highmoor[-9]["flow_ml_day"] + 25
    assert max(row["flow_ml_day"] for row in stable) - min(row["flow_ml_day"] for row in stable) < 12
    assert min(row["flow_ml_day"] for row in wren[-10:]) < wren[-11]["flow_ml_day"] - 12
    assert first["sensors"]["R3-U2"]["readings"][-1]["health"] == "degraded"


def test_named_last_couple_days_returns_four_intervals_with_provenance_and_calculations():
    start = (DATA_NOW - timedelta(hours=48)).isoformat()
    result = get_river_flow_history("river-alder", start, DATA_NOW.isoformat())
    assert len(result["records"]) == 4
    assert result["query"]["aggregation"] == "12h"
    assert result["period"] == {"start": start, "end": DATA_NOW.isoformat(), "semantics": "start-inclusive/end-exclusive"}
    assert result["provenance"]["synthetic"] is True
    assert {item["label"] for item in result["calculations"]} == {"Mean flow", "Period change", "Period change percent"}


def test_network_comparison_requires_explicit_ids_and_covers_all_five():
    ids = list(ENVIRONMENT["rivers"])
    result = compare_river_flows(ids, (DATA_NOW - timedelta(days=7)).isoformat(), DATA_NOW.isoformat())
    assert {row["river_id"] for row in result["records"]} == set(ids)
    assert len(result["calculations"]) == 5


def test_capability_questions_are_model_directed_to_an_observable_registry_tool():
    result = list_capabilities()
    assert "call list_capabilities" in SYSTEM_PROMPT
    assert result["source"] == "Water Operations Capability Registry"
    assert len(result["records"]) == 4
    assert result["provenance"]["synthetic"] is True


def test_ambiguous_river_script_clarifies_without_telemetry():
    registry = list_rivers()
    started = AIMessage(content="", tool_calls=[{"name": "list_rivers", "args": {}, "id": "call-registry", "type": "tool_call"}])
    completed = ToolMessage(content=json.dumps(registry), tool_call_id="call-registry", name="list_rivers")
    script = [
        {"type": "updates", "ns": (), "data": {"model": {"messages": [started]}}},
        {"type": "updates", "ns": (), "data": {"tools": {"messages": [completed]}}},
    ]
    agent = ScriptedAgent(script, final_response("clarification_required", "Which river?", "Which of the five rivers do you mean?", [registry["evidence_id"]]))

    async def scenario():
        harness = WaterOperationsHarness(Settings(agent_execution_mode="simulation"), agent=agent)
        created = await harness.create("How has the river changed?", "session-a")
        record = await wait_terminal(harness, created.investigation_id)
        assert record.status == "clarification_required"
        assert [activity.tool.name for activity in record.activities.values()] == ["list_rivers"]
        assert all(activity.tool.name != "get_river_flow_history" for activity in record.activities.values())

    asyncio.run(scenario())


def test_session_order_thread_isolation_history_and_sse_cursor():
    agent = ScriptedAgent([], final_response(answer="Evidence-backed response."))

    async def scenario():
        harness = WaterOperationsHarness(Settings(agent_execution_mode="simulation"), agent=agent)
        first = await harness.create("First question", "shared-session")
        await wait_terminal(harness, first.investigation_id)
        second = await harness.create("Follow-up question", "shared-session")
        await wait_terminal(harness, second.investigation_id)
        assert [item.investigation_id for item in harness.session("shared-session")] == [first.investigation_id, second.investigation_id]
        assert first.thread_id != second.thread_id
        second_messages = agent.inputs[1]["messages"]
        assert [message["content"] for message in second_messages] == ["First question", "Evidence-backed response.", "Follow-up question"]

        record = harness.get(second.investigation_id)
        replay = []
        async for payload in harness.event_stream(second.investigation_id, after=1):
            if payload.startswith("id:"):
                replay.append(payload)
        assert replay
        assert all(int(payload.splitlines()[0].split(": ")[1]) > 1 for payload in replay)

    asyncio.run(scenario())


def test_failure_emits_run_failed_without_fallback_evidence():
    async def scenario():
        harness = WaterOperationsHarness(Settings(agent_execution_mode="simulation"), agent=FailingAgent())
        created = await harness.create("What happened?", "failure-session")
        record = await wait_terminal(harness, created.investigation_id)
        assert record.status == "failed"
        assert "scripted Gemini outage" in record.error
        assert record.evidence == {}
        assert record.final is None
        assert record.events[-1].type == "run_failed"

    asyncio.run(scenario())


def test_real_model_stream_events_become_timed_activities_without_content():
    streamed = AIMessage(content="private intermediate text", id="model-call-1")
    completed = AIMessage(content="", id="model-call-1")
    script = [
        {"type": "messages", "ns": (), "data": (streamed, {"langgraph_node": "model", "langgraph_step": 1})},
        {"type": "updates", "ns": (), "data": {"model": {"messages": [completed]}}},
    ]

    async def scenario():
        harness = WaterOperationsHarness(Settings(agent_execution_mode="simulation"), agent=ScriptedAgent(script, final_response()))
        created = await harness.create("Hello", "model-events")
        record = await wait_terminal(harness, created.investigation_id)
        model_activity = next(item for item in record.activities.values() if item.kind == "model")
        assert model_activity.status == "complete"
        assert model_activity.duration_ms is not None
        assert "private intermediate text" not in model_activity.model_dump_json()

    asyncio.run(scenario())


def test_approval_resumes_exact_thread_and_leaves_sibling_unchanged():
    async def scenario():
        approval_agent = ApprovalAgent()
        harness = WaterOperationsHarness(Settings(agent_execution_mode="simulation"), agent=approval_agent)
        pending = await harness.create("Take an action", "approval-session")
        pending_record = await wait_terminal(harness, pending.investigation_id, {"awaiting_approval"})
        sibling_agent = ScriptedAgent([], final_response(answer="Sibling complete."))
        harness.agent = sibling_agent
        sibling = await harness.create("Check something else", "approval-session")
        sibling_record = await wait_terminal(harness, sibling.investigation_id)
        sibling_thread = sibling_record.thread_id
        sibling_event_count = len(sibling_record.events)

        harness.agent = approval_agent
        original_thread = pending_record.thread_id
        await harness.decide(pending.investigation_id, "approve")
        resumed = await wait_terminal(harness, pending.investigation_id, {"complete"})
        assert resumed.thread_id == original_thread
        assert harness.get(sibling.investigation_id).thread_id == sibling_thread
        assert len(harness.get(sibling.investigation_id).events) == sibling_event_count

    asyncio.run(scenario())


def test_api_contract_returns_202_and_session_timeline(monkeypatch):
    import app.main as main

    scripted = ScriptedAgent([], final_response(answer="Hello from Gemini."))
    replacement = WaterOperationsHarness(Settings(agent_execution_mode="simulation"), agent=scripted)
    monkeypatch.setattr(main, "harness", replacement)
    with TestClient(app) as client:
        first = client.post("/api/investigations", json={"question": "Hello", "session_id": "api-session"})
        second = client.post("/api/investigations", json={"question": "Follow up", "session_id": "api-session"})
        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["thread_id"] != second.json()["thread_id"]
        for _ in range(100):
            timeline = client.get("/api/sessions/api-session").json()["investigations"]
            if all(item["status"] == "complete" for item in timeline):
                break
        assert [item["question"] for item in timeline] == ["Hello", "Follow up"]
        assert client.post("/api/investigations", json={"question": "missing session"}).status_code == 422


def test_source_has_no_legacy_river_x_or_deterministic_router():
    from pathlib import Path

    root = Path(__file__).parents[2]
    sources = [*root.glob("backend/app/**/*.py"), *root.glob("frontend/app/**/*.tsx"), *root.glob("frontend/lib/**/*.ts")]
    text = "\n".join(path.read_text().lower() for path in sources)
    assert "river-x" not in text
    assert "scenario_router" not in text
