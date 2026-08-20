import type { Investigation, InvestigationCreated, StreamEvent } from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiError(response: Response, fallback: string): Promise<Error> {
  const payload = await response.json().catch(() => null) as { detail?: string | Array<{ msg?: string; loc?: Array<string | number> }> } | null;
  if (Array.isArray(payload?.detail)) return new Error(payload.detail.map(item => `${item.loc?.at(-1) ?? "request"}: ${item.msg ?? "Invalid value"}`).join(" · "));
  return new Error(typeof payload?.detail === "string" ? payload.detail : fallback);
}

export async function startInvestigation(question: string, sessionId: string): Promise<InvestigationCreated> {
  const response = await fetch(`${API_URL}/api/investigations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, session_id: sessionId }) });
  if (!response.ok) throw await apiError(response, `The assistant request failed (${response.status}).`);
  return response.json();
}

export async function getSession(sessionId: string): Promise<Investigation[]> {
  const response = await fetch(`${API_URL}/api/sessions/${encodeURIComponent(sessionId)}`);
  if (!response.ok) throw await apiError(response, "Could not restore this session.");
  return (await response.json()).investigations;
}

export async function decide(id: string, decision: "approve" | "reject") {
  const response = await fetch(`${API_URL}/api/investigations/${id}/decision`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision }) });
  if (!response.ok) throw await apiError(response, "The decision could not be recorded.");
  return response.json();
}

const EVENT_TYPES = ["run_started", "plan_updated", "activity_started", "activity_completed", "answer_delta", "clarification_required", "approval_required", "run_completed", "run_failed"];

export function streamInvestigation(eventsUrl: string, after: number, onEvent: (event: StreamEvent) => void, onError: () => void): () => void {
  const separator = eventsUrl.includes("?") ? "&" : "?";
  const source = new EventSource(`${API_URL}${eventsUrl}${separator}after=${after}`);
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, raw => {
      const event = JSON.parse((raw as MessageEvent).data) as StreamEvent;
      onEvent(event);
      if (["run_completed", "clarification_required", "run_failed", "approval_required"].includes(event.type)) source.close();
    });
  }
  source.onerror = () => { source.close(); onError(); };
  return () => source.close();
}

