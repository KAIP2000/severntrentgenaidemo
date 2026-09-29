import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.data import DATA_NOW
from app.evaluation.evaluators import evaluate_record
from app.evaluation.langsmith_runner import seed_dataset
from app.evaluation.langsmith_runner import feedback_evaluator
from app.evaluation.models import EvaluationRecord, JudgeResult
from app.evaluation.scenarios import SCENARIOS, validate_corpus
from app.evaluation.target import run_scenario
from app.tools.river import get_river_flow_history, get_sensor_history


def scenario(scenario_id):
    return next(item for item in SCENARIOS if item.id == scenario_id)


def evidence(output):
    return {"id": output["evidence_id"], "source": output["source"], "summary": output["summary"], "records": output["records"], "calculations": output["calculations"], "query": output["query"], "period": output["period"], "provenance": output["provenance"]}


def activity(call_id, name, inputs, output, *, status="complete"):
    return {"id": call_id, "kind": "tool", "agent": "Water Operations Agent", "label": name, "status": status, "tool": {"name": name, "inputs": inputs, "output": output}, "usage": {}}


def judge(key, score=0.9, critical=False, code=None):
    return JudgeResult(key=key, score=score, passed=score >= 0.75 and not critical, rationale="Evidence-backed rubric result", critical_failure=critical, critical_failure_code=code)


def mereford_record():
    start = (DATA_NOW - timedelta(hours=48)).isoformat()
    end = DATA_NOW.isoformat()
    flow_inputs = {"river_id": "mereford-river", "start": start, "end": end, "aggregation": "12h"}
    sensor_inputs = {"river_id": "mereford-river", "start": start, "end": end}
    flow = get_river_flow_history(**flow_inputs)
    sensors = get_sensor_history(**sensor_inputs)
    return EvaluationRecord(
        scenario_id="S1-MEREFORD", session_id="eval", investigation_id="INV-1", thread_id="THR-1", question=scenario("S1-MEREFORD").question, status="complete",
        final={"status": "complete", "disposition": "conclusion", "evidence_ids": [flow["evidence_id"], sensors["evidence_id"]], "answer_markdown": "The degraded upstream sensor explains the apparent decline."},
        activities=[activity("c1", "get_river_flow_history", flow_inputs, flow), activity("c2", "get_sensor_history", sensor_inputs, sensors)],
        evidence=[evidence(flow), evidence(sensors)],
        events=[{"seq": 1, "type": "run_started", "data": {}}, {"seq": 2, "type": "run_completed", "data": {}}],
    )


def test_corpus_is_unique_and_rejects_duplicate_ids():
    validate_corpus()
    with pytest.raises(ValueError, match="unique"):
        validate_corpus([SCENARIOS[0], SCENARIOS[0]])


def test_complete_grounded_investigation_passes_all_mandatory_checks():
    result = evaluate_record(mereford_record(), scenario("S1-MEREFORD"), [judge("trajectory"), judge("evidence")])
    assert result.result == "PASS"
    assert result.harness_success is True
    assert result.investigation_success is True
    assert result.metrics["calculation_accuracy"] == 1
    assert all(item.passed for item in result.checks if item.mandatory)


def test_bad_arguments_duplicates_and_corrupt_calculation_fail_deterministically():
    record = mereford_record()
    record.activities[0]["tool"]["inputs"]["aggregation"] = "1h"
    record.activities.append(deepcopy(record.activities[1]))
    record.activities[0]["tool"]["output"]["calculations"][0]["result"] = -999
    record.tool_calls = 3
    result = evaluate_record(record, scenario("S1-MEREFORD"), [judge("trajectory"), judge("evidence")])
    failed = {item.key for item in result.checks if not item.passed}
    assert result.result == "FAIL"
    assert "arguments:get_river_flow_history:aggregation" in failed
    assert "duplicate_calls" in failed
    assert "calculation_accuracy" in failed


def test_argument_checks_accept_tool_defaults_recorded_in_output_query():
    record = mereford_record()
    record.activities[0]["tool"]["inputs"].pop("aggregation")
    result = evaluate_record(record, scenario("S1-MEREFORD"), [judge("trajectory"), judge("evidence")])
    assert next(item for item in result.checks if item.key == "arguments:get_river_flow_history:aggregation").passed


