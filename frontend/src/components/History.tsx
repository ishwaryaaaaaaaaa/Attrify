import { scaleLinear } from "d3-scale";
import { Minus, Plus, Scan } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useSize } from "../hooks";
import { allCards, useStore } from "../store";
import { FunctionCard, Turn } from "../types";
import { QTYPE_LABEL } from "../util";
import { PanelFrame } from "./PanelFrame";

const SLOT = 150, NODE_W = 110, NODE_H = 44, LEFT = 64, TOP = 26;
const TYPE_COLOR: Record<string, { fg: string; bg: string }> = {
  open_ended: { fg: "#2a5db0", bg: "#e3ecfb" }, clarify: { fg: "#17756f", bg: "#d9f1ee" },
  suggest: { fg: "#9a6a00", bg: "#fdf0c4" }, chat: { fg: "#5b667a", bg: "#eceff4" },
};
const STATUS_FILL: Record<string, { fill: string; stroke: string }> = {
  pending: { fill: "#eef0f4", stroke: "#d5dbe6" }, accepted: { fill: "#dff3e6", stroke: "#9fd3b2" },
  rejected: { fill: "#fde4e2", stroke: "#f0aaa5" }, refined: { fill: "#e9e5fa", stroke: "#b9aef0" },
};

interface NodeInfo { turn: Turn; slot: number; softness: number | null; provisional: boolean }

