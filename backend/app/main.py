import asyncio
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agents import WaterOperationsHarness
from app.config import get_settings
from app.data import ENVIRONMENT
from app.evaluation.reporting import load_report
from app.evaluation.scenarios import CORPUS_VERSION, SCENARIOS
from app.evaluation.models import EvaluationReport
from app.evaluation.langsmith_runner import run_experiment
from app.schemas import DecisionAccepted, DecisionRequest, InvestigationCreated, InvestigationRequest, InvestigationView, SessionView

settings = get_settings()
evaluation_runtime: dict = {
    "status": "idle",
    "started_at": None,
    "completed_at": None,
    "experiment_url": None,
    "scenario_count": 0,
    "error": None,
}


async def _run_startup_evaluation() -> None:
    evaluation_runtime.update(status="running", started_at=datetime.now(timezone.utc).isoformat(), completed_at=None, experiment_url=None, scenario_count=0, error=None)
    try:
        report, url = await run_experiment(settings)
        evaluation_runtime.update(
            status="complete",
            completed_at=datetime.now(timezone.utc).isoformat(),
            experiment_url=url,
            scenario_count=len(report.scenarios),
        )
    except asyncio.CancelledError:
        evaluation_runtime.update(status="cancelled", completed_at=datetime.now(timezone.utc).isoformat())
        raise
    except Exception as exc:
        evaluation_runtime.update(status="failed", completed_at=datetime.now(timezone.utc).isoformat(), error=str(exc))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task: asyncio.Task | None = None
    if settings.eval_run_on_startup and settings.live_model_available and not os.getenv("PYTEST_CURRENT_TEST"):
        task = asyncio.create_task(_run_startup_evaluation(), name="startup-harness-evaluation")
    elif not settings.eval_run_on_startup:
        evaluation_runtime.update(status="disabled")
    elif not settings.live_model_available:
        evaluation_runtime.update(status="skipped", error="Live model execution is not configured.")
    yield
    if task and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title=settings.app_name, version="0.3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins.split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
harness = WaterOperationsHarness(settings)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model": settings.model_name,
        "provider": settings.model_provider,
        "live_model": settings.live_model_available,
        "rivers": len(ENVIRONMENT["rivers"]),
        "data_intervals": 60,
        "middleware": ["TodoList", "Filesystem", "SubAgent", "Summarization", "ModelCallLimit", "ToolCallLimit", "HumanInTheLoop"],
    }


@app.get("/api/overview")
def overview():
    return {
        "network_health": "Watch",
        "rivers_monitored": len(ENVIRONMENT["rivers"]),
        "sensors": len(ENVIRONMENT["sensors"]),
        "active_incidents": sum(item["status"] == "open" for item in ENVIRONMENT["incidents"]),
        "pending_approvals": sum(item.status == "awaiting_approval" for item in harness.investigations.values()),
        "generated_at": ENVIRONMENT["generated_at"],
    }


@app.get("/api/evaluations/latest", response_model=EvaluationReport | None)
def latest_evaluation():
    """Return the most recent startup- or CLI-generated evaluation report."""
    return load_report()


@app.get("/api/evaluations/status")
def evaluation_status():
    return evaluation_runtime


@app.get("/api/evaluations/scenarios")
def evaluation_scenarios():
    return {
        "corpus_version": CORPUS_VERSION,
        "scenarios": [
            {"id": item.id, "split": item.split, "question": item.question, "expected_status": item.expected_status}
            for item in SCENARIOS
        ],
    }


@app.post("/api/investigations", response_model=InvestigationCreated, status_code=status.HTTP_202_ACCEPTED)
async def create_investigation(request: InvestigationRequest):
    record = await harness.create(request.question, request.session_id)
    return InvestigationCreated(session_id=record.session_id, investigation_id=record.investigation_id, thread_id=record.thread_id, events_url=f"/api/investigations/{record.investigation_id}/events")


@app.get("/api/investigations/{investigation_id}", response_model=InvestigationView)
def get_investigation(investigation_id: str):
    record = harness.get(investigation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return record.view()


@app.get("/api/investigations/{investigation_id}/events")
def investigation_events(investigation_id: str, after: int = Query(default=0, ge=0)):
    if not harness.get(investigation_id):
        raise HTTPException(status_code=404, detail="Investigation not found")
    return StreamingResponse(harness.event_stream(investigation_id, after), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/sessions/{session_id}", response_model=SessionView)
def get_session(session_id: str):
    return SessionView(session_id=session_id, investigations=[record.view() for record in harness.session(session_id)])


@app.post("/api/investigations/{investigation_id}/decision", response_model=DecisionAccepted, status_code=status.HTTP_202_ACCEPTED)
async def decide(investigation_id: str, request: DecisionRequest):
    record = harness.get(investigation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Investigation not found")
    try:
        record = await harness.decide(investigation_id, request.decision)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DecisionAccepted(investigation_id=record.investigation_id, thread_id=record.thread_id, status="running", events_url=f"/api/investigations/{record.investigation_id}/events", after=len(record.events))
