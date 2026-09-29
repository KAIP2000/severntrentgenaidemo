from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.agents.orchestrator import WaterOperationsHarness
from app.config import Settings
from app.data import DATA_NOW
from app.evaluation.models import EvaluationRecord, Scenario
from app.schemas import AgentFinalResponse
from langchain_core.messages import AIMessage, ToolMessage


class _FailingAgent:
    def __init__(self, message: str):
        self.message = message

    async def astream(self, _input_value, **_kwargs):
        raise RuntimeError(self.message)
        yield

    async def aget_state(self, _config):
        return SimpleNamespace(values={}, tasks=())


class _MissingStructuredOutputAgent:
    async def astream(self, _input_value, **_kwargs):
        if False:
            yield None

    async def aget_state(self, _config):
        return SimpleNamespace(values={}, tasks=())


class _ApprovalInterruptAgent:
    async def astream(self, _input_value, **_kwargs):
        if False:
            yield None

    async def aget_state(self, _config):
        interrupt = SimpleNamespace(value={"tool": "execute_operational_action", "description": "Injected approval interruption"})
        return SimpleNamespace(values={}, tasks=(SimpleNamespace(interrupts=(interrupt,)),))


class _ToolFailureAgent:
    def __init__(self, malformed: bool = False):
        self.malformed = malformed
        self.final = AgentFinalResponse(
            status="complete",
            disposition="insufficient_evidence",
            title="Forecast unavailable",
            answer_markdown="The forecast could not be validated, so no intervention can be recommended.",
        )

    async def astream(self, _input_value, **_kwargs):
        call = {"name": "run_supply_forecast", "args": {"river_ids": ["mereford-river"], "horizon_days": 6}, "id": "fault-call", "type": "tool_call"}
        yield {"type": "updates", "ns": (), "data": {"model": {"messages": [AIMessage(content="", tool_calls=[call])]}}}
        yield {"type": "updates", "ns": (), "data": {"tools": {"messages": [ToolMessage(content="<<malformed>>" if self.malformed else "forecast service unavailable", tool_call_id="fault-call", name="run_supply_forecast", status="success" if self.malformed else "error")]}}}

    async def aget_state(self, _config):
        return SimpleNamespace(values={"structured_response": self.final}, tasks=())


def _fault_agent(scenario: Scenario) -> Any | None:
    if scenario.fault_mode == "model_outage":
        return _FailingAgent("injected model outage")
    if scenario.fault_mode == "stream_interruption":
        return _FailingAgent("injected stream interruption")
    if scenario.fault_mode == "invalid_structured_output":
        return _MissingStructuredOutputAgent()
    if scenario.fault_mode == "approval_interruption":
        return _ApprovalInterruptAgent()
    if scenario.fault_mode in {"tool_error", "forecast_unavailable"}:
        return _ToolFailureAgent()
    if scenario.fault_mode == "malformed_tool_output":
        return _ToolFailureAgent(malformed=True)
    if scenario.fault_mode == "sse_reconnect":
        return _MissingStructuredOutputAgent()
    return None


async def _wait_for(record_getter, statuses: set[str], timeout_seconds: float = 180) -> Any:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        record = record_getter()
        if record.status in statuses:
            return record
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"Investigation did not reach {sorted(statuses)} within {timeout_seconds}s")
        await asyncio.sleep(0.05)


def normalize_record(scenario: Scenario, record: Any, started_at: datetime) -> EvaluationRecord:
    activities = [activity.model_dump(mode="json") for activity in record.activities.values()]
    tool_activities = [item for item in activities if item["kind"] in {"tool", "subagent"} and item.get("tool", {}).get("name") != "task"]
    model_activities = [item for item in activities if item["kind"] == "model"]
    total_tokens = sum(item.get("usage", {}).get("total_tokens", 0) for item in model_activities)
    return EvaluationRecord(
        scenario_id=scenario.id,
        session_id=record.session_id,
        investigation_id=record.investigation_id,
        thread_id=record.thread_id,
        question=record.question,
        status=record.status,
        final=record.final.model_dump(mode="json") if record.final else None,
        activities=activities,
        evidence=[item.model_dump(mode="json") for item in record.evidence.values()],
        events=[item.model_dump(mode="json") for item in record.events],
        decisions=list(record.decisions),
        error=record.error,
        duration_ms=max(0, int((record.updated_at - started_at).total_seconds() * 1000)),
        model_calls=len(model_activities),
        tool_calls=len(tool_activities),
        total_tokens=total_tokens,
        approval_required=any(item.type == "approval_required" for item in record.events),
        tool_failure=any(
            item.get("kind") == "tool" and (
                item.get("status") == "failed"
                or (item.get("tool", {}).get("name") not in {"task", "write_todos"} and not isinstance(item.get("tool", {}).get("output"), dict))
            )
            for item in activities
        ),
        execution_failure=record.status == "failed",
    )


async def run_scenario(scenario: Scenario, settings: Settings, agent: Any | None = None) -> EvaluationRecord:
    selected_agent = agent if agent is not None else _fault_agent(scenario)
    harness = WaterOperationsHarness(settings, agent=selected_agent)
    started_at = datetime.now(timezone.utc)
    session_id = f"eval-{scenario.id.lower()}-{uuid4().hex[:8]}"
    created = await harness.create(
        scenario.question,
        session_id,
        metadata={
            "scenario_id": scenario.id,
            "scenario_split": scenario.split,
            "environment_clock": DATA_NOW.isoformat(),
        },
    )
    record = await _wait_for(
        lambda: harness.get(created.investigation_id),
        harness.TERMINAL,
        timeout_seconds=settings.eval_scenario_timeout_seconds,
    )
    if scenario.decision and record.status == "awaiting_approval":
        await harness.decide(record.investigation_id, scenario.decision)
        record = await _wait_for(
            lambda: harness.get(created.investigation_id),
            harness.TERMINAL,
            timeout_seconds=settings.eval_scenario_timeout_seconds,
        )
    normalized = normalize_record(scenario, record, started_at)
    if scenario.fault_mode == "sse_reconnect":
        replayed = []
        async for payload in harness.event_stream(record.investigation_id, after=1):
            if payload.startswith("id:"):
                replayed.append(int(payload.splitlines()[0].split(": ")[1]))
        normalized.sse_replay_verified = bool(replayed) and all(sequence > 1 for sequence in replayed) and replayed == sorted(replayed)
    return normalized