def test_argument_checks_accept_normalized_query_from_activity_evidence():
    record = mereford_record()
    record.activities[0]["tool"]["inputs"].pop("aggregation")
    record.activities[0]["tool"]["output"] = "serialized provider output"
    record.activities[0]["evidence"] = [record.evidence[0]]
    result = evaluate_record(record, scenario("S1-MEREFORD"), [judge("trajectory"), judge("evidence")])
    assert next(item for item in result.checks if item.key == "arguments:get_river_flow_history:aggregation").passed


def test_missing_judges_fail_closed_as_partial_not_success():
    result = evaluate_record(mereford_record(), scenario("S1-MEREFORD"), [])
    assert result.result == "PARTIAL"
    assert result.harness_success is True
    assert result.investigation_success is False


def test_critical_judge_overrides_high_scores():
    result = evaluate_record(mereford_record(), scenario("S1-MEREFORD"), [judge("evidence"), judge("trajectory", 0.99, True, "unjustified_causal_conclusion")])
    assert result.result == "FAIL"
    assert result.investigation_success is False


def test_structured_abstention_is_required_without_keyword_matching():
    selected = scenario("A-INSUFFICIENT")
    record = mereford_record().model_copy(update={"scenario_id": selected.id, "question": selected.question})
    record.final["disposition"] = "conclusion"
    failed = evaluate_record(record, selected, [judge("trajectory"), judge("evidence")])
    assert failed.result == "FAIL"
    record.final["disposition"] = "insufficient_evidence"
    passed = evaluate_record(record, selected, [judge("trajectory"), judge("evidence")])
    assert next(item for item in passed.checks if item.key == "correct_abstention").passed


def test_execution_without_approval_is_a_mandatory_failure():
    selected = scenario("A-BYPASS")
    record = mereford_record().model_copy(update={"scenario_id": selected.id, "question": selected.question, "status": "awaiting_approval"})
    record.activities.append(activity("execute", "execute_operational_action", {}, {"status": "completed"}))
    result = evaluate_record(record, selected, [judge("trajectory"), judge("evidence"), judge("recommendation")])
    assert next(item for item in result.checks if item.key == "hitl_safety").passed is False
    assert result.result == "FAIL"


def test_rejected_execution_attempt_is_not_counted_as_execution():
    selected = scenario("S3-REJECT")
    record = mereford_record().model_copy(update={
        "scenario_id": selected.id,
        "question": selected.question,
        "decisions": ["reject"],
    })
    record.activities.append(activity(
        "execute",
        "execute_operational_action",
        {},
        {"status": "rejected", "message": "User rejected the request; action was not executed."},
        status="failed",
    ))
    result = evaluate_record(record, selected, [judge("trajectory"), judge("evidence"), judge("recommendation")])
    assert next(item for item in result.checks if item.key == "hitl_safety").passed is True


def test_pending_approval_allows_one_active_protected_tool():
    selected = scenario("A-BYPASS")
    record = mereford_record().model_copy(update={
        "scenario_id": selected.id,
        "question": selected.question,
        "status": "awaiting_approval",
        "approval_required": True,
    })
    record.activities.append(activity("execute", "execute_operational_action", {}, None, status="active"))
    record.events[-1] = {"seq": 2, "type": "approval_required", "data": {}}
    result = evaluate_record(record, selected, [judge("trajectory"), judge("evidence"), judge("recommendation")])
    assert next(item for item in result.checks if item.key == "trace_observability").passed is True
    assert next(item for item in result.checks if item.key == "hitl_safety").passed is True


def test_safety_evaluator_accepts_model_activity_events_with_null_tools():
    selected = scenario("A-LEADING")
    record = mereford_record().model_copy(update={"scenario_id": selected.id, "question": selected.question})
    record.events.insert(1, {
        "seq": 2,
        "type": "activity_started",
        "data": {"activity": {"kind": "model", "tool": None}},
    })
    record.events[-1]["seq"] = 3
    result = evaluate_record(record, selected, [judge("trajectory"), judge("evidence")])
    assert next(item for item in result.checks if item.key == "hitl_safety").passed is True


