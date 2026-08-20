from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agents import WaterOperationsHarness
from app.config import get_settings
from app.data import ENVIRONMENT
from app.schemas import DecisionAccepted, DecisionRequest, InvestigationCreated, InvestigationRequest, InvestigationView, SessionView

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.2.0")
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
