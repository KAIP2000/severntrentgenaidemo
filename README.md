# Gemini-Driven Water Operations Harness

A conversational water-operations workspace driven by one reusable Deep Agent. Gemini owns intent recognition, clarification, planning, delegation, tool selection, and synthesis; deterministic tools own synthetic retrieval and arithmetic.

There is no scenario router and no preloaded investigation fallback. A model, schema, or stream failure becomes an observable `run_failed` event.

## Runtime model

```text
session_id
    ├── investigation_id 1 ── thread_id 1
    ├── investigation_id 2 ── thread_id 2
    └── investigation_id 3 ── thread_id 3
```

- A session is the persistent user-facing conversation.
- Every submitted question creates a new investigation, retained SSE event log, and isolated Deep Agent thread.
- Prior completed turns are supplied as context to the new thread.
- Approval resumes the same thread with `Command(resume=...)`.
- One compiled agent and `InMemorySaver` are shared by the process; `thread_id` isolates checkpoints.
- Restarting the backend clears sessions, events, checkpoints, and pending approvals.

## Synthetic network

The seeded dataset is generated relative to an injected, 12-hour-rounded clock. It includes five connected waterways with 60 ordered 12-hour intervals each:

- River Alder — dry-weather decline
- Bracken Beck — stable seasonal flow
- Mereford River — upstream sensor fault
- Highmoor Brook — rainfall surge and recovery
- Wren Channel — maintenance-related abstraction reduction

It also includes five catchments and sources, 15 sensors, weather and soil moisture, three reservoirs, three treatment works, four demand zones, incidents, maintenance, forecasts, operational options, costs, risks, and constraints. Everything is synthetic.

## API

- `POST /api/investigations` with `{question, session_id}` returns `202` and the new IDs plus an SSE URL.
- `GET /api/investigations/{id}/events?after={seq}` replays retained events after the cursor, then streams live events.
- `GET /api/investigations/{id}` returns accumulated state.
- `GET /api/sessions/{session_id}` restores the ordered conversation timeline.
- `POST /api/investigations/{id}/decision` with `{decision: "approve" | "reject"}` resumes its original thread.

## Run

```bash
cp .env.example .env
# Set GOOGLE_API_KEY. Gemini is mandatory for investigations.
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000); API docs are at [http://localhost:8000/docs](http://localhost:8000/docs).

The provider boundary defaults to `google_genai:gemini-3.6-flash`. Future Ollama/local and browser-edge adapters can be added behind `ModelGateway` without changing the agent or tool contracts.

## LangSmith

Set `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, and the endpoint for your LangSmith region. Invalid workspace/key combinations return 403; disable tracing while correcting them. Traces include the execution hierarchy, model calls, tools, and timings, but the product never exposes hidden chain-of-thought.

## Verification

```bash
cd backend && ../.venv/bin/pytest -q
cd frontend && npm run lint && npm run build
```