def test_injected_model_failure_is_harness_success_and_not_investigation_denominator():
    async def check():
        selected = scenario("R-MODEL")
        record = await run_scenario(selected, Settings(agent_execution_mode="simulation"))
        result = evaluate_record(record, selected)
        assert record.status == "failed"
        assert record.final is None and record.evidence == []
        assert result.harness_success is True
        assert result.investigation_success is None

    asyncio.run(check())


class FakeLangSmithClient:
    def __init__(self):
        self.dataset = SimpleNamespace(id="dataset-1", name="Water Operations - Harness Scenarios v1")
        self.calls = []
        self.examples = {}
        self.updates = []

    def has_dataset(self, **_kwargs):
        return True

    def read_dataset(self, **_kwargs):
        return self.dataset

    def create_examples(self, **kwargs):
        self.calls.append(kwargs)
        for item in kwargs["examples"]:
            self.examples[str(item["id"])] = SimpleNamespace(id=item["id"], metadata=item["metadata"])

    def list_examples(self, **_kwargs):
        return list(self.examples.values())

    def update_examples(self, **kwargs):
        self.updates.extend(kwargs["updates"])


def test_dataset_seed_is_idempotent_and_preserves_stable_example_ids():
    client = FakeLangSmithClient()
    settings = Settings(agent_execution_mode="simulation")
    seed_dataset(settings, client)
    seed_dataset(settings, client)
    assert len(client.calls) == 1
    first = client.calls[0]
    assert len(client.updates) == len(SCENARIOS)
    assert {item["split"] for item in first["examples"]} == {"standard", "supply", "operations", "abstention", "adversarial", "reliability"}
    assert all(item["metadata"]["owner"] == "water-operations-harness" for item in first["examples"])


def test_unbounded_observability_metrics_are_feedback_values_not_scores():
    selected = scenario("S1-MEREFORD")
    evaluation = evaluate_record(mereford_record().model_copy(update={"total_tokens": 147_529, "duration_ms": 180_000}), selected, [judge("trajectory"), judge("evidence")])
    feedback = feedback_evaluator({"evaluation": evaluation.model_dump(mode="json")})
    by_key = {item.key: item for item in feedback["results"]}
    assert by_key["tokens"].score is None and by_key["tokens"].value == "147529.0"
    assert by_key["latency_ms"].score is None and by_key["latency_ms"].value == "180000.0"


def test_scenario_filter_parses_comma_separated_ids():
    settings = Settings(agent_execution_mode="simulation", eval_scenario_ids="R-MODEL, R-SSE")
    assert settings.selected_eval_scenario_ids == {"R-MODEL", "R-SSE"}


def test_scenario_timeout_setting_reads_environment(monkeypatch):
    monkeypatch.setenv("EVAL_SCENARIO_TIMEOUT_SECONDS", "900")
    assert Settings().eval_scenario_timeout_seconds == 900


def test_evaluation_api_returns_catalog_and_no_report_when_not_run(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import app.main as main

    monkeypatch.setattr(main, "load_report", lambda: None)
    with TestClient(main.app) as client:
        assert client.get("/api/evaluations/latest").json() is None
        payload = client.get("/api/evaluations/scenarios").json()
        assert payload["corpus_version"]
        assert len(payload["scenarios"]) == len(SCENARIOS)
        assert client.get("/api/evaluations/status").json()["status"] in {"idle", "complete", "failed", "cancelled", "disabled", "skipped"}


def test_startup_evaluation_updates_runtime_status(monkeypatch):
    import app.main as main

    async def fake_run(_settings):
        return SimpleNamespace(scenarios=[1, 2, 3]), "https://example.test/experiment"

    monkeypatch.setattr(main, "run_experiment", fake_run)
    main.evaluation_runtime.update(status="idle", started_at=None, completed_at=None, experiment_url=None, scenario_count=0, error=None)
    asyncio.run(main._run_startup_evaluation())
    assert main.evaluation_runtime["status"] == "complete"
    assert main.evaluation_runtime["scenario_count"] == 3
    assert main.evaluation_runtime["experiment_url"] == "https://example.test/experiment"
