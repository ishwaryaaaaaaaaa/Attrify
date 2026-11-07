import { useEffect, useRef, useState } from "react";
import { allCards, isLocked, useStore } from "../store";
import { FunctionCard } from "../types";
import { QTYPE_LABEL, exportFunctions, exportLog, exportTable, exportTrace } from "../util";
import { FunctionCardView } from "./FunctionCardView";
import { PanelFrame } from "./PanelFrame";

function useNow(active: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

function Header() {
  const server = useStore((s) => s.server);
  const startOver = useStore((s) => s.startOver);
  const toast = useStore((s) => s.showToast);
  const [menu, setMenu] = useState(false);
  const [info, setInfo] = useState(false);
  const inspecting = useStore((s) => s.inspector.open);
  const setInspector = useStore((s) => s.setInspector);
  const run = (f: () => string | Promise<string>) => async () => {
    setMenu(false);
    if (server) toast(await f());
  };
  return (
    <div className="chat-header">
      <button className="btn-outline" aria-haspopup="menu" aria-expanded={menu} onClick={() => { setMenu(!menu); setInfo(false); }}>Session Menu</button>
      <button className={`btn-outline${inspecting ? " on" : ""}`} aria-pressed={inspecting} title="Show every backend step with its inputs and outputs" onClick={() => setInspector({ open: !inspecting })}>Pipeline</button>
      <button className="btn-outline" aria-expanded={info} onClick={() => { setInfo(!info); setMenu(false); }}>Info</button>
      {menu && server && (
        <div className="menu" role="menu">
          <button role="menuitem" onClick={run(() => exportTable(server))}>Export table (CSV)</button>
          <button role="menuitem" onClick={run(() => exportFunctions(server))}>Export functions (.py)</button>
          <button role="menuitem" onClick={run(exportLog)}>Download session log (JSON)</button>
          <button role="menuitem" onClick={run(() => exportTrace(useStore.getState().trace))}>Download pipeline trace (JSON)</button>
          <button role="menuitem" onClick={() => { setMenu(false); startOver(); }}>Start over</button>
        </div>
      )}
      {info && (
        <div className="popover" style={{ top: 34, right: 12, width: 300 }} role="dialog" aria-label="How AttriFy works">
          <h3>How AttriFy works</h3>
          <p style={{ margin: "0 0 6px" }}>I ask one question at a time. The chips say what kind it is:</p>
          <p style={{ margin: "0 0 4px" }}><span className="chip open_ended">Open-ended</span> describe something you care about.</p>
          <p style={{ margin: "0 0 4px" }}><span className="chip clarify">Clarifying</span> I narrow down what you mean.</p>
          <p style={{ margin: "0 0 8px" }}><span className="chip suggest">Suggestion</span> add more, or move on.</p>
          <p style={{ margin: 0 }}><b>Accepting means this is relevant to you, not that it has been verified correct.</b> Check the sample values.</p>
          <p className="hint" style={{ margin: "6px 0 0" }}>A higher softness number is not a failure: more detail often opens new ways to measure.</p>
        </div>
      )}
    </div>
  );
}

function CardGroup({ cards, all }: { cards: FunctionCard[]; all: FunctionCard[] }) {
  const pending = cards.filter((c) => c.status === "pending").length;
  const reviewed = cards.length - pending;
  const [done, setDone] = useState(false);
  const prev = useRef(pending);
  useEffect(() => {
    if (prev.current > 0 && pending === 0) {
      setDone(true);
      const t = setTimeout(() => setDone(false), 2000);
      prev.current = pending;
      return () => clearTimeout(t);
    }
    prev.current = pending;
  }, [pending]);
  return (
    <>
      <div className={`cards${cards.length === 1 ? " one" : ""}`}>
        {cards.map((c) => <FunctionCardView key={c.id} card={c} cards={all} />)}
      </div>
      {pending > 0 && <div className="counter" aria-live="polite">{reviewed} of {cards.length} reviewed</div>}
      {done && <div className="counter done" aria-live="polite">All reviewed</div>}
    </>
  );
}

function StatusLine() {
  const working = useStore((s) => s.working);
  const cancel = useStore((s) => s.cancel);
  const now = useNow(!!working);
  if (!working) return null;
  const slow = now - working.since > 15000;
  return (
    <div className="status-line" role="status">
      <span className="dots"><i /><i /><i /></span>
      <span>{working.stage}</span>
      {slow && !working.cancelled && (
        <span>
          Still working. This can take a moment.{" "}
          {working.kind === "answer" && <button className="link" onClick={() => void cancel()}>Cancel</button>}
        </span>
      )}
    </div>
  );
}

function Messages() {
  const server = useStore((s) => s.server);
  const live = useStore((s) => s.liveCards);
  const provisional = useStore((s) => s.provisional);
  const working = useStore((s) => s.working);
  const notices = useStore((s) => s.notices);
  const sel = useStore((s) => s.sel);
  const select = useStore((s) => s.select);
  const ref = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  const [jump, setJump] = useState(false);
  const cards = allCards(server, live);
  const turns = server?.turns ?? [];
  const baseline = server?.mode === "baseline";

  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    if (atBottom.current) setJump(false);
  };
  const toBottom = () => { ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: "smooth" }); setJump(false); };

  const signature = `${turns.length}|${cards.length}|${cards.map((c) => c.status[0]).join("")}|${provisional?.text ?? ""}|${working?.stage ?? ""}`;
  useEffect(() => {
    if (atBottom.current) ref.current?.scrollTo({ top: ref.current.scrollHeight });
    else setJump(true);
  }, [signature]);

  // Cross-panel links: clicking a History node scrolls to that exchange and flashes it.
  useEffect(() => {
    if (sel.flashTurnId === null) return;
    document.getElementById(`turn-${sel.flashTurnId}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
    const t = setTimeout(() => select({ flashTurnId: null }), 1500);
    return () => clearTimeout(t);
  }, [sel.flashTurnId, select]);
  useEffect(() => {
    if (sel.flashCardId === null) return;
    document.getElementById(`card-${sel.flashCardId}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
    const t = setTimeout(() => select({ flashCardId: null }), 1500);
    return () => clearTimeout(t);
  }, [sel.flashCardId, select]);

  let topic = 0;
  return (
    <div className="messages" ref={ref} onScroll={onScroll} role="log" aria-live="polite" aria-label="Conversation">
      {turns.map((t) => {
        const group = cards.filter((c) => c.turn === t.i);
        const isLast = t.i === turns.length - 1;
        const divider = t.new_block && t.i > 0 ? (topic += 1, topic + 1) : null;
        return (
          <div key={t.id} style={{ display: "contents" }}>
            {divider && <div className="divider-topic">Topic {divider}</div>}
            <div id={`turn-${t.i}`} className={`msg-q${sel.flashTurnId === t.i ? " flash" : ""}${sel.focusTurnId === t.i ? " hl" : ""}`}>
              {t.qtype !== "chat" && <div><span className={`chip ${t.qtype}`}>{QTYPE_LABEL[t.qtype]}</span></div>}
              {t.question}
            </div>
            {t.answer ? (
              <div className="msg-a">{t.answer}<button className="link how" onClick={() => useStore.getState().openInspector(t.i)}>See how this was processed</button></div>
            ) : isLast && provisional ? (
              <div className="msg-a">{provisional.text}</div>
            ) : null}
            {notices.filter((n) => n.turn === t.i).map((n, i) => <div key={i} className="notice">{n.text}</div>)}
            {group.length > 0 && <CardGroup cards={group} all={cards} />}
          </div>
        );
      })}
      <StatusLine />
      {jump && <button className="jump" onClick={toBottom}>Jump to latest</button>}
      {baseline && turns.length === 1 && <div className="hint">Baseline condition: plain chat. Proposals appear after every message.</div>}
    </div>
  );
}

