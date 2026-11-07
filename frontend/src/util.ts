import { api } from "./api";
import { ServerState } from "./types";

export const CLUSTER_COLORS = ["#7aa2e8", "#e88a8a", "#7fc98a", "#a58be0", "#e8a96a"];
export const clusterColor = (c: number) => (c < 0 ? "#9aa3b5" : CLUSTER_COLORS[c % CLUSTER_COLORS.length]);

export const snake = (name: string) =>
  name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "attribute";

export const QTYPE_LABEL: Record<string, string> = { open_ended: "Open-ended", clarify: "Clarifying", suggest: "Suggestion", chat: "Chat" };

export function fmt(v: number): string {
  return Number.isFinite(v) ? v.toFixed(3) : "";
}

/** Share of the most common value in a column (rounded to 6 places), and that value. */
export function modalShare(values: number[]): { share: number; value: number } {
  const counts = new Map<number, number>();
  for (const v of values) {
    const k = Math.round(v * 1e6) / 1e6;
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  let best = 0;
  let bestV = 0;
  counts.forEach((n, v) => {
    if (n > best) { best = n; bestV = v; }
  });
  return { share: values.length ? best / values.length : 0, value: bestV };
}

function download(filename: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const csvCell = (s: string | number) => {
  const t = String(s);
  return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
};

export function exportTable(s: ServerState): string {
  const header = ["essay_id", ...s.table.names.map(snake)];
  const lines = [header.join(",")];
  for (const r of s.table.rows) lines.push([r.id, ...r.values].map(csvCell).join(","));
  download("attrify_table.csv", lines.join("\n"), "text/csv");
  api.event("export", { kind: "table" });
  return `Exported ${s.table.names.length} attributes for ${s.table.rows.length} essays.`;
}

export function exportFunctions(s: ServerState): string {
  const acc = s.functions.filter((f) => f.status === "accepted");
  const parts = ["# Accepted AttriFy attributes. Each function takes an essay string and returns a float.\n"];
  for (const f of acc) {
    parts.push(`# ${f.name}: ${f.description.replace(/\n/g, " ")}\n` + f.code.replace(/def\s+score\s*\(/, `def ${snake(f.name)}(`));
  }
  download("attrify_functions.py", parts.join("\n\n"), "text/x-python");
  api.event("export", { kind: "functions" });
  return `Exported ${acc.length} functions.`;
}

export async function exportLog(): Promise<string> {
  const log = await api.log();
  download("attrify_session_log.json", JSON.stringify(log, null, 2), "application/json");
  api.event("export", { kind: "log" });
  return "Downloaded the session log.";
}

export function exportTrace(steps: unknown[]): string {
  download("attrify_pipeline_trace.json", JSON.stringify(steps, null, 2), "application/json");
  api.event("export", { kind: "trace" });
  return `Downloaded ${steps.length} pipeline steps.`;
}
