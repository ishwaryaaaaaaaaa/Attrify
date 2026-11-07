import { useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { Example, FunctionCard } from "../types";
import { fmt } from "../util";

const STATUS_LABEL = { pending: "Pending", accepted: "Accepted", rejected: "Rejected", refined: "Refined" } as const;

export function FunctionCardView({ card, cards }: { card: FunctionCard; cards: FunctionCard[] }) {
  const review = useStore((s) => s.review);
  const revisit = useStore((s) => s.revisit);
  const select = useStore((s) => s.select);
  const working = useStore((s) => !!s.working);
  const lift = useStore((s) => s.sel.hoverCardId === card.id);
  const flash = useStore((s) => s.sel.flashCardId === card.id);
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState(false);
  const [refining, setRefining] = useState(false);
  const [note, setNote] = useState("");
  const [menu, setMenu] = useState(false);
  const [armed, setArmed] = useState(false);       // "Accept anyway" needs a second click
  const [more, setMore] = useState<Example[]>([]);
  const examples = [...card.examples, ...more];

  const pending = card.status === "pending";
  const constant = card.sameShare !== null && card.sameShare >= 0.999;
  const heavy = card.sameShare !== null && card.sameShare > 0.5;
  const replacement = card.supersededBy !== null ? cards.find((c) => c.id === card.supersededBy) : undefined;

  const toggleDetails = () => {
    if (!open) api.event("details_open", { cardId: card.id });
    setOpen(!open);
  };
  const accept = () => {
    if (constant && !armed) { setArmed(true); return; }
    void review(card.id, "accept", "chat");
  };
  const showMore = async () => {
    api.event("more_examples", { cardId: card.id });
    try {
      const got = await api.examples(card.id, examples.map((e) => e.id));
      setMore([...more, ...got]);
    } catch { /* values are only kept while the session lives */ }
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (!pending || working || (e.target as HTMLElement).tagName === "TEXTAREA" || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === "a") accept();
    else if (k === "r") void review(card.id, "reject", "chat");
    else if (k === "f") setRefining(true);
  };

  return (
    <div
      id={`card-${card.id}`}
      className={`card ${card.status}${lift ? " lift" : ""}${flash ? " flash" : ""}`}
      tabIndex={0}
      role="group"
      aria-label={`${card.name}, ${card.status}. Accept, Refine, Reject.`}
      onKeyDown={onKey}
      onMouseEnter={() => select({ hoverCardId: card.id })}
      onMouseLeave={() => select({ hoverCardId: null })}
    >
      <h4 style={card.status === "refined" ? { color: "var(--muted)" } : undefined}>{card.name}</h4>
      <span className={`badge-status ${card.status}`}>{STATUS_LABEL[card.status]}</span>
      <button
        className="circle"
        aria-label={`Change decision for ${card.name}`}
        disabled={pending || card.status === "refined"}
        onClick={() => setMenu(!menu)}
      />
      {menu && (
        <div className="menu" style={{ top: 28, right: 4, minWidth: 130 }}>
          {card.status !== "accepted" && <button onClick={() => { setMenu(false); void revisit(card.id, "accept", "circle"); }}>Accepted</button>}
          {card.status !== "rejected" && <button onClick={() => { setMenu(false); void revisit(card.id, "reject", "circle"); }}>Rejected</button>}
        </div>
      )}
      <div className="desc">{card.description}</div>

      {card.status === "refined" && (
        <div className="hint" style={{ marginTop: 4 }}>
          {card.refineNote && <div>You asked: “{card.refineNote}”</div>}
          {replacement ? (
            <button className="link" onClick={() => { select({ flashCardId: replacement.id }); document.getElementById(`card-${replacement.id}`)?.scrollIntoView({ block: "center", behavior: "smooth" }); }}>
              → replaced by new card
            </button>
          ) : <span>→ replaced by new card</span>}
        </div>
      )}
      {card.similarTo && <div className="hint" style={{ marginTop: 4 }}>Looks similar to: {card.similarTo}</div>}
      {constant && <div className="warn-line red">Every essay gets the same value.</div>}
      {!constant && heavy && <div className="warn-line">Same value on {Math.round((card.sameShare ?? 0) * 100)}% of essays. It may not separate much.</div>}
      {card.warnings.map((w) => <div key={w} className="warn-line">{w}</div>)}

      {(
        <div className="row">
          {pending && (
            <>
              <button className="btn accept" title="This matches what I care about. (It does not prove the measurement is right.)" disabled={working} onClick={accept}>
                {armed ? "Accept anyway" : "Accept"}
              </button>
              <button className="btn refine" title="Close, but change it." disabled={working} onClick={() => setRefining(!refining)}>Refine</button>
              <button className="btn reject" title="This is not what I mean." disabled={working} onClick={() => void review(card.id, "reject", "chat")}>Reject</button>
            </>
          )}
          <button className="link" aria-expanded={open} onClick={toggleDetails}>{open ? "Hide details" : "Details"}</button>
        </div>
      )}

      {refining && pending && (
        <div className="refine-box">
          <div style={{ fontWeight: 600, color: "var(--refined)", fontSize: 12 }}>What should be different?</div>
          <textarea rows={2} value={note} placeholder="e.g. “Only look at the last sentence of the intro”" onChange={(e) => setNote(e.target.value)} autoFocus />
          <div style={{ textAlign: "right" }}>
            <button className="btn primary" disabled={!note.trim() || working} onClick={() => { setRefining(false); void review(card.id, "refine", "chat", note.trim()); }}>Send refinement</button>
          </div>
        </div>
      )}

      {open && (
        <div className="details">
          <h5>How it works</h5>
          <ol>{card.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
          <div style={{ margin: "6px 0" }}><span className="tag">Type: {card.methodType}</span></div>
          {examples.length > 0 && <h5>Sample values on {examples.length} essays</h5>}
          {examples.map((e) => (
            <div key={e.id} className="sample">
              <span className="mono hint">#{e.id}</span><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>“{e.excerpt}”</span><span className="v">{fmt(e.value).replace(/\.?0+$/, "") || "0"}</span>
            </div>
          ))}
          {card.sameShare !== null && <button className="link" style={{ margin: "4px 0" }} onClick={() => void showMore()}>Show me 3 more essays</button>}
          <div><button className="link" onClick={() => setCode(!code)}>{code ? "Hide code" : "View code"}</button></div>
          {code && <pre>{card.code}</pre>}
        </div>
      )}
    </div>
  );
}
