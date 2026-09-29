from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.evaluation.evaluators import summarize
from app.evaluation.models import EvaluationReport, ScenarioEvaluation
from app.evaluation.scenarios import CORPUS_VERSION, RUBRIC_VERSION


RESULT_DIR = Path(__file__).parents[2] / ".evaluation"
LATEST_REPORT = RESULT_DIR / "latest.json"


def build_report(results: list[ScenarioEvaluation], *, model_name: str, judge_model_name: str, experiment_name: str | None = None) -> EvaluationReport:
    return EvaluationReport(
        corpus_version=CORPUS_VERSION,
        rubric_version=RUBRIC_VERSION,
        generated_at=datetime.now(timezone.utc),
        experiment_name=experiment_name,
        model_name=model_name,
        judge_model_name=judge_model_name,
        summary=summarize(results),
        scenarios=results,
    )


def save_report(report: EvaluationReport, path: Path = LATEST_REPORT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2))
    return path


def load_report(path: Path = LATEST_REPORT) -> EvaluationReport | None:
    if not path.exists():
        return None
    return EvaluationReport.model_validate(json.loads(path.read_text()))