export function HistoryPanel() {
  const server = useStore((s) => s.server);
  const live = useStore((s) => s.liveCards);
  const provisional = useStore((s) => s.provisional);
  const sel = useStore((s) => s.sel);
  const select = useStore((s) => s.select);
  const revisit = useStore((s) => s.revisit);
  const wrap = useRef<HTMLDivElement>(null);
  const { w, h } = useSize(wrap);
  const [view, setView] = useState({ tx: 0, k: 1 });
  const [openTurn, setOpenTurn] = useState<number | null>(null);
  const [hoverTurn, setHoverTurn] = useState<number | null>(null);
  const drag = useRef<{ x: number; tx: number } | null>(null);
  const dragged = useRef(false);

  const cards = allCards(server, live);
  const baselineY = Math.max(TOP + 120, h - 62);
  const y = useMemo(() => scaleLinear().domain([0, 100]).range([baselineY, TOP]), [baselineY]);

  const nodes: NodeInfo[] = useMemo(() => {
    const out: NodeInfo[] = [];
    (server?.turns ?? []).forEach((t, idx, arr) => {
      const isLast = idx === arr.length - 1;
      if (t.softness !== null) out.push({ turn: t, slot: out.length, softness: t.softness, provisional: false });
      else if (isLast && provisional) out.push({ turn: { ...t, answer: provisional.text, keywords: provisional.keywords ?? [], specification: provisional.specification ?? "" }, slot: out.length, softness: provisional.score ?? null, provisional: provisional.score === undefined });
    });
    return out;
  }, [server, provisional]);

  const px = (slot: number) => LEFT + 70 + view.tx + slot * SLOT * view.k;
  const latest = nodes[nodes.length - 1];

  // Auto-pan so the newest node stays visible (unless the user is dragging).
  useEffect(() => {
    if (!latest || drag.current) return;
    const x = px(latest.slot);
    if (x > w - NODE_W) setView((v) => ({ ...v, tx: v.tx - (x - (w - NODE_W)) }));
    else if (x < LEFT + NODE_W / 2) setView((v) => ({ ...v, tx: v.tx + (LEFT + NODE_W / 2 - x) }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes.length, w]);

  const onDown = (e: React.PointerEvent) => {
    if ((e.target as Element).closest(".node, .bcard, button")) return;
    drag.current = { x: e.clientX, tx: view.tx };
    dragged.current = false;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  };
  const onMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const dx = e.clientX - drag.current.x;
    if (Math.abs(dx) > 3) dragged.current = true;
    setView((v) => ({ ...v, tx: drag.current!.tx + dx }));
  };
  const onUp = () => { drag.current = null; };
  // Ctrl + scroll zooms. React's onWheel is passive, so attach a native non-passive listener.
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const on = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      setView((v) => ({ ...v, k: Math.min(2, Math.max(0.5, v.k * (e.deltaY < 0 ? 1.1 : 0.9))) }));
    };
    el.addEventListener("wheel", on, { passive: false });
    return () => el.removeEventListener("wheel", on);
  }, [server]);
  const zoomBy = (f: number) => setView((v) => ({ ...v, k: Math.min(2, Math.max(0.5, v.k * f)) }));
  const fit = () => setView({ tx: 0, k: 1 });

  const openNode = (n: NodeInfo) => {
    api.event("node_open", { turnId: n.turn.id });
    select({ flashTurnId: n.turn.i });
    setOpenTurn(openTurn === n.turn.i ? null : n.turn.i);
  };
  const keyNav = (e: React.KeyboardEvent, n: NodeInfo) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNode(n); }
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (d) (document.querySelector(`[data-slot="${n.slot + d}"]`) as HTMLElement | null)?.focus();
  };

  if (!server) return null;
  const popNode = nodes.find((n) => n.turn.i === openTurn);
  const popCard = sel.popoverCardId !== null ? cards.find((c) => c.id === sel.popoverCardId) : undefined;
  let topic = 1;

  const cardsOf = (n: NodeInfo): FunctionCard[] => cards.filter((c) => c.turn === n.turn.i);

  return (
    <PanelFrame letter="B" title="Interaction History" id="history" scroll={false}>
      <div className="hist-wrap" ref={wrap}>
        <div className="hist-tools">
          <button aria-label="Zoom in" onClick={() => zoomBy(1.2)}><Plus size={13} /></button>
          <button aria-label="Zoom out" onClick={() => zoomBy(1 / 1.2)}><Minus size={13} /></button>
          <button aria-label="Fit" title="Fit" onClick={fit}><Scan size={13} /></button>
        </div>
        {nodes.length === 0 && <div className="empty" style={{ position: "absolute", inset: 0 }}>Your conversation will appear here as a timeline.</div>}
        <svg className="hist-svg" width={w} height={h} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} role="img" aria-label="Timeline of your answers by softness">
          <defs>
            <pattern id="grid" width="12" height="12" patternUnits="userSpaceOnUse"><path d="M12 0H0V12" fill="none" stroke="#e8ecf3" strokeWidth="1" /></pattern>
            <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" fill="#7a84a0" /></marker>
          </defs>
          <rect x={LEFT} y={0} width={Math.max(0, w - LEFT)} height={baselineY + 20} fill="url(#grid)" />
          <rect x={LEFT} y={y(100)} width={Math.max(0, w - LEFT)} height={y(65) - y(100)} fill="#e3ecfb" opacity=".55" />
          <rect x={LEFT} y={y(30)} width={Math.max(0, w - LEFT)} height={y(0) - y(30)} fill="#dff3e6" opacity=".55" />
          <text x={LEFT + 6} y={y(100) + 12}>soft (≥ 65, ask first)</text>
          <text x={LEFT + 6} y={y(30) + 12}>not soft (≤ 30)</text>
          <text x={4} y={12}>very soft</text>
          {[0, 30, 65, 100].map((t) => (
            <g key={t}><line x1={LEFT - 4} x2={w} y1={y(t)} y2={y(t)} stroke="#c9d0de" strokeWidth={t === 0 ? 1.5 : 0.6} strokeDasharray={t === 0 ? undefined : "3 3"} /><text x={LEFT - 8} y={y(t) + 4} textAnchor="end">{t}</text></g>
          ))}
          <text x={LEFT + 6} y={baselineY - 6}>baseline: softness 0 = one single computed meaning</text>

          {/* topic dividers */}
          {nodes.map((n, i) => {
            if (i === 0 || !n.turn.new_block) return null;
            topic += 1;
            const x = (px(n.slot - 1) + px(n.slot)) / 2;
            return <g key={`d${i}`}><line x1={x} x2={x} y1={TOP - 10} y2={baselineY + 22} stroke="#7a84a0" strokeDasharray="2 4" /><text x={x + 4} y={TOP}>Topic {topic}</text></g>;
          })}

          {/* edges between nodes */}
          {nodes.slice(1).map((n, i) => {
            const a = nodes[i];
            const x1 = px(a.slot) + NODE_W / 2, y1 = y(a.softness ?? 50), x2 = px(n.slot) - NODE_W / 2, y2 = y(n.softness ?? 50);
            const mx = (x1 + x2) / 2;
            return <path key={`e${i}`} d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} fill="none" stroke="#7a84a0" strokeWidth="1.5" markerEnd="url(#arrow)" />;
          })}

          {nodes.map((n) => {
            const cx = px(n.slot);
            const cy = y(n.softness ?? 50);
            const cs = cardsOf(n);
            const tc = TYPE_COLOR[n.turn.qtype] ?? TYPE_COLOR.chat;
            const kw = (n.turn.keywords.join(" ") || n.turn.answer.slice(0, 16)).slice(0, 18) + ((n.turn.keywords.join(" ") || n.turn.answer).length > 18 ? "…" : "");
            const isLatest = n === latest;
            const hot = hoverTurn === n.turn.i || sel.flashTurnId === n.turn.i;
            return (
              <g key={n.turn.id}>
                {/* links down to the baseline */}
                {cs.map((c, j) => {
                  const bx = cx + (j - (cs.length - 1) / 2) * 34;
                  return <line key={`l${c.id}`} x1={cx} y1={cy + NODE_H / 2} x2={bx} y2={baselineY + 24} stroke="#7a84a0" strokeDasharray="3 3" strokeWidth={sel.hoverCardId === c.id ? 2 : 1} />;
                })}
                {cs.length === 0 && n.softness !== null && n.softness >= 65 && (
                  <g><line x1={cx} y1={cy + NODE_H / 2} x2={cx} y2={baselineY + 20} stroke="#7a84a0" strokeDasharray="1 4" /><text x={cx} y={baselineY + 36} textAnchor="middle"><title>Too open to measure yet, so I asked first.</title>—</text></g>
                )}
                {cs.map((c, j) => {
                  const bx = cx + (j - (cs.length - 1) / 2) * 34;
                  const st = STATUS_FILL[c.status];
                  return (
                    <g key={`c${c.id}`} className={`bcard${sel.hoverCardId === c.id ? " glow" : ""}`} transform={`translate(${bx - 14},${baselineY + 24})`} tabIndex={0} role="button"
                      aria-label={`${c.name}, ${c.status}`}
                      onMouseEnter={() => select({ hoverCardId: c.id })} onMouseLeave={() => select({ hoverCardId: null })}
                      onClick={() => { select({ popoverCardId: sel.popoverCardId === c.id ? null : c.id, flashCardId: c.id, hoverCardId: c.id }); }}
                      onKeyDown={(e) => { if (e.key === "Enter") select({ popoverCardId: c.id, flashCardId: c.id }); }}>
                      <title>{c.name} ({c.status})</title>
                      <rect width="28" height="20" rx="4" fill={st.fill} stroke={sel.hoverCardId === c.id ? "#2a6bff" : st.stroke} />
                      <circle cx="10" cy="10" r="2.5" fill="#5b667a" /><circle cx="18" cy="10" r="2.5" fill="#5b667a" />
                    </g>
                  );
                })}
                {/* gap bracket on hover */}
                {hoverTurn === n.turn.i && n.softness !== null && n.softness > 0 && (
                  <g stroke="#c4501e" strokeWidth="1.5" fill="none">
                    <path d={`M${cx - NODE_W / 2 - 8},${cy} h-6 V${baselineY} h6`} />
                    <text x={cx - NODE_W / 2 - 18} y={(cy + baselineY) / 2} textAnchor="end" fill="#c4501e" stroke="none" style={{ fill: "#c4501e", fontWeight: 700 }}>gap = {n.softness}</text>
                    <text x={cx - NODE_W / 2 - 18} y={(cy + baselineY) / 2 + 13} textAnchor="end" stroke="none" style={{ fill: "#c4501e" }}>meanings left</text>
                  </g>
                )}
                <g className={`node${isLatest ? " latest" : ""}${n.provisional ? " prov" : ""}${hot ? " flash" : ""}`} data-slot={n.slot} tabIndex={0} role="button"
                  aria-label={`${QTYPE_LABEL[n.turn.qtype]} answer, softness ${n.softness ?? "being scored"}`}
                  onMouseEnter={() => { setHoverTurn(n.turn.i); select({ focusTurnId: n.turn.i }); }}
                  onMouseLeave={() => { setHoverTurn(null); select({ focusTurnId: null }); }}
                  onFocus={() => setHoverTurn(n.turn.i)} onBlur={() => setHoverTurn(null)}
                  onClick={() => { if (!dragged.current) openNode(n); }} onKeyDown={(e) => keyNav(e, n)}>
                  <rect className="box" x={cx - NODE_W / 2} y={cy - NODE_H / 2} width={NODE_W} height={NODE_H} rx="8" />
                  <rect x={cx - NODE_W / 2 + 8} y={cy - NODE_H / 2 - 7} width={QTYPE_LABEL[n.turn.qtype].length * 6.2 + 10} height="14" rx="4" fill={tc.bg} />
                  <text x={cx - NODE_W / 2 + 13} y={cy - NODE_H / 2 + 3} style={{ fill: tc.fg, fontSize: 9, fontWeight: 700, letterSpacing: ".4px" }}>{QTYPE_LABEL[n.turn.qtype].toUpperCase()}</text>
                  <text className="kw" x={cx - NODE_W / 2 + 8} y={cy + 8}>{kw}</text>
                </g>
              </g>
            );
          })}
        </svg>

        {popNode && (
          <div className="popover node-pop" style={{ left: Math.min(Math.max(8, px(popNode.slot) - 150), Math.max(8, w - 310)), top: Math.min(y(popNode.softness ?? 50) + NODE_H / 2 + 6, Math.max(8, h - 190)) }} role="dialog" aria-label="Interaction details">
            <span className={`chip ${popNode.turn.qtype}`}>{QTYPE_LABEL[popNode.turn.qtype]}</span>
            <strong style={{ marginLeft: 8 }}>softness {popNode.softness ?? "…"}</strong>
            <div style={{ marginTop: 6 }}><b>Q:</b> {popNode.turn.question}</div>
            <div style={{ marginTop: 4 }}><b>A:</b> {popNode.turn.answer}</div>
            {popNode.turn.specification && <div className="hint" style={{ marginTop: 6 }}>Restated: “{popNode.turn.specification}”</div>}
            <div style={{ textAlign: "right" }}><button className="link" onClick={() => setOpenTurn(null)}>Close</button></div>
          </div>
        )}
        {popCard && (
          <div className="popover node-pop" style={{ left: Math.max(8, Math.min(w - 310, 80)), top: Math.max(8, baselineY - 130) }} role="dialog" aria-label="Card decision">
            <strong>{popCard.name}</strong> <span className={`badge-status ${popCard.status}`}>{popCard.status}</span>
            <div className="hint" style={{ margin: "4px 0 6px" }}>Change your mind about this attribute:</div>
            <div style={{ display: "flex", gap: 6 }}>
              <button className="btn accept" disabled={popCard.status !== "rejected"} onClick={() => { void revisit(popCard.id, "accept", "history"); select({ popoverCardId: null }); }}>Accept</button>
              <button className="btn reject" disabled={popCard.status !== "accepted"} onClick={() => { void revisit(popCard.id, "reject", "history"); select({ popoverCardId: null }); }}>Reject</button>
              <button className="link" onClick={() => select({ popoverCardId: null })}>Close</button>
            </div>
          </div>
        )}
      </div>
    </PanelFrame>
  );
}
