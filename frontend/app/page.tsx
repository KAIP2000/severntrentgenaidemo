"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ActivityIcon, ArrowRight, Bell, Brain, CaretDown, ChartLineUp, Check, ClockCounterClockwise,
  Database, Drop, FlowArrow, Gauge, House, MapTrifold, PaperPlaneTilt, ShieldCheck, Sparkle,
  SpinnerGap, Warning, Waves, X,
} from "@phosphor-icons/react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { decide, getSession, startInvestigation, streamInvestigation } from "@/lib/api";
import type { Activity, ChartSpec, Evidence, Investigation, StreamEvent } from "@/lib/types";

const prompts = [
  "What can you do?",
  "Compare all five rivers over the last seven days.",
  "Show River Alder flow for the last couple days.",
  "Which sensors are currently degraded?",
];

function emptyRun(created: { session_id: string; investigation_id: string; thread_id: string }, question: string): Investigation {
  const now = new Date().toISOString();
  return { ...created, question, status: "queued", created_at: now, updated_at: now, model_provider: "google_genai", model_name: "Gemini", plan: [], activities: [], evidence: [], last_sequence: 0 };
}

function mergeEvent(run: Investigation, event: StreamEvent): Investigation {
  const next = { ...run, updated_at: event.timestamp, last_sequence: event.seq };
  if (event.type === "run_started") next.status = "running";
  if (event.type === "plan_updated") next.plan = event.data.plan as Array<Record<string, unknown>>;
  if (event.type === "activity_started" || event.type === "activity_completed") {
    const activity = event.data.activity as Activity;
    next.activities = [...run.activities.filter(item => item.id !== activity.id), activity];
    const gathered = next.activities.flatMap(item => item.evidence ?? []);
    next.evidence = Array.from(new Map(gathered.map(item => [item.id, item])).values());
  }
  if (event.type === "approval_required") next.status = "awaiting_approval";
  if (event.type === "run_failed") { next.status = "failed"; next.error = String(event.data.error ?? "The Gemini run failed."); }
  if (event.type === "run_completed" || event.type === "clarification_required") {
    next.final = event.data.result as Investigation["final"];
    next.status = event.type === "clarification_required" ? "clarification_required" : "complete";
  }
  return next;
}

function Status({ status }: { status: Investigation["status"] }) {
  return <span className={`status ${status}`}><i />{status.replaceAll("_", " ")}</span>;
}

function EvidenceChart({ spec, evidence }: { spec: ChartSpec; evidence?: Evidence }) {
  if (!evidence?.records.length) return null;
  const colors = ["#005c93", "#00a3c7", "#65c7d8"];
  const lines = spec.y_fields.map((field, index) => <Line key={field} type="monotone" dataKey={field} stroke={colors[index % colors.length]} strokeWidth={2.5} dot={false} />);
  return <section className="chartCard"><h3>{spec.title}</h3><div className="chartArea"><ResponsiveContainer width="100%" height="100%">{spec.type === "bar" ? <BarChart data={evidence.records}><CartesianGrid stroke="#d7e4ec" vertical={false}/><XAxis dataKey={spec.x_field}/><YAxis/><Tooltip/><Legend/>{spec.y_fields.map((field, index) => <Bar key={field} dataKey={field} fill={colors[index % colors.length]} />)}</BarChart> : <LineChart data={evidence.records}><CartesianGrid stroke="#d7e4ec" vertical={false}/><XAxis dataKey={spec.x_field} tickFormatter={value => String(value).slice(5, 16)}/><YAxis/><Tooltip/><Legend/>{lines}</LineChart>}</ResponsiveContainer></div></section>;
}

function ActivityRow({ activity }: { activity: Activity }) {
  return <details className="activityRow"><summary><span className={`activityMark ${activity.status}`}>{activity.status === "active" ? <SpinnerGap className="spin"/> : <Check/>}</span><div><small>{activity.agent} · {activity.duration_ms != null ? `${activity.duration_ms}ms` : "running"}</small><strong>{activity.tool?.name ?? activity.label}</strong><p>{activity.result_summary ?? activity.label}</p></div><CaretDown className="chevron"/></summary><div className="activityBody"><div className="interactionGrid"><div><label>TOOL INPUTS</label><pre>{JSON.stringify(activity.tool?.inputs ?? {}, null, 2)}</pre></div><div><label>RESULT</label><pre>{JSON.stringify(activity.tool?.output ?? activity.result_summary ?? {}, null, 2)}</pre></div></div><div className="calculationBlock"><label>CALCULATIONS</label>{activity.calculations.length ? activity.calculations.map(calc => <div className="calculation" key={calc.label}><strong>{calc.label}</strong><code>{calc.formula}</code><span>{JSON.stringify(calc.inputs)} → <b>{String(calc.result)} {calc.unit ?? ""}</b></span></div>) : <p>No calculation required for this activity.</p>}</div>{activity.evidence.map(item => <div className="attachedEvidence" key={item.id}><Database/><div className="evidenceOverview"><strong>{item.source}</strong><p>{item.summary}</p><small>{item.id}</small></div><div className="evidenceDetails"><div><label>QUERY PERIOD</label><pre>{JSON.stringify(item.period, null, 2)}</pre></div><div><label>RETURNED RECORDS</label><pre>{JSON.stringify(item.records, null, 2)}</pre></div><div><label>PROVENANCE</label><pre>{JSON.stringify(item.provenance, null, 2)}</pre></div></div></div>)}</div></details>;
}