function Composer() {
  const server = useStore((s) => s.server);
  const live = useStore((s) => s.liveCards);
  const working = useStore((s) => s.working);
  const draft = useStore((s) => s.draft);
  const setDraft = useStore((s) => s.setDraft);
  const send = useStore((s) => s.send);
  const connection = useStore((s) => s.connection);
  const locked = useStore((s) => isLocked({ server: s.server, working: s.working, liveCards: s.liveCards })) || connection !== "ok";
  const ref = useRef<HTMLTextAreaElement>(null);
  const pending = (server?.pending.length ?? 0) > 0 || live.some((c) => c.status === "pending");
  const placeholder = pending ? "Review the cards above first…" : working ? "One moment…" : "Type your answer…";

  useEffect(() => { if (!locked) ref.current?.focus(); }, [locked]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 4 * 19) + "px";
  }, [draft]);

  const go = () => { if (!locked && draft.trim()) void send(draft); };
  return (
    <div className="composer">
      <div className={`box${locked ? " locked" : ""}`}>
        <textarea
          ref={ref} rows={1} value={draft} disabled={locked} placeholder={placeholder} aria-label="Your answer"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(); } }}
        />
      </div>
      <button className={`send${!locked && draft.trim() ? " on" : ""}`} disabled={locked || !draft.trim()} onClick={go}>Send</button>
    </div>
  );
}

export function ChatPanel() {
  const server = useStore((s) => s.server);
  const working = useStore((s) => s.working);
  const error = useStore((s) => s.error);
  const skip = useStore((s) => s.skip);
  const showQuick = !!server && server.mode === "attrify" && server.can_skip && !working;
  return (
    <PanelFrame letter="A" title="Chat Panel" scroll={false}>
      <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
        <Header />
        <Messages />
        {showQuick && (
          <div className="quick">
            <button onClick={() => void skip("next")}>Nothing to add, next question</button>
            <button onClick={() => void skip("topic")}>Start a new topic</button>
          </div>
        )}
        {error && (
          <div className="banner red err-inline" role="alert">
            <span>{error.message}</span>
            <button className="btn primary" onClick={error.retry}>Retry</button>
          </div>
        )}
        <Composer />
      </div>
    </PanelFrame>
  );
}
