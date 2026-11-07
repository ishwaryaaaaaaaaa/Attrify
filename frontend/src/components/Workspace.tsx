import { useEffect, useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { useStore } from "../store";
import { ChatPanel } from "./Chat";
import { GraphPanel } from "./Graph";
import { HistoryPanel } from "./History";
import { InspectorPanel } from "./Inspector";
import { TablePanel } from "./Table";

const KEY = "attrify.layout.";
const load = (id: string): Record<string, number> | undefined => {
  try { const v = localStorage.getItem(KEY + id); return v ? JSON.parse(v) : undefined; } catch { return undefined; }
};
const save = (id: string) => (layout: Record<string, number>) => {
  try { localStorage.setItem(KEY + id, JSON.stringify(layout)); } catch { /* storage can be blocked */ }
};

function useWide() {
  const [wide, setWide] = useState(window.innerWidth >= 1100);
  useEffect(() => {
    const on = () => setWide(window.innerWidth >= 1100);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return wide;
}

export function Workspace() {
  const server = useStore((s) => s.server);
  const connection = useStore((s) => s.connection);
  const toast = useStore((s) => s.toast);
  const wide = useWide();
  const [tab, setTab] = useState<"history" | "table" | "graph">("history");
  const inspecting = useStore((s) => s.inspector.open);
  if (!server) return null;
  const baseline = server.mode === "baseline";
  const mode = baseline ? "b" : "a";

  const right = inspecting ? <InspectorPanel /> : !wide ? (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div className="tabs-narrow" role="tablist">
        {(baseline ? (["table", "graph"] as const) : (["history", "table", "graph"] as const)).map((t) => (
          <button key={t} role="tab" aria-selected={(baseline && tab === "history" ? "table" : tab) === t} onClick={() => setTab(t)}>
            {{ history: "Interaction History", table: "Attribute Table", graph: "Coverage Graph" }[t]}
          </button>
        ))}
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        {(baseline && tab === "history" ? "table" : tab) === "history" ? <HistoryPanel /> : (baseline && tab === "history" ? "table" : tab) === "table" ? <TablePanel /> : <GraphPanel />}
      </div>
    </div>
  ) : baseline ? (
    <Group style={{ overflow: "visible" }} orientation="vertical" id={`right-${mode}`} defaultLayout={load(`right-${mode}`)} onLayoutChanged={save(`right-${mode}`)}>
      <Panel id="c" style={{ overflow: "visible" }} defaultSize="55%" minSize="20%"><TablePanel /></Panel>
      <Separator />
      <Panel id="d" style={{ overflow: "visible" }} defaultSize="45%" minSize="20%"><GraphPanel /></Panel>
    </Group>
  ) : (
    <Group style={{ overflow: "visible" }} orientation="vertical" id="right-a" defaultLayout={load("right-a")} onLayoutChanged={save("right-a")}>
      <Panel id="b" style={{ overflow: "visible" }} defaultSize="52%" minSize="20%"><HistoryPanel /></Panel>
      <Separator />
      <Panel id="bottom" style={{ overflow: "visible" }} defaultSize="48%" minSize="20%">
        <Group style={{ overflow: "visible" }} orientation="horizontal" id="bottom-a" defaultLayout={load("bottom-a")} onLayoutChanged={save("bottom-a")}>
          <Panel id="c" style={{ overflow: "visible" }} defaultSize="55%" minSize="25%"><TablePanel /></Panel>
          <Separator />
          <Panel id="d" style={{ overflow: "visible" }} defaultSize="45%" minSize="25%"><GraphPanel /></Panel>
        </Group>
      </Panel>
    </Group>
  );

  return (
    <div className="workspace">
      {connection === "reconnecting" && <div className="banner grey" role="status">Reconnecting…</div>}
      {server.synthetic && <div className="banner warn">Sample corpus (50 hand-written essays): for testing only. Do not report results from it.</div>}
      <div className="workspace-body">
        <Group style={{ overflow: "visible" }} orientation="horizontal" id={`outer-${mode}`} defaultLayout={load(`outer-${mode}`)} onLayoutChanged={save(`outer-${mode}`)}>
          <Panel id="a" style={{ overflow: "visible" }} defaultSize={baseline ? "40%" : "34%"} minSize={380}><ChatPanel /></Panel>
          <Separator />
          <Panel id="rest" style={{ overflow: "visible" }} defaultSize={baseline ? "60%" : "66%"} minSize="30%">{right}</Panel>
        </Group>
      </div>
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
