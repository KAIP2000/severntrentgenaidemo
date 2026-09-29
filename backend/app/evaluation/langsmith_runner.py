from __future__ import annotations

import asyncio
import subprocess
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from langsmith import Client
from langsmith.evaluation import EvaluationResult, EvaluationResults

from app.config import Settings
from app.evaluation.evaluators import evaluate_record
from app.evaluation.judges import GeminiJudges
from app.evaluation.models import EvaluationRecord, ScenarioEvaluation
from app.evaluation.reporting import build_report, save_report
from app.evaluation.scenarios import CORPUS_VERSION, RUBRIC_VERSION, SCENARIOS
from app.evaluation.target import run_scenario


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def seed_dataset(settings: Settings, client: Client | None = None) -> Any:
    client = client or Client()
    if client.has_dataset(dataset_name=settings.eval_dataset_name):
        dataset = client.read_dataset(dataset_name=settings.eval_dataset_name)
    else:
        dataset = client.create_dataset(
            settings.eval_dataset_name,
            description="Versioned behavioral, adversarial, abstention, operations, and reliability scenarios for the water-operations harness.",
            metadata={"owner": "water-operations-harness", "corpus_version": CORPUS_VERSION},
        )
    examples = []
    for scenario in SCENARIOS:
        examples.append({
            "id": uuid5(NAMESPACE_URL, f"{settings.eval_dataset_name}:{scenario.id}"),
            "inputs": {"scenario_id": scenario.id},
            "outputs": {
                "expected_status": scenario.expected_status,
                "acceptable_dispositions": sorted(scenario.acceptable_dispositions),
                "judge_context": scenario.judge_context,
            },
            "metadata": {"owner": "water-operations-harness", "scenario_id": scenario.id, "corpus_version": CORPUS_VERSION},
            "split": scenario.split,
        })
    existing = {
        str(example.id): example
        for example in client.list_examples(dataset_id=dataset.id)
        if (example.metadata or {}).get("owner") == "water-operations-harness"
    }
    missing = []
    updates = []
    for payload in examples:
        current = existing.get(str(payload["id"]))
        if current is None:
            missing.append(payload)
            continue
        updates.append({"id": current.id, "inputs": payload["inputs"], "outputs": payload["outputs"], "metadata": payload["metadata"], "split": payload["split"]})
    if updates:
        client.update_examples(dataset_id=dataset.id, updates=updates)
    if missing:
        client.create_examples(dataset_id=dataset.id, examples=missing)
    return dataset


def feedback_evaluator(outputs: dict) -> EvaluationResults:
    evaluation = ScenarioEvaluation.model_validate(outputs["evaluation"])
    feedback = [
        EvaluationResult(key="harness_success", score=float(evaluation.harness_success)),
        EvaluationResult(key="investigation_success", score=None if evaluation.investigation_success is None else float(evaluation.investigation_success)),
        EvaluationResult(key="scenario_result", value=evaluation.result),
    ]
    raw_value_metrics = {"tool_calls", "model_calls", "tokens", "latency_ms"}
    feedback.extend(
        EvaluationResult(key=key, value=str(value)) if key in raw_value_metrics else EvaluationResult(key=key, score=value)
        for key, value in evaluation.metrics.items()
    )
    feedback.extend(EvaluationResult(key=f"check:{check.key}", score=check.score, comment=check.comment) for check in evaluation.checks)
    feedback.extend(EvaluationResult(key=f"judge:{judge.key}", score=judge.score, comment=judge.rationale) for judge in evaluation.judges)
    return EvaluationResults(results=feedback)


async def run_experiment(settings: Settings, client: Client | None = None):
    client = client or Client()
    dataset = await asyncio.to_thread(seed_dataset, settings, client)
    scenarios = {scenario.id: scenario for scenario in SCENARIOS}
    judges = GeminiJudges(settings)
    selected_ids = settings.selected_eval_scenario_ids
    data = dataset
    if selected_ids:
        unknown = selected_ids - set(scenarios)
        if unknown:
            raise ValueError(f"Unknown EVAL_SCENARIO_IDS: {', '.join(sorted(unknown))}")
        data = [example for example in client.list_examples(dataset_id=dataset.id) if (example.metadata or {}).get("scenario_id") in selected_ids]

    async def target(inputs: dict) -> dict:
        scenario = scenarios[inputs["scenario_id"]]
        record = await run_scenario(scenario, settings)
        judge_results = await judges.evaluate_scenario(scenario, record)
        evaluation = evaluate_record(record, scenario, judge_results)
        return {"evaluation": evaluation.model_dump(mode="json")}

    experiment = await client.aevaluate(
        target,
        data=data,
        evaluators=[feedback_evaluator],
        experiment_prefix="water-harness",
        max_concurrency=settings.eval_max_concurrency,
        num_repetitions=settings.eval_repetitions,
        metadata={
            "corpus_version": CORPUS_VERSION,
            "rubric_version": RUBRIC_VERSION,
            "application_model": settings.model_name,
            "judge_model": settings.judge_model_name,
            "git_commit": git_commit(),
        },
    )
    results = []
    async for row in experiment:
        outputs = row["run"].outputs or {}
        if outputs.get("evaluation"):
            results.append(ScenarioEvaluation.model_validate(outputs["evaluation"]))
    expected_ids = selected_ids or set(scenarios)
    observed_counts = {scenario_id: sum(item.scenario_id == scenario_id for item in results) for scenario_id in expected_ids}
    for scenario_id, observed in observed_counts.items():
        for repetition in range(observed, settings.eval_repetitions):
            scenario = scenarios[scenario_id]
            missing_record = EvaluationRecord(
                scenario_id=scenario_id,
                session_id=f"missing-{repetition}",
                investigation_id=f"missing-{scenario_id}-{repetition}",
                thread_id="missing",
                question=scenario.question,
                status="failed",
                error="LangSmith experiment target produced no evaluation output for this expected scenario.",
                execution_failure=True,
            )
            results.append(evaluate_record(missing_record, scenario))
    report = build_report(results, model_name=settings.model_name, judge_model_name=settings.judge_model_name, experiment_name=experiment.experiment_name)
    save_report(report)
    return report, experiment.url
