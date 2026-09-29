from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Calculation(BaseModel):
    label: str
    formula: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    unit: str | None = None


class Evidence(BaseModel):
    id: str
    title: str
    source: str
    period: dict[str, Any] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    summary: str
    records: list[dict[str, Any]] = Field(default_factory=list)
    calculations: list[Calculation] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class ToolInteraction(BaseModel):
    name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    output: Any = None


class Activity(BaseModel):
    id: str
    parent_id: str | None = None
    agent: str
    kind: Literal["model", "tool", "subagent", "plan", "approval"] = "tool"
    label: str
    status: Literal["active", "complete", "failed"] = "active"
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    tool: ToolInteraction | None = None
    result_summary: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    calculations: list[Calculation] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


class Recommendation(BaseModel):
    id: str
    action: str
    rationale: str
    expected_impact_ml_day: float | None = None
    risk: Literal["Low", "Medium", "High"] | None = None


class ChartSpec(BaseModel):
    type: Literal["line", "bar"]
    title: str
    evidence_id: str
    x_field: str
    y_fields: list[str]


class AgentFinalResponse(BaseModel):
    """Provider-validated final response emitted after the tool loop."""

    status: Literal["complete", "clarification_required"]
    disposition: Literal["conclusion", "insufficient_evidence", "conflicting_evidence", "no_action_required"] = "conclusion"
    title: str
    answer_markdown: str
    scope: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: int | None = Field(default=None, ge=0, le=100)
    confidence_rationale: str | None = None
    recommendation: Recommendation | None = None
    charts: list[ChartSpec] = Field(default_factory=list)


class InvestigationRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    session_id: str = Field(min_length=1, max_length=100)

    @field_validator("question")
    @classmethod
    def question_must_contain_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Ask a question or enter a message.")
        return cleaned


class InvestigationCreated(BaseModel):
    session_id: str
    investigation_id: str
    thread_id: str
    events_url: str


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]


class StreamEvent(BaseModel):
    seq: int
    session_id: str
    investigation_id: str
    thread_id: str
    timestamp: datetime
    type: Literal["run_started", "plan_updated", "activity_started", "activity_completed", "answer_delta", "clarification_required", "approval_required", "run_completed", "run_failed"]
    data: dict[str, Any] = Field(default_factory=dict)


class InvestigationView(BaseModel):
    session_id: str
    investigation_id: str
    thread_id: str
    question: str
    status: Literal["queued", "running", "clarification_required", "awaiting_approval", "complete", "failed"]
    created_at: datetime
    updated_at: datetime
    model_provider: str
    model_name: str
    plan: list[dict[str, Any]] = Field(default_factory=list)
    activities: list[Activity] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    final: AgentFinalResponse | None = None
    error: str | None = None
    last_sequence: int = 0


class SessionView(BaseModel):
    session_id: str
    investigations: list[InvestigationView]


class DecisionAccepted(BaseModel):
    investigation_id: str
    thread_id: str
    status: Literal["running"]
    events_url: str
    after: int
