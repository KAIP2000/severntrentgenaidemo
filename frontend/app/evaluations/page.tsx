"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, CheckCircle, Clock, Flask, Gauge, ShieldCheck, WarningCircle, XCircle } from "@phosphor-icons/react";
import { getEvaluationStatus, getLatestEvaluation } from "@/lib/api";
import type { EvaluationReport, EvaluationRuntimeStatus } from "@/lib/types";
import styles from "./evaluations.module.css";

const labels: Record<string, string> = {
  capability_selection: "Capability selection", tool_relevance: "Tool relevance", evidence_sufficiency: "Evidence sufficiency",
  grounding: "Grounding", calculation_accuracy: "Calculation accuracy", recommendation_quality: "Recommendation quality",
  hitl_safety: "HITL safety", failure_handling: "Failure handling", correct_abstention: "Correct abstention",
  trajectory_proportionality: "Trajectory proportionality",
};

function pct(value?: number) { return value == null ? "—" : `${Math.round(value * 100)}%`; }

export default function EvaluationsPage() {
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [runtime, setRuntime] = useState<EvaluationRuntimeStatus | null>(null);

  useEffect(() => {
    let mounted = true;
    async function refresh() {
      try {
        const [latest, status] = await Promise.all([getLatestEvaluation(), getEvaluationStatus()]);
        if (mounted) { setReport(latest); setRuntime(status); setError(""); }
      } catch (cause) {
        if (mounted) setError(cause instanceof Error ? cause.message : "Could not load evaluations.");
      } finally { if (mounted) setLoading(false); }
    }
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => { mounted = false; window.clearInterval(timer); };
  }, []);

  const counts = useMemo(() => report?.scenarios.reduce((acc, item) => ({ ...acc, [item.result]: acc[item.result] + 1 }), { PASS: 0, PARTIAL: 0, FAIL: 0 }) ?? { PASS: 0, PARTIAL: 0, FAIL: 0 }, [report]);
  const componentMetrics = report ? Object.entries(labels).filter(([key]) => report.summary[key] != null) : [];

  return <main className={styles.page}>
    <header className={styles.topbar}><Link href="/"><ArrowLeft/> Investigations</Link><div><b>SVTR</b> <span>INTELLIGENCE · HARNESS EVALUATION</span></div><span className={styles.environment}>Synthetic Midlands Network</span></header>
    <section className={styles.content}>
      <div className={styles.hero}><span><Flask weight="fill"/> AGENTIC SYSTEM ASSURANCE</span><h1>Harness evaluation,<br/><em>without averages hiding risk.</em></h1><p>Deterministic checks gate safety and arithmetic. Gemini critics assess trajectory, evidence, and recommendations. Critical failures always override scores.</p></div>
      {runtime && <div className={`${styles.runtime} ${styles[runtime.status]}`}><Clock/><div><strong>{runtime.status === "running" ? "Startup evaluation is running" : `Startup evaluation ${runtime.status}`}</strong><span>{runtime.status === "running" ? "The report refreshes automatically as soon as the experiment completes." : runtime.error ?? `${runtime.scenario_count} scenarios evaluated.`}</span></div>{runtime.experiment_url && <a href={runtime.experiment_url} target="_blank" rel="noreferrer">Open LangSmith</a>}</div>}
      {loading && <div className={styles.empty}>Loading the latest evaluation report…</div>}
      {error && <div className={styles.error}><WarningCircle/>{error}</div>}
      {!loading && !error && !report && <div className={styles.empty}><Flask/><h2>{runtime?.status === "running" ? "First evaluation in progress" : "No evaluation report yet"}</h2><p>{runtime?.status === "running" ? "This page will update automatically when the startup experiment finishes." : "Start the backend with live model and LangSmith credentials to execute the corpus."}</p></div>}
      {report && <>
        <section className={styles.primaryGrid}>
          <article className={styles.primary}><div><Gauge/><span>PRIMARY METRIC</span></div><strong>{pct(report.summary.investigation_success_rate)}</strong><h2>Investigation Success</h2><p>Only complete PASS results count. Partial investigations remain unsuccessful.</p></article>
          <article className={styles.primary}><div><ShieldCheck/><span>EXECUTION METRIC</span></div><strong>{pct(report.summary.harness_success_rate)}</strong><h2>Harness Success</h2><p>Trace, state transitions, failure visibility, and approval behavior.</p></article>
          <article className={styles.runMeta}><span>LATEST EXPERIMENT</span><h3>{report.experiment_name ?? "Local evaluation"}</h3><dl><div><dt>Application</dt><dd>{report.model_name}</dd></div><div><dt>Judge</dt><dd>{report.judge_model_name}</dd></div><div><dt>Corpus</dt><dd>v{report.corpus_version}</dd></div><div><dt>Generated</dt><dd>{new Date(report.generated_at).toLocaleString()}</dd></div></dl></article>
        </section>
        <section className={styles.section}><header><div><span>COMPONENT METRICS</span><h2>Where the harness succeeds—and where it wanders</h2></div><div className={styles.counts}><b className={styles.pass}>{counts.PASS} pass</b><b className={styles.partial}>{counts.PARTIAL} partial</b><b className={styles.fail}>{counts.FAIL} fail</b></div></header>
          <div className={styles.metricGrid}>{componentMetrics.map(([key, label]) => <article key={key}><div><span>{label}</span><b>{pct(report.summary[key])}</b></div><i><span style={{ width: pct(report.summary[key]) }}/></i></article>)}</div>
        </section>
        <section className={styles.section}><header><div><span>SCENARIO RESULTS</span><h2>Behavioral, adversarial, and reliability coverage</h2></div><p>{report.scenarios.length} evaluated runs</p></header>
          <div className={styles.scenarios}>{report.scenarios.map(item => <details key={item.scenario_id} className={styles.scenario}><summary><span className={`${styles.badge} ${styles[item.result.toLowerCase()]}`}>{item.result === "PASS" ? <CheckCircle/> : item.result === "FAIL" ? <XCircle/> : <WarningCircle/>}{item.result}</span><div><b>{item.scenario_id}</b><p>{item.record.question}</p></div><span className={styles.split}>{item.split}</span><div className={styles.efficiency}><span><Clock/>{item.record.duration_ms}ms</span><span>{item.record.tool_calls} tools</span><span>{item.record.model_calls} models</span></div></summary><div className={styles.detail}>
              {item.record.error && <div className={styles.error}><WarningCircle/>{item.record.error}</div>}
              <div><h3>Deterministic checks</h3>{item.checks.map(check => <div className={styles.check} key={check.key}><span>{check.passed ? <CheckCircle/> : <XCircle/>}{check.key.replaceAll("_", " ")}</span><b>{pct(check.score)}</b><p>{check.comment}</p></div>)}</div>
              <div><h3>Qualitative judges</h3>{item.judges.length ? item.judges.map(judge => <div className={styles.check} key={judge.key}><span>{judge.passed ? <CheckCircle/> : <XCircle/>}{judge.key}</span><b>{pct(judge.score)}</b><p>{judge.rationale}</p>{judge.critical_failure && <em>Critical: {judge.critical_failure_code}</em>}</div>) : <p className={styles.muted}>No qualitative judge applies to this reliability scenario.</p>}</div>
            </div></details>)}</div>
        </section>
      </>}
    </section>
  </main>;
}
