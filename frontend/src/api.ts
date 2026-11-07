import { Api, ApiError, Example, FunctionCard, Mode, ScoredEvent, ServerState, StreamHandlers, TraceStep } from "./types";
import { mockApi } from "./mock";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, init);
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("Cannot reach the server.", 0, true);
  }
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    /* non-JSON error body */
  }
  if (!r.ok) {
    const detail = (body as { detail?: string } | null)?.detail;
    throw new ApiError(detail || r.statusText || "Request failed", r.status);
  }
  return body as T;
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

/** Minimal Server-Sent Events reader over fetch (EventSource cannot POST). */
async function stream(path: string, body: unknown, signal: AbortSignal, onEvent: (kind: string, data: any) => void) {
  let r: Response;
  try {
    r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("Cannot reach the server.", 0, true);
  }
  if (!r.ok || !r.body) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail || detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, r.status);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let cut: number;
    while ((cut = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, cut);
      buf = buf.slice(cut + 2);
      let kind = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) kind = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) onEvent(kind, JSON.parse(data));
    }
  }
}

const realApi: Api = {
  start: (genre: string, mode: Mode) => post<ServerState>("/api/session", { genre, mode }),
  state: (eps) => request<ServerState>("/api/state" + (eps ? `?eps=${eps}` : "")),
  async answerStream(text: string, h: StreamHandlers, signal: AbortSignal) {
    let done: ServerState | null = null;
    let failure: ApiError | null = null;
    await stream("/api/answer/stream", { text }, signal, (kind, d) => {
      if (kind === "stage") h.onStage(d.text);
      else if (kind === "scored") h.onScored(d as ScoredEvent);
      else if (kind === "trace") h.onTrace?.(d as TraceStep);
      else if (kind === "card") h.onCard(d as FunctionCard);
      else if (kind === "notice") h.onNotice(d.text);
      else if (kind === "done") done = d as ServerState;
      else if (kind === "error") failure = new ApiError(d.message, d.status);
    });
    if (failure) throw failure;
    if (!done) throw new ApiError("The connection closed before the answer finished.", 0, true);
    return done;
  },
  review: (fid, decision, feedback) => post<ServerState>("/api/review", { fid, decision, feedback }),
  revisit: (fid, decision) => post<ServerState>("/api/revisit", { fid, decision }),
  skip: (kind) => post<ServerState>(`/api/skip?kind=${kind}`),
  async examples(fid: number, exclude: number[]): Promise<Example[]> {
    const r = await request<{ examples: Example[] }>(`/api/cards/${fid}/examples?n=3&exclude=${exclude.join(",")}`);
    return r.examples;
  },
  essay: (id) => request(`/api/essay/${id}`),
  async cancel() {
    await post("/api/cancel");
  },
  event(name, data) {
    post("/api/event", { name, data: data ?? {} }).catch(() => undefined);
  },
  log: () => request<unknown[]>("/api/log"),
  async trace() {
    return (await request<{ steps: TraceStep[] }>("/api/trace")).steps;
  },
};

export const MOCK = new URLSearchParams(location.search).has("mock");
export const api: Api = MOCK ? mockApi : realApi;