function Turn({ run, onDecision }: { run: Investigation; onDecision: (run: Investigation, value: "approve" | "reject") => void }) {
  const [activityOpen, setActivityOpen] = useState(run.status === "running");
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  return <article className="turn"><header className="turnHeader"><div><span className="turnLabel"><Sparkle weight="fill"/> INVESTIGATION {run.investigation_id}</span><h2>{run.question}</h2><small>Session {run.session_id.slice(0, 8)} · Thread {run.thread_id.slice(0, 12)}</small></div><Status status={run.status}/></header>
    {run.plan.length > 0 && <section className="plan"><h3><FlowArrow/> Gemini plan</h3><div>{run.plan.map((step, index) => <span key={index}><i>{index + 1}</i>{String(step.content ?? step.task ?? JSON.stringify(step))}</span>)}</div></section>}
    <section className="activityPanel"><button className="sectionToggle" onClick={() => setActivityOpen(!activityOpen)}><span><ActivityIcon/> Agent activity <b>{run.activities.length}</b></span><span>{activityOpen ? "Collapse all" : "Expand all"}<CaretDown className={activityOpen ? "up" : ""}/></span></button>{activityOpen && <div className="activityList">{run.activities.length ? run.activities.map(activity => <ActivityRow activity={activity} key={activity.id}/>) : <div className="waiting"><SpinnerGap className="spin"/> Waiting for Gemini activity…</div>}</div>}</section>
    {run.status === "failed" && <div className="failure"><Warning weight="fill"/><div><strong>Gemini execution failed</strong><p>{run.error}</p></div></div>}
    {run.final && <section className="answer"><div className="answerIcon"><Brain weight="duotone"/></div><div><span className="turnLabel">GEMINI RESPONSE{run.final.confidence != null ? ` · ${run.final.confidence}% CONFIDENCE` : ""}</span><h2>{run.final.title}</h2><ReactMarkdown remarkPlugins={[remarkGfm]}>{run.final.answer_markdown}</ReactMarkdown>{run.final.confidence_rationale && <small>{run.final.confidence_rationale}</small>}</div></section>}
    {run.final?.charts.map(spec => <EvidenceChart key={`${spec.evidence_id}-${spec.title}`} spec={spec} evidence={run.evidence.find(item => item.id === spec.evidence_id)}/>)}
    {run.status === "awaiting_approval" && <section className="approval"><ShieldCheck weight="fill"/><div><strong>Human approval required</strong><p>Gemini has paused before executing the proposed operational action.</p></div><button className="reject" onClick={() => onDecision(run, "reject")}><X/> Reject</button><button className="approve" onClick={() => onDecision(run, "approve")}><Check/> Approve</button></section>}
    {run.evidence.length > 0 && <section className="evidenceIndex"><button className="sectionToggle" onClick={() => setEvidenceOpen(!evidenceOpen)}><span><Database/> Evidence index <b>{run.evidence.length}</b></span><span>{evidenceOpen ? "Hide" : "Show"}<CaretDown className={evidenceOpen ? "up" : ""}/></span></button>{evidenceOpen && <div className="evidenceGrid">{run.evidence.map(item => <details key={item.id}><summary><strong>{item.source}</strong><span>{item.summary}</span><small>{item.id}</small></summary><div><label>QUERY</label><pre>{JSON.stringify(item.query, null, 2)}</pre><label>RECORDS</label><pre>{JSON.stringify(item.records, null, 2)}</pre><label>PROVENANCE</label><pre>{JSON.stringify(item.provenance, null, 2)}</pre></div></details>)}</div>}</section>}
  </article>;
}

