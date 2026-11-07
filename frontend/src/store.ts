import { create } from "zustand";
import { api } from "./api";
import { ApiError, FunctionCard, Mode, ServerState, TraceStep } from "./types";

export interface Selection {
  hoverCardId: number | null;
  hoverEssayId: number | null;
  focusTurnId: number | null;
  focusClusterId: number | null;
  selectedEssayId: number | null;
  brushIds: number[] | null;
  flashCardId: number | null;
  flashTurnId: number | null;
  popoverCardId: number | null;
}

/** State of the Pipeline Inspector (the panel that shows every backend step). */
export interface Inspector {
  open: boolean;
  turn: number | "all";      // which answered turn to show (-1 = session start)
  follow: boolean;           // scroll to the newest step while the backend works
  focusStep: number | null;
}

interface Working {
  kind: "start" | "answer" | "review" | "skip";
  stage: string;
  since: number;
  cancelled: boolean;
}

export interface Provisional {
  text: string;
  score?: number;
  keywords?: string[];
  specification?: string;
}

interface Store {
  screen: "loading" | "start" | "work";
  server: ServerState | null;
  working: Working | null;
  provisional: Provisional | null;
  liveCards: FunctionCard[];
  notices: { turn: number; text: string }[];
  error: { message: string; retry: () => void } | null;
  connection: "ok" | "reconnecting";
  draft: string;
  toast: string | null;
  sel: Selection;
  maxPanel: "history" | "table" | "graph" | null;
  newFids: number[];
  eps: number | null;
  trace: TraceStep[];
  inspector: Inspector;

  init(): Promise<void>;
  startSession(genre: string, mode: Mode): Promise<void>;
  send(text: string): Promise<void>;
  retryAnswer(text: string): Promise<void>;
  review(fid: number, decision: "accept" | "reject" | "refine", source: string, feedback?: string): Promise<void>;
  revisit(fid: number, decision: "accept" | "reject", source: string): Promise<void>;
  skip(kind: "next" | "topic"): Promise<void>;
  cancel(): Promise<void>;
  setDraft(t: string): void;
  select(p: Partial<Selection>): void;
  setMaxPanel(p: Store["maxPanel"]): void;
  setEps(eps: number | null): Promise<void>;
  showToast(t: string): void;
  startOver(): void;
  loadTrace(): Promise<void>;
  setInspector(p: Partial<Inspector>): void;
  openInspector(turn?: number | "all", step?: number): void;
}

const NO_SEL: Selection = {
  hoverCardId: null, hoverEssayId: null, focusTurnId: null, focusClusterId: null, selectedEssayId: null,
  brushIds: null, flashCardId: null, flashTurnId: null, popoverCardId: null,
};

let controller: AbortController | null = null;
let toastTimer: number | undefined;
let stageStart: { stage: string; at: number } | null = null;

const logStage = (stage: string | null) => {
  const now = performance.now();
  if (stageStart) api.event("wait_end", { stage: stageStart.stage, duration: Math.round(now - stageStart.at) });
  stageStart = stage ? { stage, at: now } : null;
  if (stage) api.event("wait_start", { stage });
};

