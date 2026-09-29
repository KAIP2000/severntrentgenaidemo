export type Calculation = { label: string; formula: string; inputs: Record<string, unknown>; result: unknown; unit?: string | null };
export type Evidence = {
  id: string; title: string; source: string; period: Record<string, unknown>; query: Record<string, unknown>;
  summary: string; records: Record<string, unknown>[]; calculations: Calculation[]; provenance: Record<string, unknown>;
};
export type Activity = {
  id: string; parent_id?: string | null; agent: string; kind: "model" | "tool" | "subagent" | "plan" | "approval";
  label: string; status: "active" | "complete" | "failed"; started_at: string; completed_at?: string | null;
  duration_ms?: number | null; tool?: { name: string; inputs: Record<string, unknown>; output?: unknown } | null;
  result_summary?: string | null; evidence: Evidence[]; calculations: Calculation[]; usage?: Record<string, number>; error?: string | null;
};
export type Recommendation = { id: string; action: string; rationale: string; expected_impact_ml_day?: number | null; risk?: string | null };
export type ChartSpec = { type: "line" | "bar"; title: string; evidence_id: string; x_field: string; y_fields: string[] };
export type AgentFinal = {
  status: "complete" | "clarification_required"; disposition: "conclusion" | "insufficient_evidence" | "conflicting_evidence" | "no_action_required"; title: string; answer_markdown: string; scope: Record<string, unknown>;
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

export type EvaluationCheck = { key: string; score: number; passed: boolean; mandatory: boolean; comment: string };
export type EvaluationJudge = { key: string; score: number; passed: boolean; rationale: string; strengths: string[]; weaknesses: string[]; critical_failure: boolean; critical_failure_code?: string | null };
export type EvaluationScenario = {
  scenario_id: string; split: string; result: "PASS" | "PARTIAL" | "FAIL"; harness_success: boolean;
  investigation_success?: boolean | null; checks: EvaluationCheck[]; judges: EvaluationJudge[];
  metrics: Record<string, number>; record: { status: string; question: string; duration_ms: number; tool_calls: number; model_calls: number; total_tokens: number; error?: string | null };
};
export type EvaluationReport = {
  corpus_version: string; rubric_version: string; generated_at: string; experiment_name?: string | null;
  model_name: string; judge_model_name: string; summary: Record<string, number>; scenarios: EvaluationScenario[];
};
export type EvaluationRuntimeStatus = {
  status: "idle" | "running" | "complete" | "failed" | "cancelled" | "disabled" | "skipped";
  started_at?: string | null; completed_at?: string | null; experiment_url?: string | null;
  scenario_count: number; error?: string | null;
};