export default function Home() {
  const [sessionId, setSessionId] = useState("");
  const [runs, setRuns] = useState<Investigation[]>([]);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState("");
  const streams = useRef<Map<string, () => void>>(new Map());

  const active = useMemo(() => runs.some(run => run.status === "queued" || run.status === "running"), [runs]);

  useEffect(() => {
    const existing = localStorage.getItem("water-ops-session") ?? crypto.randomUUID();
    localStorage.setItem("water-ops-session", existing);
    getSession(existing).then(restored => {
      setSessionId(existing);
      setRuns(restored);
      restored.filter(run => ["queued", "running"].includes(run.status)).forEach(run => {
        attach(run, `/api/investigations/${run.investigation_id}/events`);
      });
    }).catch(() => { setSessionId(existing); setRuns([]); });
    const openStreams = streams.current;
    return () => openStreams.forEach(close => close());
  }, []);

  function attach(run: Investigation, eventsUrl: string) {
    streams.current.get(run.investigation_id)?.();
    const close = streamInvestigation(eventsUrl, run.last_sequence, event => {
      setRuns(current => current.map(item => item.investigation_id === event.investigation_id ? mergeEvent(item, event) : item));
    }, () => setError("The live activity stream disconnected. Submit a new prompt or refresh to restore the session."));
    streams.current.set(run.investigation_id, close);
  }

  async function submit(text = question) {
    if (!text.trim() || !sessionId) return;
    setError(""); setQuestion("");
    try {
      const created = await startInvestigation(text.trim(), sessionId);
      const run = emptyRun(created, text.trim());
      setRuns(current => [...current, run]);
      attach(run, created.events_url);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not start the investigation."); }
  }

  async function decision(run: Investigation, value: "approve" | "reject") {
    try {
      const response = await decide(run.investigation_id, value);
      const next = { ...run, status: "running" as const, last_sequence: response.after };
      setRuns(current => current.map(item => item.investigation_id === run.investigation_id ? next : item));
      attach(next, response.events_url);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not record the decision."); }
  }

  return <main className="shell"><aside className="rail"><div className="brandmark"><Waves weight="bold"/></div><nav><button className="railButton active"><Sparkle/></button><button className="railButton"><House/></button><button className="railButton"><MapTrifold/></button><Link className="railButton" href="/evaluations" aria-label="Evaluations"><ChartLineUp/></Link><button className="railButton"><ClockCounterClockwise/></button></nav><div className="railBottom"><button className="railButton"><Bell/></button><div className="avatar">KP</div></div></aside>
    <section className="app"><header className="topbar"><div className="wordmark"><b>SVTR</b><span>INTELLIGENCE</span></div><div className="environment"><i/> Synthetic Midlands Network</div><div className="operator"><strong>Kyle Pierre</strong><small>Duty Operations Manager</small></div></header>
      <div className="workspace"><aside className="sidebar"><label>WORKSPACE</label><a><Gauge/>Overview</a><a className="active"><Sparkle/>AI investigations <span>{runs.length}</span></a><Link href="/evaluations"><ChartLineUp/>Evaluations</Link><a><Warning/>Active alerts</a><label>NETWORK</label><a><Waves/>5 Rivers</a><a><Drop/>Supply</a><a><FlowArrow/>Treatment & demand</a><label>TRY ASKING</label>{prompts.map(prompt => <button className="quick" key={prompt} onClick={() => submit(prompt)}>{prompt}<ArrowRight/></button>)}<div className="systemCard"><i/><div><strong>Gemini agent online</strong><small>15 sensors · 60 intervals per river</small></div></div></aside>
        <section className="content"><div className="hero"><span><Sparkle weight="fill"/> GEMINI-DRIVEN OPERATIONS</span><h1>Water operations,<br/><em>investigated live.</em></h1><p>Ask a question and watch Gemini choose the evidence, calculations, tools and specialists it needs.</p></div>
          <div className="timeline">{runs.length === 0 && <div className="empty"><Brain weight="duotone"/><h2>Start a conversation</h2><p>No river is assumed. If your scope is ambiguous, Gemini will ask.</p></div>}{runs.map(run => <Turn run={run} key={run.investigation_id} onDecision={decision}/>)}</div>
          {error && <div className="globalError"><Warning/>{error}<button onClick={() => setError("")}><X/></button></div>}
          <div className="composer"><textarea value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }} placeholder="Ask about a named river, the network, supply, sensors, treatment or operations…"/><div><span><Brain/> Gemini · streamed Deep Agent</span><button onClick={() => submit()} disabled={!question.trim() || active}><PaperPlaneTilt weight="fill"/>Send</button></div></div>
        </section></div></section></main>;
}