export const useStore = create<Store>((set, get) => {
  const adopt = (s: ServerState, extra: Partial<Store> = {}) => {
    const before = get().server?.table.fids ?? [];
    const added = s.table.fids.filter((f) => !before.includes(f));
    set({ server: s, screen: "work", working: null, provisional: null, liveCards: [], newFids: added, ...extra });
    void get().loadTrace();
    if (added.length) window.setTimeout(() => set({ newFids: [] }), 1300);
  };

  /** Network failure: show the grey banner, retry with backoff, then rebuild everything from the server. */
  const reconnect = async () => {
    set({ connection: "reconnecting" });
    for (let wait = 1000; ; wait = Math.min(wait * 2, 8000)) {
      await new Promise((r) => setTimeout(r, wait));
      try {
        const s = await api.state(get().eps);
        set({ connection: "ok" });
        adopt(s);
        return;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          set({ connection: "ok", screen: "start", server: null });
          return;
        }
      }
    }
  };

  const fail = (e: unknown, retry: () => void) => {
    if (e instanceof ApiError && e.network) {
      set({ working: null, provisional: null, liveCards: [] });
      void reconnect();
      return;
    }
    const message = e instanceof ApiError ? e.message : "Something went wrong.";
    set({ working: null, error: { message: `Something went wrong. Your answer was saved. Try again. (${message})`, retry } });
  };

  return {
    screen: "loading", server: null, working: null, provisional: null, liveCards: [], notices: [], error: null,
    connection: "ok", draft: "", toast: null, sel: NO_SEL, maxPanel: null, newFids: [], eps: null,
    trace: [], inspector: { open: false, turn: "all", follow: true, focusStep: null },

    async init() {
      try {
        adopt(await api.state());
      } catch (e) {
        if (e instanceof ApiError && e.network) void reconnect();
        else set({ screen: "start" });
      }
    },

    async startSession(genre, mode) {
      set({ working: { kind: "start", stage: "Starting…", since: Date.now(), cancelled: false }, error: null, notices: [], sel: NO_SEL });
      try {
        adopt(await api.start(genre, mode));
      } catch (e) {
        fail(e, () => void get().startSession(genre, mode));
      }
    },

    async send(text) {
      const { server, working } = get();
      if (!server || working || !text.trim()) return;
      text = text.trim();
      const turn = server.turns[server.turns.length - 1];
      api.event("answer_submit", { turnId: turn?.id, length: text.length });
      // Show the pipeline as soon as an answer is sent: readings, matrix, score appear live.
      set((s) => ({ inspector: { ...s.inspector, open: true, turn: server.turns.length - 1, follow: true, focusStep: null } }));
      controller = new AbortController();
      set({
        working: { kind: "answer", stage: "One moment…", since: Date.now(), cancelled: false },
        provisional: { text }, liveCards: [], error: null, draft: "",
      });
      logStage("One moment…");
      const turnIdx = server.turns.length - 1;
      try {
        const done = await api.answerStream(text, {
          onStage: (t) => { logStage(t); set((s) => (s.working ? { working: { ...s.working, stage: t } } : {})); },
          onScored: (e) => {
            api.event("scored", { turnId: turn?.id, softness: e.score });
            set((s) => ({ provisional: s.provisional ? { ...s.provisional, score: e.score, keywords: e.keywords, specification: e.specification } : s.provisional }));
          },
          onTrace: (st) => set((s) => ({ trace: [...s.trace.filter((x) => x.id !== st.id), st].sort((a, b) => a.id - b.id) })),
          onCard: (c) => set((s) => ({ liveCards: [...s.liveCards.filter((x) => x.id !== c.id), c] })),
          onNotice: (t) => set((s) => ({ notices: [...s.notices, { turn: turnIdx, text: t }] })),
        }, controller.signal);
        logStage(null);
        const n = done.functions.filter((f) => f.turn === turnIdx).length;
        if (n) api.event("cards_generated", { turnId: turn?.id, count: n, retries: 0 });
        adopt(done);
      } catch (e) {
        logStage(null);
        set({ draft: text });
        fail(e, () => void get().retryAnswer(text));
      }
    },

    async review(fid, decision, source, feedback) {
      if (get().working) return;
      api.event(decision === "refine" ? "card_refine" : "card_decision", decision === "refine" ? { cardId: fid, text: feedback } : { cardId: fid, from: "pending", to: decision === "accept" ? "accepted" : "rejected", source });
      set({ working: { kind: "review", stage: decision === "refine" ? "Planning…" : "One moment…", since: Date.now(), cancelled: false }, error: null });
      let timer: number | undefined;
      if (decision === "refine") {
        const stages = ["Planning…", "Writing code…", "Checking the code…", "Trying it on sample essays…"];
        let k = 0;
        timer = window.setInterval(() => set((s) => (s.working ? { working: { ...s.working, stage: stages[++k % stages.length] } } : {})), 1800);
      }
      try {
        adopt(await api.review(fid, decision, feedback));
      } catch (e) {
        fail(e, () => void get().review(fid, decision, source, feedback));
      } finally {
        if (timer) clearInterval(timer);
      }
    },

    async revisit(fid, decision, source) {
      if (get().working) return;
      const card = get().server?.functions.find((f) => f.id === fid);
      api.event("card_decision", { cardId: fid, from: card?.status, to: decision === "accept" ? "accepted" : "rejected", source });
      try {
        adopt(await api.revisit(fid, decision), { toast: "Changed" });
        window.setTimeout(() => set({ toast: null }), 1500);
      } catch (e) {
        fail(e, () => void get().revisit(fid, decision, source));
      }
    },

    async skip(kind) {
      if (get().working) return;
      set({ working: { kind: "skip", stage: "One moment…", since: Date.now(), cancelled: false }, error: null });
      try {
        adopt(await api.skip(kind));
      } catch (e) {
        fail(e, () => void get().skip(kind));
      }
    },

    async cancel() {
      set((s) => (s.working ? { working: { ...s.working, cancelled: true, stage: "Cancelling…" } } : {}));
      try {
        await api.cancel();
      } catch {
        /* the stream keeps running and will finish on its own */
      }
    },

    // A failed answer may already have been recorded server-side: check before sending it again.
    async retryAnswer(text: string) {
      set({ error: null });
      try {
        const s = await api.state();
        const last = s.turns[s.turns.length - 1];
        if (!s.awaiting_answer || s.pending.length || (last && last.answer === text)) { adopt(s); return; }
      } catch (e) {
        fail(e, () => void get().retryAnswer(text));
        return;
      }
      await get().send(text);
    },

    setDraft: (draft) => set({ draft }),
    select: (p) => set((s) => ({ sel: { ...s.sel, ...p } })),
    setMaxPanel: (maxPanel) => set({ maxPanel }),
    async setEps(eps) {
      set({ eps });
      try { set({ server: await api.state(eps) }); } catch { /* keep the old picture */ }
    },
    showToast(t) {
      window.clearTimeout(toastTimer);
      set({ toast: t });
      toastTimer = window.setTimeout(() => set({ toast: null }), 3000);
    },
    async loadTrace() {
      try { set({ trace: await api.trace() }); } catch { /* the inspector keeps what it has */ }
    },
    setInspector: (p) => set((s) => ({ inspector: { ...s.inspector, ...p } })),
    openInspector(turn, step) {
      set((s) => ({ inspector: { ...s.inspector, open: true, turn: turn ?? s.inspector.turn, focusStep: step ?? null } }));
    },
    startOver() {
      set({ trace: [], screen: "start", server: null, working: null, provisional: null, liveCards: [], notices: [], error: null, sel: NO_SEL, draft: "", maxPanel: null });
    },
  };
});

/** Cards to show: the server's, plus any streamed in this request that the server state does not have yet. */
export function allCards(server: ServerState | null, live: FunctionCard[]): FunctionCard[] {
  const base = server?.functions ?? [];
  return [...base, ...live.filter((c) => !base.some((b) => b.id === c.id))];
}

export function isLocked(st: Pick<Store, "server" | "working" | "liveCards">): boolean {
  const s = st.server;
  if (!s || st.working) return true;
  const pending = s.pending.length > 0 || st.liveCards.some((c) => c.status === "pending");
  return pending || !s.awaiting_answer;
}
