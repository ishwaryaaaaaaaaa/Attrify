import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { clusterColor, fmt, modalShare, snake } from "../util";
import { PanelFrame } from "./PanelFrame";

const ROW_H = 28;

function Histogram({ counts, edges, name }: { counts: number[]; edges: number[]; name: string }) {
  const max = Math.max(1, ...counts);
  const bw = 100 / counts.length;
  return (
    <svg width="100%" height="24" viewBox="0 0 100 24" preserveAspectRatio="none" role="img" aria-label={`Distribution of ${name}`}>
      {counts.map((c, i) => (
        <rect key={i} x={i * bw + 0.5} y={24 - (c / max) * 22} width={bw - 1} height={(c / max) * 22} fill="#c5d1ea">
          <title>{`${fmt(edges[i])} to ${fmt(edges[i + 1])}: ${c} essays`}</title>
        </rect>
      ))}
    </svg>
  );
}

interface Reader { id: number; text: string; names: string[]; values: number[] }

export function TablePanel() {
  const server = useStore((s) => s.server);
  const sel = useStore((s) => s.sel);
  const select = useStore((s) => s.select);
  const newFids = useStore((s) => s.newFids);
  const revisit = useStore((s) => s.revisit);
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null);
  const [menu, setMenu] = useState<number | null>(null);
  const [reader, setReader] = useState<Reader | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  const table = server?.table;
  const nCols = table?.names.length ?? 0;
  const template = `180px ${"minmax(110px,1fr) ".repeat(nCols)}`.trim();
  const minW = 180 + 110 * nCols;

  const rows = useMemo(() => {
    if (!table) return [];
    let r = table.rows;
    if (sel.focusClusterId !== null) r = r.filter((x) => x.cluster === sel.focusClusterId);
    if (sel.brushIds) { const ids = new Set(sel.brushIds); r = r.filter((x) => ids.has(x.id)); }
    if (sort) r = [...r].sort((a, b) => (a.values[sort.col] - b.values[sort.col]) * sort.dir);
    return r;
  }, [table, sort, sel.focusClusterId, sel.brushIds]);

  const virt = useVirtualizer({ count: rows.length, getScrollElement: () => scroller.current, estimateSize: () => ROW_H, overscan: 12 });

  // Shortcut clicks elsewhere: scroll to the column or the selected row.
  useEffect(() => {
    if (sel.flashCardId === null || !table) return;
    const idx = table.fids.indexOf(sel.flashCardId);
    if (idx >= 0) document.getElementById(`col-${sel.flashCardId}`)?.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
  }, [sel.flashCardId, table]);
  useEffect(() => {
    if (sel.selectedEssayId === null) return;
    const i = rows.findIndex((r) => r.id === sel.selectedEssayId);
    if (i >= 0) virt.scrollToIndex(i, { align: "center" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel.selectedEssayId]);
  useEffect(() => {
    if (sel.selectedEssayId === null) { setReader(null); return; }
    let alive = true;
    api.essay(sel.selectedEssayId).then((r) => alive && setReader(r)).catch(() => undefined);
    return () => { alive = false; };
  }, [sel.selectedEssayId]);

  if (!server || !table) return null;
  const filtered = sel.focusClusterId !== null || sel.brushIds !== null;

  return (
    <PanelFrame letter="C" title="Attribute Table" id="table" scroll={false}>
      <div className="tbl-wrap">
        {filtered && (
          <div className="banner warn" style={{ margin: 6, display: "flex", justifyContent: "space-between" }}>
            <span>Showing {rows.length} essays{sel.focusClusterId !== null ? ` in group ${sel.focusClusterId + 1}` : " in your selection"}.</span>
            <button className="link" onClick={() => select({ focusClusterId: null, brushIds: null })}>Clear (Esc)</button>
          </div>
        )}
        {nCols === 0 ? (
          <div className="empty">Accept an attribute card to add your first column.</div>
        ) : (
          <div className="tbl-scroll" ref={scroller}>
            <div style={{ minWidth: minW }}>
              <div className="t-head" style={{ gridTemplateColumns: template }}>
                <div className="t-colhead sticky" style={{ textAlign: "left", position: "sticky", left: 0, background: "#fff", zIndex: 4 }}>Essay</div>
                {table.names.map((name, j) => {
                  const col = table.rows.map((r) => r.values[j]);
                  const m = modalShare(col);
                  const fid = table.fids[j];
                  const hi = sel.hoverCardId === fid;
                  const flash = newFids.includes(fid);
                  return (
                    <div key={fid} id={`col-${fid}`} className={`t-colhead${hi ? " hi" : ""}${flash ? " flash" : ""}`} style={{ position: "relative" }}>
                      <Histogram counts={table.hists[j].counts} edges={table.hists[j].edges} name={name} />
                      <div style={{ display: "flex", justifyContent: "flex-end", gap: 2 }}>
                        <button className="name" title="Sort by this column" aria-label={`Sort by ${snake(name)}`} onClick={() => { api.event("table_sort", { ids: [fid] }); setSort(sort?.col === j ? (sort.dir === 1 ? { col: j, dir: -1 } : null) : { col: j, dir: 1 }); }}>
                          {snake(name)}{sort?.col === j ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
                        </button>
                        <button className="link" aria-label={`Menu for ${snake(name)}`} onClick={() => setMenu(menu === j ? null : j)}>⋯</button>
                      </div>
                      {m.share > 0.5 && <span className="zero-badge">{Math.round(m.share * 100)}% {m.value === 0 ? "zeros" : "same"}</span>}
                      {menu === j && (
                        <div className="menu" style={{ top: "100%", right: 0, minWidth: 140 }}>
                          <button onClick={() => { setMenu(null); select({ flashCardId: fid }); }}>Show card</button>
                          <button onClick={() => { setMenu(null); void revisit(fid, "reject", "history"); }}>Reject</button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              <div style={{ height: virt.getTotalSize(), position: "relative" }}>
                {virt.getVirtualItems().map((v) => {
                  const r = rows[v.index];
                  const tint = r.cluster >= 0 ? clusterColor(r.cluster) + "1f" : "#fff";
                  const cls = `t-row${sel.selectedEssayId === r.id ? " sel" : ""}${sel.hoverEssayId === r.id ? " hov" : ""}`;
                  return (
                    <div key={r.id} className={cls} role="row" tabIndex={0} style={{ gridTemplateColumns: template, top: v.start, height: ROW_H, background: tint }}
                      onMouseEnter={() => select({ hoverEssayId: r.id })} onMouseLeave={() => select({ hoverEssayId: null })}
                      onClick={() => { api.event("row_open", { ids: [r.id] }); select({ selectedEssayId: r.id }); }}
                      onKeyDown={(e) => { if (e.key === "Enter") select({ selectedEssayId: r.id }); }}>
                      <div className="t-cell sticky" style={{ background: tint === "#fff" ? "#fff" : `color-mix(in srgb, ${clusterColor(r.cluster)} 12%, white)` }} title={r.text}>
                        <span className="mono hint">#{r.id}</span> {r.text.slice(0, 40)}
                      </div>
                      {r.values.map((val, j) => <div key={j} className={`t-cell num${newFids.includes(table.fids[j]) ? " flash" : ""}`}>{fmt(val)}</div>)}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
        {reader && (
          <div className="reader" role="dialog" aria-label={`Essay ${reader.id}`}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <strong>Essay #{reader.id}</strong>
              <button className="link" onClick={() => select({ selectedEssayId: null })}>Close</button>
            </div>
            <div style={{ margin: "6px 0" }}>
              {reader.names.map((n, i) => <div key={n} className="sample" style={{ gridTemplateColumns: "1fr 60px" }}><span className="mono">{snake(n)}</span><span className="v">{fmt(reader.values[i])}</span></div>)}
            </div>
            <pre>{reader.text}</pre>
          </div>
        )}
      </div>
    </PanelFrame>
  );
}
