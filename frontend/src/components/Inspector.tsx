import { ChevronDown, ChevronRight, Download } from "lucide-react";
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../store";
import { TraceStep, VizBlock } from "../types";
import { exportTrace } from "../util";
import { PanelFrame } from "./PanelFrame";

const AGENT_CLASS: Record<string, string> = {
  You: "you", System: "system", "Softness Agent": "softness", Policy: "policy", "Function Agent": "function",
  "Attribute Table": "table", "Coverage Graph": "graph", "Question Agent": "question", "Baseline Chat": "baseline",
};
const agentClass = (a: string) => "ag-" + (AGENT_CLASS[a] ?? "system");
const KIND_LABEL: Record<TraceStep["kind"], string> = {
  llm: "LLM call", compute: "Computation", sandbox: "Code run", decision: "Decision", io: "Input / output",
};
const fmtMs = (ms: number | null) => (ms == null ? "" : ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);
const humanize = (k: string) => k.replace(/_/g, " ");

// ---------- generic value viewer ----------
function Val({ v, depth = 0 }: { v: unknown; depth?: number }): ReactNode {
  if (v === null || v === undefined) return <span className="muted">none</span>;
  if (typeof v === "boolean") return <span className="mono">{String(v)}</span>;
  if (typeof v === "number") return <span className="mono">{v}</span>;
  if (typeof v === "string") {
    return v.includes("\n") || v.length > 110 ? <pre className="ins-pre">{v}</pre> : <span>{v}</span>;
  }
  if (Array.isArray(v)) {
    if (!v.length) return <span className="muted">empty</span>;
    if (v.every((x) => typeof x === "number")) {
      const shown = v.slice(0, 40).join(", ");
      return <span className="mono">[{shown}{v.length > 40 ? ` … (${v.length} values)` : ""}]</span>;
    }
    if (v.every((x) => typeof x === "string" && x.length < 70)) {
      return <span className="chips">{v.map((x, i) => <span key={i} className="mini-chip">{x as string}</span>)}</span>;
    }
    return <ol className="ins-list">{v.map((x, i) => <li key={i}><Val v={x} depth={depth + 1} /></li>)}</ol>;
  }
  if (typeof v === "object") return <KV obj={v as Record<string, unknown>} depth={depth + 1} />;
  return <span>{String(v)}</span>;
}

function KV({ obj, depth = 0 }: { obj: Record<string, unknown>; depth?: number }) {
  const entries = Object.entries(obj);
  if (!entries.length) return null;
  return (
    <dl className={`kv${depth > 1 ? " nested" : ""}`}>
      {entries.map(([k, v]) => (
        <div key={k} className="kv-row">
          <dt>{humanize(k)}</dt>
          <dd><Val v={v} depth={depth} /></dd>
        </div>
      ))}
    </dl>
  );
}

// ---------- pictures ----------
function Matrix({ b }: { b: Extract<VizBlock, { type: "matrix" }> }) {
  const n = b.values.length;
  return (
    <div className="viz">
      {b.title && <div className="viz-title">{b.title}</div>}
      <div className="matrix" style={{ gridTemplateColumns: `22px repeat(${n}, minmax(26px, 1fr))` }} role="table" aria-label={b.title}>
        <span />
        {b.labels.map((_, j) => <span key={j} className="mx-h">{j + 1}</span>)}
        {b.values.map((row, i) => (
          <div key={i} style={{ display: "contents" }}>
            <span className="mx-h">{i + 1}</span>
            {row.map((v, j) => (
              <span key={j} className="mx-c" title={`${b.labels[i]}  ↔  ${b.labels[j]}: ${v}`}
                style={{ background: `rgba(42,93,176,${Math.min(1, Math.max(0, v))})`, color: v > 0.5 ? "#fff" : "var(--ink)" }}>
                {v.toFixed(2).replace(/^0/, "")}
              </span>
            ))}
          </div>
        ))}
      </div>
      <ol className="mx-legend">{b.labels.map((l, i) => <li key={i} value={i + 1}>{l}</li>)}</ol>
    </div>
  );
}

