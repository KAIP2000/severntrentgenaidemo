from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from uuid import uuid4

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Command

from app.config import Settings
from app.models import ModelGateway
from app.schemas import Activity, AgentFinalResponse, Calculation, Evidence, InvestigationView, StreamEvent

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RunRecord:
    session_id: str
    investigation_id: str
    thread_id: str
    question: str
    model_provider: str
    model_name: str
    status: str = "queued"
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    plan: list[dict[str, Any]] = field(default_factory=list)
    activities: dict[str, Activity] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    final: AgentFinalResponse | None = None
    error: str | None = None
    events: list[StreamEvent] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)

    def view(self) -> InvestigationView:
        return InvestigationView(
            session_id=self.session_id,
            investigation_id=self.investigation_id,
            thread_id=self.thread_id,
            question=self.question,
            status=self.status,
            created_at=self.created_at,
            updated_at=self.updated_at,
            model_provider=self.model_provider,
            model_name=self.model_name,
            plan=self.plan,
            activities=list(self.activities.values()),
            evidence=list(self.evidence.values()),
            final=self.final,
            error=self.error,
            last_sequence=len(self.events),
        )


class WaterOperationsHarness:
    """Gemini-owned execution with session grouping, isolated graph threads and replayable events."""

    TERMINAL = {"complete", "clarification_required", "awaiting_approval", "failed"}

    def __init__(self, settings: Settings, agent: Any | None = None):
        self.settings = settings
        self.checkpointer = InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=[AgentFinalResponse]))
        self.agent = agent
        if self.agent is None and settings.live_model_available:
            from app.agents.deep_agent import create_water_deep_agent

            self.agent = create_water_deep_agent(ModelGateway(settings), self.checkpointer)
        self.investigations: dict[str, RunRecord] = {}
        self.sessions: dict[str, list[str]] = {}

    async def create(self, question: str, session_id: str) -> RunRecord:
        investigation_id = f"INV-{_now():%Y%m%d}-{uuid4().hex[:8].upper()}"
        thread_id = f"THR-{uuid4().hex}"
        record = RunRecord(
            session_id=session_id,
            investigation_id=investigation_id,
            thread_id=thread_id,
            question=question,
            model_provider=self.settings.model_provider,
            model_name=self.settings.model_name,
        )
        self.investigations[investigation_id] = record
        self.sessions.setdefault(session_id, []).append(investigation_id)
        asyncio.create_task(self._run(record))
        return record

    def get(self, investigation_id: str) -> RunRecord | None:
        return self.investigations.get(investigation_id)

    def session(self, session_id: str) -> list[RunRecord]:
        return [self.investigations[item] for item in self.sessions.get(session_id, [])]

    async def decide(self, investigation_id: str, decision: str) -> RunRecord:
        record = self.investigations[investigation_id]
        if record.status != "awaiting_approval":
            raise ValueError("Investigation is not awaiting approval")
        record.status = "running"
        record.updated_at = _now()
        resume = Command(resume={"decisions": [{"type": decision}]})
        asyncio.create_task(self._run(record, command=resume))
        return record

    async def _emit(self, record: RunRecord, event_type: str, data: dict[str, Any]) -> StreamEvent:
        event = StreamEvent(
            seq=len(record.events) + 1,
            session_id=record.session_id,
            investigation_id=record.investigation_id,
            thread_id=record.thread_id,
            timestamp=_now(),
            type=event_type,
            data=data,
        )
        record.events.append(event)
        record.updated_at = event.timestamp
        async with record.condition:
            record.condition.notify_all()
        return event

    def _history(self, record: RunRecord) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for investigation_id in self.sessions.get(record.session_id, []):
            prior = self.investigations[investigation_id]
            if prior.investigation_id == record.investigation_id:
                break
            if prior.final:
                messages.extend([
                    {"role": "user", "content": prior.question},
                    {"role": "assistant", "content": prior.final.answer_markdown},
                ])
        return messages[-16:]

    async def _run(self, record: RunRecord, command: Command | None = None) -> None:
        record.status = "running"
        await self._emit(record, "run_started", {"question": record.question, "resumed": command is not None})
        if self.agent is None:
            record.status = "failed"
            record.error = "Gemini is not configured. Set a valid API key and enable live execution."
            await self._emit(record, "run_failed", {"error": record.error})
            return

        config = {"configurable": {"thread_id": record.thread_id}, "metadata": {"session_id": record.session_id, "investigation_id": record.investigation_id}}
        input_value: Any = command or {"messages": [*self._history(record), {"role": "user", "content": record.question}]}
        try:
            async for chunk in self.agent.astream(
                input_value,
                config=config,
                stream_mode=["updates", "messages", "custom"],
                subgraphs=True,
                version="v2",
            ):
                await self._consume_chunk(record, chunk)

            snapshot = await self.agent.aget_state(config)
            interrupts = self._interrupts(snapshot)
            if interrupts:
                record.status = "awaiting_approval"
                await self._emit(record, "approval_required", {"requests": interrupts})
                return

            structured = snapshot.values.get("structured_response") if snapshot and snapshot.values else None
            if structured is None:
                raise RuntimeError("Gemini completed without a validated structured response")
            record.final = structured if isinstance(structured, AgentFinalResponse) else AgentFinalResponse.model_validate(structured)
            self._validate_final(record)
            record.status = record.final.status
            await self._emit(record, "answer_delta", {"text": record.final.answer_markdown, "final": True})
            terminal_type = "clarification_required" if record.status == "clarification_required" else "run_completed"
            await self._emit(record, terminal_type, {"result": record.final.model_dump(mode="json")})
        except Exception as exc:
            logger.exception("Deep Agent run failed for %s", record.investigation_id)
            failed_at = _now()
            for activity in record.activities.values():
                if activity.status == "active":
                    activity.status = "failed"
                    activity.completed_at = failed_at
                    activity.duration_ms = max(0, int((failed_at - activity.started_at).total_seconds() * 1000))
                    activity.error = str(exc)
                    await self._emit(record, "activity_completed", {"activity": activity.model_dump(mode="json")})
            record.status = "failed"
            record.error = str(exc)
            await self._emit(record, "run_failed", {"error": record.error})

    @staticmethod
    def _interrupts(snapshot: Any) -> list[dict[str, Any]]:
        found = []
        for task in getattr(snapshot, "tasks", ()) or ():
            for interrupt in getattr(task, "interrupts", ()) or ():
                value = getattr(interrupt, "value", interrupt)
                found.append(value if isinstance(value, dict) else {"description": str(value)})
        return found

    @staticmethod
    def _validate_final(record: RunRecord) -> None:
        assert record.final is not None
        known = set(record.evidence)
        unknown_citations = set(record.final.evidence_ids) - known
        if unknown_citations:
            raise RuntimeError(f"Gemini cited unknown evidence IDs: {', '.join(sorted(unknown_citations))}")
        for chart in record.final.charts:
            evidence = record.evidence.get(chart.evidence_id)
            if not evidence:
                raise RuntimeError(f"Chart references unknown evidence ID: {chart.evidence_id}")
            available_fields = {key for row in evidence.records for key in row}
            missing_fields = {chart.x_field, *chart.y_fields} - available_fields
            if missing_fields:
                raise RuntimeError(f"Chart references fields absent from evidence: {', '.join(sorted(missing_fields))}")

    async def _consume_chunk(self, record: RunRecord, chunk: Any) -> None:
        if not isinstance(chunk, dict):
            return
        chunk_type = chunk.get("type")
        namespace = chunk.get("ns") or ()
        agent_name = self._agent_name(namespace)
        if chunk_type == "updates":
            for node, update in (chunk.get("data") or {}).items():
                if not isinstance(update, dict):
                    continue
                structured = update.get("structured_response")
                if structured:
                    record.final = structured if isinstance(structured, AgentFinalResponse) else AgentFinalResponse.model_validate(structured)
                for message in update.get("messages", []):
                    if isinstance(message, AIMessage):
                        await self._model_completed(record, message, agent_name, node)
                        for call in message.tool_calls:
                            await self._tool_started(record, call, agent_name)
                    elif isinstance(message, ToolMessage):
                        await self._tool_completed(record, message, agent_name)
        elif chunk_type == "custom":
            data = chunk.get("data")
            if isinstance(data, dict) and data.get("todos"):
                record.plan = data["todos"]
                await self._emit(record, "plan_updated", {"plan": record.plan})
        elif chunk_type == "messages":
            data = chunk.get("data")
            if isinstance(data, (tuple, list)) and data:
                message = data[0]
                metadata = data[1] if len(data) > 1 and isinstance(data[1], dict) else {}
                if message.__class__.__name__.startswith("AIMessage"):
                    await self._model_started(record, message, self._agent_name(namespace), metadata)

    @staticmethod
    def _agent_name(namespace: Any) -> str:
        if not namespace:
            return "Water Operations Agent"
        if isinstance(namespace, str):
            return namespace
        return " / ".join(str(part).split(":")[0] for part in namespace)

    @staticmethod
    def _model_activity_id(message: Any, agent_name: str, metadata: dict[str, Any] | None = None, node: str | None = None) -> str:
        metadata = metadata or {}
        identity = getattr(message, "id", None) or f"{agent_name}:{node or metadata.get('langgraph_node', 'model')}:{metadata.get('langgraph_step', 'stream')}"
        return f"MODEL-{identity}"

    async def _model_started(self, record: RunRecord, message: Any, agent_name: str, metadata: dict[str, Any]) -> None:
        activity_id = self._model_activity_id(message, agent_name, metadata)
        if activity_id in record.activities:
            return
        node = str(metadata.get("langgraph_node") or "Gemini")
        activity = Activity(
            id=activity_id,
            agent=agent_name,
            kind="model",
            label=f"{node} model call",
            started_at=_now(),
            result_summary="Streaming model response",
        )
        record.activities[activity_id] = activity
        await self._emit(record, "activity_started", {"activity": activity.model_dump(mode="json")})

    async def _model_completed(self, record: RunRecord, message: AIMessage, agent_name: str, node: str) -> None:
        activity_id = self._model_activity_id(message, agent_name, node=node)
        activity = record.activities.get(activity_id)
        if not activity:
            candidates = [item for item in record.activities.values() if item.kind == "model" and item.status == "active" and item.agent == agent_name]
            activity = candidates[-1] if candidates else None
        if not activity or activity.status != "active":
            return
        activity.status = "complete"
        activity.completed_at = _now()
        activity.duration_ms = max(0, int((activity.completed_at - activity.started_at).total_seconds() * 1000))
        usage = getattr(message, "usage_metadata", None) or {}
        total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
        activity.result_summary = f"Model call completed{f' · {total_tokens} tokens' if total_tokens is not None else ''}"
        await self._emit(record, "activity_completed", {"activity": activity.model_dump(mode="json")})

    async def _tool_started(self, record: RunRecord, call: dict[str, Any], agent_name: str) -> None:
        call_id = call.get("id") or f"CALL-{uuid4().hex[:10]}"
        name = call.get("name", "tool")
        inputs = call.get("args") or {}
        if name == "write_todos":
            record.plan = inputs.get("todos", [])
            await self._emit(record, "plan_updated", {"plan": record.plan})
            return
        if call_id in record.activities:
            return
        activity = Activity(
            id=call_id,
            agent=agent_name,
            kind="subagent" if name == "task" else "tool",
            label=f"Calling {name}",
            started_at=_now(),
            tool={"name": name, "inputs": inputs},
        )
        record.activities[call_id] = activity
        await self._emit(record, "activity_started", {"activity": activity.model_dump(mode="json")})

    @staticmethod
    def _decode_tool_output(message: ToolMessage) -> Any:
        artifact = getattr(message, "artifact", None)
        if isinstance(artifact, dict):
            return artifact
        content = message.content
        if isinstance(content, dict):
            return content
        if isinstance(content, list):
            texts = [part.get("text", "") for part in content if isinstance(part, dict)]
            content = "".join(texts)
        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return content
        return content

    async def _tool_completed(self, record: RunRecord, message: ToolMessage, agent_name: str) -> None:
        call_id = message.tool_call_id or f"CALL-{uuid4().hex[:10]}"
        output = self._decode_tool_output(message)
        activity = record.activities.get(call_id)
        if not activity:
            activity = Activity(id=call_id, agent=agent_name, kind="tool", label=f"Completed {message.name or 'tool'}", started_at=_now(), tool={"name": message.name or "tool", "inputs": {}})
            record.activities[call_id] = activity
        activity.status = "complete"
        activity.completed_at = _now()
        activity.duration_ms = max(0, int((activity.completed_at - activity.started_at).total_seconds() * 1000))
        if activity.tool:
            activity.tool.output = output
        if isinstance(output, dict) and output.get("evidence_id"):
            evidence = Evidence(
                id=output["evidence_id"],
                title=output.get("summary") or activity.tool.name,
                source=output.get("source", "Unknown source"),
                period=output.get("period") or {},
                query=output.get("query") or {},
                summary=output.get("summary", ""),
                records=output.get("records") or [],
                calculations=[Calculation.model_validate(item) for item in output.get("calculations") or []],
                provenance=output.get("provenance") or {},
            )
            record.evidence[evidence.id] = evidence
            activity.evidence = [evidence]
            activity.calculations = evidence.calculations
            activity.result_summary = evidence.summary
        else:
            activity.result_summary = output if isinstance(output, str) else json.dumps(output, default=str)[:500]
        await self._emit(record, "activity_completed", {"activity": activity.model_dump(mode="json")})

    async def event_stream(self, investigation_id: str, after: int = 0) -> AsyncIterator[str]:
        record = self.investigations[investigation_id]
        cursor = max(0, after)
        while True:
            while cursor < len(record.events):
                event = record.events[cursor]
                cursor = event.seq
                yield f"id: {event.seq}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
            if record.status in self.TERMINAL and cursor >= len(record.events):
                break
            try:
                async with record.condition:
                    await asyncio.wait_for(record.condition.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
