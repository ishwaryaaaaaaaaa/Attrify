import { polygonHull } from "d3-polygon";
import { scaleLinear } from "d3-scale";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useSize } from "../hooks";
import { useStore } from "../store";
import { clusterColor } from "../util";
import { PanelFrame } from "./PanelFrame";

const M = { l: 44, r: 16, t: 22, b: 34 };
const DEV = new URLSearchParams(location.search).has("dev");

const jitter = (id: number) => (((id * 2654435761) >>> 0) % 1000) / 1000 - 0.5;

export function GraphPanel() {
  const server = useStore((s) => s.server);
  const sel = useStore((s) => s.sel);
  const select = useStore((s) => s.select);
  const setEps = useStore((s) => s.setEps);
  const eps = useStore((s) => s.eps);
  const wrap = useRef<HTMLDivElement>(null);
  const { w, h } = useSize(wrap);
  const prev = useRef<Map<number, [number, number]>>(new Map());
  const [tip, setTip] = useState<{ x: number; y: number; id: number } | null>(null);
  const [box, setBox] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);

  const cov = server?.coverage;
  const nCols = server?.table.names.length ?? 0;

  // Keep the picture oriented: PCA axes may flip sign between runs, so flip them back to match last time.
  const pts = useMemo(() => {
    if (!cov || cov.points.length === 0) return [] as [number, number][];
    const out = cov.points.map((p) => [...p] as [number, number]);
    for (const axis of [0, 1] as const) {
      let dot = 0;
      out.forEach((p, i) => { const q = prev.current.get(cov.ids[i]); if (q) dot += q[axis] * p[axis]; });
      if (dot < 0) out.forEach((p) => { p[axis] = -p[axis]; });
    }
    return out;
  }, [cov]);
  useEffect(() => {
    if (!cov) return;
    prev.current = new Map(cov.ids.map((id, i) => [id, pts[i]] as [number, number[]]) as [number, [number, number]][]);
  }, [cov, pts]);

  const strip = nCols === 1;
  const xs = pts.map((p) => p[0]);
  const ys = strip ? [-1, 1] : pts.map((p) => p[1]);
  const pad = (a: number[]) => { const lo = Math.min(...a), hi = Math.max(...a); const d = (hi - lo || 1) * 0.08; return [lo - d, hi + d]; };
  const sx = scaleLinear().domain(xs.length ? pad(xs) : [0, 1]).range([M.l, Math.max(M.l + 10, w - M.r)]);
  const sy = scaleLinear().domain(ys.length ? pad(ys) : [0, 1]).range([Math.max(M.t + 10, h - M.b), M.t]);
  const pos = (i: number): [number, number] => [sx(pts[i][0]), strip ? sy(jitter(cov!.ids[i]) * 1.6) : sy(pts[i][1])];

  const rowText = useMemo(() => new Map((server?.table.rows ?? []).map((r) => [r.id, r.text])), [server?.table.rows]);

  const hulls = useMemo(() => {
    if (!cov || strip || pts.length === 0) return [];
    const groups = new Map<number, number[]>();
    cov.labels.forEach((l, i) => { if (l >= 0) groups.set(l, [...(groups.get(l) ?? []), i]); });
    return [...groups.entries()].map(([label, idx]) => ({ label, idx }));
  }, [cov, strip, pts.length]);

  const onDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if ((e.target as Element).closest(".pt, .hull")) return;
    const r = e.currentTarget.getBoundingClientRect();
    setBox({ x0: e.clientX - r.left, y0: e.clientY - r.top, x1: e.clientX - r.left, y1: e.clientY - r.top });
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!box) return;
    const r = e.currentTarget.getBoundingClientRect();
    setBox({ ...box, x1: e.clientX - r.left, y1: e.clientY - r.top });
  };
  const onUp = () => {
    if (!box || !cov) return;
    const [xa, xb] = [Math.min(box.x0, box.x1), Math.max(box.x0, box.x1)];
    const [ya, yb] = [Math.min(box.y0, box.y1), Math.max(box.y0, box.y1)];
    setBox(null);
    if (xb - xa < 4 && yb - ya < 4) { select({ brushIds: null }); return; }
    const ids = cov.ids.filter((_, i) => { const [x, y] = pos(i); return x >= xa && x <= xb && y >= ya && y <= yb; });
    api.event("graph_select", { ids });
    select({ brushIds: ids.length ? ids : null, focusClusterId: null });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") select({ brushIds: null, focusClusterId: null, selectedEssayId: null }); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [select]);

  if (!server || !cov) return null;
  const nGroups = hulls.length;
  const largestN = cov.largest !== null ? cov.labels.filter((l) => l === cov.largest).length : 0;
  const summary = nCols === 0 ? "No attributes accepted yet." : `${nGroups} group${nGroups === 1 ? "" : "s"}; largest has ${largestN} essays.`;
  const empty = nCols === 0;

  return (
    <PanelFrame letter="D" title="Coverage Graph" id="graph" scroll={false}>
      <div ref={wrap} style={{ position: "relative", height: "100%" }}>
        <span className="sr-only" role="status">{summary}</span>
        {empty && <div className="empty" style={{ position: "absolute", inset: 0 }}>Accept two attributes to see how your essays spread out.</div>}
        {!empty && (
          <svg className="graph-svg" width={w} height={h} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} role="img" aria-label={`Coverage graph. ${summary}`}>
            <line x1={M.l} x2={w - M.r} y1={h - M.b} y2={h - M.b} stroke="#c9d0de" />
            {!strip && <line x1={M.l} x2={M.l} y1={M.t} y2={h - M.b} stroke="#c9d0de" />}
            <text x={(M.l + w - M.r) / 2} y={h - 8} textAnchor="middle">{strip ? "Attribute value" : `PC1 (${(cov.explained[0] * 100).toFixed(1)}%)`}</text>
            {!strip && <text transform={`translate(12,${(M.t + h - M.b) / 2}) rotate(-90)`} textAnchor="middle">PC2 ({(cov.explained[1] * 100).toFixed(1)}%)</text>}

            {hulls.map(({ label, idx }) => {
              const poly = idx.length >= 3 ? polygonHull(idx.map(pos)) : null;
              if (!poly) return null;
              const big = label === cov.largest;
              const c = clusterColor(label);
              const active = sel.focusClusterId === label;
              return (
                <g key={label} className="hull" onClick={() => select({ focusClusterId: active ? null : label, brushIds: null })}>
                  <path d={"M" + poly.map((p) => p.join(",")).join("L") + "Z"} fill={c} fillOpacity=".14" stroke={c} strokeWidth={big || active ? 3 : 1.2} strokeLinejoin="round">
                    <title>{big ? "The next open-ended question will ask about essays like these." : `Group ${label + 1}`}</title>
                  </path>
                  {big && (() => {
                    const minX = Math.min(...poly.map((q) => q[0])), maxX = Math.max(...poly.map((q) => q[0])), minY = Math.min(...poly.map((q) => q[1]));
                    const right = minX + 150 > w;
                    return <text x={right ? maxX : minX} y={Math.max(12, minY - 6)} textAnchor={right ? "end" : "start"} style={{ fill: c, fontWeight: 700 }}>Largest group · {largestN} essays</text>;
                  })()}
                </g>
              );
            })}

            {pts.map((_, i) => {
              const id = cov.ids[i];
              const [x, y] = pos(i);
              const lab = cov.labels[i];
              const ringed = sel.hoverEssayId === id || sel.selectedEssayId === id;
              const brushed = sel.brushIds?.includes(id);
              return (
                <g key={id} className="pt" style={{ transform: `translate(${x}px, ${y}px)` }}
                  onMouseEnter={() => { select({ hoverEssayId: id }); setTip({ x, y, id }); }}
                  onMouseLeave={() => { select({ hoverEssayId: null }); setTip(null); }}
                  onClick={() => select({ selectedEssayId: id })}>
                  {ringed && <circle r="8" fill="none" stroke="#2a6bff" strokeWidth="2" />}
                  {brushed && <circle r="7" fill="none" stroke="#c4501e" strokeWidth="1.5" />}
                  {lab < 0 ? <circle r="3.5" fill="#fff" stroke="#9aa3b5" strokeWidth="1.2" /> : <circle r="3.5" fill={clusterColor(lab)} fillOpacity=".85" />}
                </g>
              );
            })}
            {box && <rect x={Math.min(box.x0, box.x1)} y={Math.min(box.y0, box.y1)} width={Math.abs(box.x1 - box.x0)} height={Math.abs(box.y1 - box.y0)} fill="#2a6bff" fillOpacity=".08" stroke="#2a6bff" strokeDasharray="3 3" />}
          </svg>
        )}
        {tip && <div className="tooltip" style={{ left: Math.min(tip.x + 10, w - 200), top: Math.max(0, tip.y - 34) }}>#{tip.id} · {rowText.get(tip.id) ?? ""}</div>}
        {DEV && !empty && (
          <label style={{ position: "absolute", right: 8, top: 6, fontSize: 11 }}>
            eps {(eps ?? cov.eps ?? 0).toFixed(2)}{" "}
            <input type="range" min="0.05" max="3" step="0.05" value={eps ?? cov.eps ?? 0.5} onChange={(e) => void setEps(Number(e.target.value))} />
          </label>
        )}
      </div>
    </PanelFrame>
  );
}
