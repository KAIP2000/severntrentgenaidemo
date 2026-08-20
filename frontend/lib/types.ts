export type Calculation = { label: string; formula: string; inputs: Record<string, unknown>; result: unknown; unit?: string | null };
export type Evidence = {
  id: string; title: string; source: string; period: Record<string, unknown>; query: Record<string, unknown>;
  summary: string; records: Record<string, unknown>[]; calculations: Calculation[]; provenance: Record<string, unknown>;
};
export type Activity = {
  id: string; parent_id?: string | null; agent: string; kind: "model" | "tool" | "subagent" | "plan" | "approval";
  label: string; status: "active" | "complete" | "failed"; started_at: string; completed_at?: string | null;
  duration_ms?: number | null; tool?: { name: string; inputs: Record<string, unknown>; output?: unknown } | null;
  result_summary?: string | null; evidence: Evidence[]; calculations: Calculation[]; error?: string | null;
};
export type Recommendation = { id: string; action: string; rationale: string; expected_impact_ml_day?: number | null; risk?: string | null };
export type ChartSpec = { type: "line" | "bar"; title: string; evidence_id: string; x_field: string; y_fields: string[] };
export type AgentFinal = {
  status: "complete" | "clarification_required"; title: string; answer_markdown: string; scope: Record<string, unknown>;
  evidence_ids: string[]; confidence?: number | null; confidence_rationale?: string | null;
  recommendation?: Recommendation | null; charts: ChartSpec[];
};
export type Investigation = {
  session_id: string; investigation_id: string; thread_id: string; question: string;
  status: "queued" | "running" | "clarification_required" | "awaiting_approval" | "complete" | "failed";
  created_at: string; updated_at: string; model_provider: string; model_name: string;
  plan: Array<Record<string, unknown>>; activities: Activity[]; evidence: Evidence[];
  final?: AgentFinal | null; error?: string | null; last_sequence: number;
};
export type StreamEvent = {
  seq: number; session_id: string; investigation_id: string; thread_id: string; timestamp: string;
  type: "run_started" | "plan_updated" | "activity_started" | "activity_completed" | "answer_delta" | "clarification_required" | "approval_required" | "run_completed" | "run_failed";
  data: Record<string, unknown>;
};
export type InvestigationCreated = { session_id: string; investigation_id: string; thread_id: string; events_url: string };