function Bars({ b }: { b: Extract<VizBlock, { type: "bars" }> }) {
  const max = Math.max(...b.values, 1e-9);
  return (
    <div className="viz">
      {b.title && <div className="viz-title">{b.title}</div>}
      <div className="bars">
        {b.values.map((v, i) => (
          <div key={i} className="bar" title={`${b.labels[i]}: ${v}`}>
            <span className="bar-v mono">{v}</span>
            <span className="bar-fill" style={{ height: `${Math.max(2, (v / max) * 70)}px` }} />
            <span className="bar-l">{b.labels[i]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Viz({ b }: { b: VizBlock }) {
  switch (b.type) {
    case "readings":
      return (
        <div className="viz">
          <div className="viz-title">The {b.items.length} readings (label → full description)</div>
          <ol className="readings">
            {b.items.map((r, i) => (
              <li key={i}><b>{r.label}</b><span className="muted"> — {r.description}</span></li>
            ))}
          </ol>
        </div>
      );
    case "matrix": return <Matrix b={b} />;
    case "bars": return <Bars b={b} />;
    case "code":
      return <div className="viz">{b.title && <div className="viz-title">{b.title}</div>}<pre className="ins-pre code">{b.code}</pre></div>;
    case "formula":
      return <pre className="ins-pre formula">{b.lines.join("\n")}</pre>;
    case "table":
      return (
        <div className="viz">
          {b.title && <div className="viz-title">{b.title}</div>}
          <table className="ins-table">
            <thead><tr>{b.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>{b.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={typeof c === "number" ? "mono" : ""}>{c}</td>)}</tr>)}</tbody>
          </table>
        </div>
      );
  }
}

// ---------- one step ----------
function summary(s: TraceStep): string {
  const src = Object.keys(s.outputs).length ? s.outputs : s.inputs;
  const parts: string[] = [];
  for (const [k, v] of Object.entries(src)) {
    if (parts.length >= 3) break;
    if (typeof v === "number" || typeof v === "boolean") parts.push(`${humanize(k)} ${v}`);
    else if (typeof v === "string" && v.length <= 70 && !v.includes("\n")) parts.push(`${humanize(k)}: ${v}`);
  }
  return parts.join("  ·  ");
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <div className="ins-sec"><div className="ins-sec-h">{title}</div>{children}</div>;
}

function StepCard({ s, open, toggle, n }: { s: TraceStep; open: boolean; toggle: () => void; n: number }) {
  const hasIn = Object.keys(s.inputs).length > 0;
  const hasOut = Object.keys(s.outputs).length > 0;
  return (
    <article id={`step-${s.id}`} className={`step ${agentClass(s.agent)}${open ? " open" : ""}${s.status !== "ok" ? " " + s.status : ""}`}>
      <button className="step-head" onClick={toggle} aria-expanded={open}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span className="step-n mono">{n}</span>
        <span className={`agent-chip ${agentClass(s.agent)}`}>{s.agent}</span>
        <span className="step-title">{s.step}</span>
        <span className="step-kind">{KIND_LABEL[s.kind]}</span>
        {s.status !== "ok" && <span className={`step-status ${s.status}`}>{s.status === "retry" ? "retried / sent back" : "error"}</span>}
        <span className="step-ms mono">{fmtMs(s.ms)}</span>
      </button>
      {!open && summary(s) && <div className="step-sum">{summary(s)}</div>}
      {open && (
        <div className="step-body">
          {s.note && <p className="step-note">{s.note}</p>}
          {s.llm && (
            <Section title={`Sent to the model — ${s.llm.model}, temperature ${s.llm.temperature}`}>
              {s.llm.system && (
                <details className="ins-details">
                  <summary>System prompt ({s.llm.system.length} characters)</summary>
                  <pre className="ins-pre">{s.llm.system}</pre>
                </details>
              )}
              <div className="viz-title">{s.llm.system ? "User message" : "Prompt (one message, no system prompt)"}</div>
              <pre className="ins-pre">{s.llm.user}</pre>
            </Section>
          )}
          {s.llm && (
            <Section title="Raw answer from the model">
              {s.llm.response == null ? <span className="muted">No answer (the call failed).</span> : <pre className="ins-pre">{s.llm.response}</pre>}
            </Section>
          )}
          {hasIn && <Section title="Input"><KV obj={s.inputs} /></Section>}
          {hasOut && <Section title={s.llm ? "What the program kept (parsed)" : "Output"}><KV obj={s.outputs} /></Section>}
          {s.viz.map((b, i) => <Viz key={i} b={b} />)}
        </div>
      )}
    </article>
  );
}

// ---------- overview strip ----------
interface Group { agent: string; first: number; count: number; ms: number; detail: string }

function groupSteps(steps: TraceStep[]): Group[] {
  const out: Group[] = [];
  for (const s of steps) {
    const last = out[out.length - 1];
    let detail = "";
    if (typeof s.outputs.softness === "number") detail = `softness ${s.outputs.softness}`;
    if (s.agent === "Policy" && typeof s.outputs.action === "string") detail = s.outputs.action.replace(/_/g, " ");
    if (s.agent === "You" && s.step.startsWith("Review")) detail = s.step.replace("Review: ", "").split(" “")[0];
    const sideCheck = s.agent === "Attribute Table" && /^(Preview|Similar-name)/.test(s.step);   // part of the Function Agent's stage
    if (last && sideCheck) {
      last.count += 1;
      last.ms += s.ms ?? 0;
    } else if (last && last.agent === s.agent && s.agent !== "You") {
      last.count += 1;
      last.ms += s.ms ?? 0;
      if (detail) last.detail = detail;
    } else {
      out.push({ agent: s.agent, first: s.id, count: 1, ms: s.ms ?? 0, detail });
    }
  }
  return out;
}

function Flow({ steps, onPick }: { steps: TraceStep[]; onPick: (id: number) => void }) {
  const groups = useMemo(() => groupSteps(steps), [steps]);
  if (!groups.length) return null;
  return (
    <nav className="flow" aria-label="Order of the steps">
      {groups.map((g, i) => (
        <div key={g.first} style={{ display: "contents" }}>
          {i > 0 && <span className="flow-arrow" aria-hidden>→</span>}
          <button className={`flow-chip ${agentClass(g.agent)}`} onClick={() => onPick(g.first)}>
            <b>{g.agent}</b>
            <span>{g.count} step{g.count > 1 ? "s" : ""}{g.ms ? ` · ${fmtMs(g.ms)}` : ""}</span>
            {g.detail && <i>{g.detail}</i>}
          </button>
        </div>
      ))}
    </nav>
  );
}

// ---------- panel ----------
export function InspectorPanel() {
  const trace = useStore((s) => s.trace);
  const server = useStore((s) => s.server);
  const working = useStore((s) => s.working);
  const insp = useStore((s) => s.inspector);
  const setInsp = useStore((s) => s.setInspector);
  const toast = useStore((s) => s.showToast);
  const [userOpen, setUserOpen] = useState<Map<number, boolean>>(new Map());
  // steps that carry the readings, matrices, numbers or code start open; the user can fold them
  const isOpen = (s: TraceStep) => userOpen.get(s.id) ?? (s.viz?.length ? true : false);
  const listRef = useRef<HTMLDivElement>(null);

  const turnsPresent = useMemo(() => [...new Set(trace.map((s) => s.turn))].sort((a, b) => a - b), [trace]);
  const visible = useMemo(() => (insp.turn === "all" ? trace : trace.filter((s) => s.turn === insp.turn)), [trace, insp.turn]);

  const toggle = (s: TraceStep) => setUserOpen((p) => new Map(p).set(s.id, !isOpen(s)));
  const reveal = (id: number) => {
    setUserOpen((p) => new Map(p).set(id, true));
    window.setTimeout(() => document.getElementById(`step-${id}`)?.scrollIntoView({ block: "start", behavior: "smooth" }), 30);
  };

  // follow the newest step while the backend is working
  useEffect(() => {
    if (insp.follow && working) listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [trace.length, insp.follow, working]);
  // jump to a step requested from elsewhere (for example the chat)
  useEffect(() => {
    if (insp.focusStep !== null) { reveal(insp.focusStep); setInsp({ focusStep: null }); }
  }, [insp.focusStep]); // eslint-disable-line react-hooks/exhaustive-deps

  const turnLabel = (t: number) => {
    if (t < 0) return "Session start";
    const tr = server?.turns[t];
    const snippet = tr?.answer ? ` — “${tr.answer.slice(0, 48)}${tr.answer.length > 48 ? "…" : ""}”` : "";
    return `Turn ${t + 1}${snippet}`;
  };

  let counter = 0;
  let lastTurn: number | null = null;
  return (
    <PanelFrame letter="P" title="Pipeline Inspector" scroll={false}>
      <div className="inspector">
        <div className="ins-bar">
          <label>Show{" "}
            <select value={String(insp.turn)} onChange={(e) => setInsp({ turn: e.target.value === "all" ? "all" : Number(e.target.value) })}>
              <option value="all">Whole session ({trace.length} steps)</option>
              {turnsPresent.map((t) => <option key={t} value={t}>{turnLabel(t)}</option>)}
            </select>
          </label>
          <button className="btn-outline" onClick={() => setUserOpen(new Map(visible.map((s) => [s.id, true] as [number, boolean])))}>Expand all</button>
          <button className="btn-outline" onClick={() => setUserOpen(new Map(visible.map((s) => [s.id, false] as [number, boolean])))}>Collapse all</button>
          <label className="follow"><input type="checkbox" checked={insp.follow} onChange={(e) => setInsp({ follow: e.target.checked })} /> Follow live</label>
          <button className="btn-outline" onClick={() => toast(exportTrace(trace))} disabled={!trace.length}><Download size={12} /> Export JSON</button>
        </div>
        <Flow steps={visible} onPick={reveal} />
        <div className="ins-list-wrap" ref={listRef}>
          {!trace.length && (
            <p className="muted ins-empty">
              Nothing recorded yet. Answer a question in the chat and every step appears here: your answer, the model calls
              with their exact prompts and answers, the softness maths, the generated code and the table and graph updates.
            </p>
          )}
          {visible.map((s) => {
            counter += 1;
            const header = insp.turn === "all" && s.turn !== lastTurn ? (lastTurn = s.turn, <h3 className="turn-h" key={`h${s.id}`}>{turnLabel(s.turn)}</h3>) : null;
            return (
              <div key={s.id} style={{ display: "contents" }}>
                {header}
                <StepCard s={s} n={counter} open={isOpen(s)} toggle={() => toggle(s)} />
              </div>
            );
          })}
          {working && <div className="ins-live"><span className="dots"><i /><i /><i /></span> {working.stage}</div>}
        </div>
      </div>
    </PanelFrame>
  );
}
