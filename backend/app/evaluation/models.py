from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


Disposition = Literal["conclusion", "insufficient_evidence", "conflicting_evidence", "no_action_required"]
ScenarioResult = Literal["PASS", "PARTIAL", "FAIL"]
JudgeName = Literal["trajectory", "evidence", "recommendation"]
CriticalFailureCode = Literal[
    "approval_bypass",
    "fabricated_evidence",
    "unsafe_action",
    "unjustified_causal_conclusion",
    "ignored_material_conflict",
    "intervention_without_need",
    "concealed_execution_failure",
]


class ArgumentConstraint(BaseModel):
    tool: str
    field: str
    equals: Any | None = None
    duration_hours: int | None = None
    required: bool = True


class Scenario(BaseModel):
    id: str
    split: Literal["standard", "supply", "operations", "abstention", "adversarial", "reliability"]
    question: str
    expected_status: Literal["complete", "clarification_required", "awaiting_approval", "failed"]
    acceptable_dispositions: set[Disposition] = Field(default_factory=lambda: {"conclusion"})
    required_capabilities: set[str] = Field(default_factory=set)
    allowed_tools: set[str] = Field(default_factory=set)
    forbidden_tools: set[str] = Field(default_factory=set)
    required_sources: set[str] = Field(default_factory=set)
    argument_constraints: list[ArgumentConstraint] = Field(default_factory=list)
    decision: Literal["approve", "reject"] | None = None
    expect_execution: bool = False
    max_tool_calls: int = 12
    judge_names: set[JudgeName] = Field(default_factory=lambda: {"trajectory", "evidence"})
    judge_context: str
    include_in_investigation_rate: bool = True
    fault_mode: Literal["model_outage", "stream_interruption", "invalid_structured_output", "approval_interruption", "tool_error", "malformed_tool_output", "forecast_unavailable", "sse_reconnect"] | None = None

    @model_validator(mode="after")
    def validate_contract(self):
        if self.allowed_tools & self.forbidden_tools:
            raise ValueError("A tool cannot be both allowed and forbidden")
        if self.decision and self.expected_status != "complete":
            raise ValueError("Decision scenarios must expect completion after resume")
        if self.expect_execution and self.decision != "approve":
            raise ValueError("Execution requires an approve decision")
        if self.split in {"abstention", "adversarial"} and not self.acceptable_dispositions:
            raise ValueError("Safety scenarios require an explicit disposition expectation")
        return self


class EvaluationRecord(BaseModel):
    scenario_id: str
    session_id: str
    investigation_id: str
    thread_id: str
    question: str
    status: str
    final: dict[str, Any] | None = None
    activities: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    error: str | None = None
    duration_ms: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    total_tokens: int = 0
    approval_required: bool = False
    tool_failure: bool = False
    execution_failure: bool = False
    sse_replay_verified: bool = False


class CheckResult(BaseModel):
    key: str
    score: float = Field(ge=0, le=1)
    passed: bool
    mandatory: bool = True
    comment: str = ""


class JudgeResult(BaseModel):
    key: JudgeName
    score: float = Field(ge=0, le=1)
    passed: bool
    rationale: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    critical_failure: bool = False
    critical_failure_code: CriticalFailureCode | None = None

    @model_validator(mode="after")
    def validate_critical_failure(self):
        if self.critical_failure != (self.critical_failure_code is not None):
            raise ValueError("critical_failure and critical_failure_code must agree")
        return self


class ScenarioEvaluation(BaseModel):
    scenario_id: str
    split: str
    result: ScenarioResult
    harness_success: bool
    investigation_success: bool | None
    checks: list[CheckResult]
    judges: list[JudgeResult] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    record: EvaluationRecord


class EvaluationReport(BaseModel):
    corpus_version: str
    rubric_version: str
    generated_at: datetime
    experiment_name: str | None = None
    model_name: str
    judge_model_name: str
    summary: dict[str, float]
    scenarios: list[ScenarioEvaluation]
