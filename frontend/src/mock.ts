// In-browser mock of the server, used with ?mock=1 so the whole UI can be tried (and tested) with no
// LLM and no backend. It imitates the API contract only: scores follow a script (70, 45, 20, ...),
// cards come from a fixed library, and the projection is NOT a real PCA/DBSCAN.
import { Api, ApiError, Example, FunctionCard, Mode, ServerState, StreamHandlers, Turn } from "./types";

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((res, rej) => {
    const t = setTimeout(res, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      rej(new DOMException("Aborted", "AbortError"));
    });
  });

const OPEN = "What makes an argumentative essay good in your view? Describe something that matters to you in your own words.";
const SUGGEST =
  "Before we continue, do you have any additional thoughts or suggestions you'd like to explore? You can describe something entirely new or build on what we've discussed. Otherwise, we'll move on to the next question.";
const CLARIFY = ["Do you mean novelty in methodology, domain, or findings?", "Does the stance have to stay the same through the whole essay?", "Should evidence be numbers, quotes, or both?"];
const SCORES = [70, 45, 20, 62, 28, 55];

const WORDS = ["schools", "homework", "phones", "sleep", "cities", "parks", "remote", "work", "uniforms", "exams"];
const ESSAYS = Array.from({ length: 60 }, (_, i) => {
  const w = WORDS[i % WORDS.length];
  const should = i % 3 !== 1;
  const nums = i % 4 === 0 ? " A 2021 survey found 62% agreed." : "";
  const long = i % 5 === 0 ? " Furthermore, many people argue about " + w + " in many different ways." : "";
  return { id: 100 + i * 7, text: `${should ? "Schools should change their " + w + " policy" : "In my opinion " + w + " matter"}. My friends said so too.${nums}${long} Cats are fine.` };
});

const LIB: { name: string; description: string; steps: string[]; methodType: string; fn: (t: string) => number }[] = [
  { name: "Thesis statement presence", description: "Checks whether the first paragraph has a thesis claim word.", steps: ["Split the essay into paragraphs.", "Take the first paragraph and split it into sentences.", "Score 1 if any sentence contains a claim word (should, must, I believe), else 0."], methodType: "word-list check", fn: (t) => (/\b(should|must|believe)\b/i.test(t) ? 1 : 0) },
  { name: "Evidence numbers", description: "Counts digit runs such as years and percentages.", steps: ["Find every run of digits in the essay.", "Return how many were found."], methodType: "surface statistic", fn: (t) => (t.match(/\d+/g) || []).length },
  { name: "Sentence length variance", description: "Variance of sentence lengths in words.", steps: ["Split the essay into sentences.", "Count words in each.", "Return the variance."], methodType: "surface statistic", fn: (t) => { const s = t.split(/[.!?]+/).map((x) => x.trim().split(/\s+/).filter(Boolean).length).filter((n) => n > 0); const m = s.reduce((a, b) => a + b, 0) / (s.length || 1); return s.reduce((a, b) => a + (b - m) ** 2, 0) / (s.length || 1); } },
  { name: "Hedging words", description: "Counts hedges like maybe, perhaps, many.", steps: ["Lower-case the essay.", "Count words from a hedge list."], methodType: "word-list check", fn: (t) => (t.match(/\b(many|maybe|perhaps|some|furthermore)\b/gi) || []).length },
];

interface MockState {
  mode: Mode;
  genre: string;
  turns: Turn[];
  funcs: FunctionCard[];
  blockStart: number;
  step: number;
  awaiting: boolean;
  nextAction: "clarify" | "suggest" | "chat";
  log: unknown[];
}
let M: MockState | null = null;

const colOf = (fid: number) => ESSAYS.map((e) => LIB[fid % LIB.length].fn(e.text));

function snapshot(): ServerState {
  if (!M) throw new ApiError("No session. Start one first.", 409);
  const accepted = M.funcs.filter((f) => f.status === "accepted");
  const cols = accepted.map((f) => colOf(f.id));
  const hists = cols.map((c) => {
    const lo = Math.min(...c), hi = Math.max(...c) || 1, bins = 11;
    const counts = new Array(bins).fill(0);
    c.forEach((v) => (counts[Math.min(bins - 1, Math.floor(((v - lo) / ((hi - lo) || 1)) * bins))] += 1));
    return { counts, edges: Array.from({ length: bins + 1 }, (_, i) => lo + ((hi - lo) * i) / bins) };
  });
  const z = cols.map((c) => { const m = c.reduce((a, b) => a + b, 0) / c.length; const sd = Math.sqrt(c.reduce((a, b) => a + (b - m) ** 2, 0) / c.length) || 1; return c.map((v) => (v - m) / sd); });
  const labels = ESSAYS.map((_, i) => (z.length === 0 ? -1 : z.length < 2 ? (z[0][i] > 0 ? 0 : 1) : Math.abs(z[0][i]) > 2 ? -1 : z[0][i] * z[1][i] > 0 ? 0 : 1));
  const points: [number, number][] = ESSAYS.map((_, i) => [z[0]?.[i] ?? 0, z[1]?.[i] ?? 0]);
  const counts: Record<number, number> = {};
  labels.forEach((l) => l >= 0 && (counts[l] = (counts[l] || 0) + 1));
  const largest = Object.keys(counts).length ? Number(Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0]) : null;
  const pending = M.funcs.filter((f) => f.status === "pending").map((f) => f.id);
  const last = M.turns[M.turns.length - 1];
  const turns = M.turns.map((t, i) => ({ ...t, i, id: `t${i}`, cardIds: M!.funcs.filter((f) => f.turn === i).map((f) => f.id), new_block: i === 0 || i === M!.blockStart }));
  let block = -1;
  turns.forEach((t) => { if (t.new_block) block += 1; t.blockId = block; });
  return {
    synthetic: true, mode: M.mode, genre: M.genre, n_essays: ESSAYS.length, turns, functions: M.funcs.map(withExamples), pending,
    awaiting_answer: M.awaiting, current_question: last && M.awaiting ? last.question : null,
    can_skip: !!last && M.awaiting && last.qtype === "suggest",
    table: { names: accepted.map((f) => f.name), fids: accepted.map((f) => f.id), hists, rows: ESSAYS.map((e, i) => ({ id: e.id, text: e.text.slice(0, 60), values: cols.map((c) => c[i]), cluster: labels[i] })) },
    coverage: { points, ids: ESSAYS.map((e) => e.id), labels, largest, explained: [0.392, 0.267], eps: 0.8 },
  };
}

function withExamples(f: FunctionCard): FunctionCard {
  const c = colOf(f.id);
  const modal = [...c].sort((a, b) => c.filter((v) => v === b).length - c.filter((v) => v === a).length)[0];
  const order = c.map((_, i) => i).sort((a, b) => c[a] - c[b]);
  const ex: Example[] = [order[0], order[30], order[59]].map((i) => ({ id: ESSAYS[i].id, excerpt: ESSAYS[i].text.slice(0, 90), value: c[i] }));
  return { ...f, sameShare: c.filter((v) => v === modal).length / c.length, modalValue: modal, examples: ex };
}

function ask(qtype: Turn["qtype"], question: string) {
  M!.turns.push({ i: M!.turns.length, id: "", blockId: 0, qtype, question, answer: "", softness: null, new_block: false, specification: "", keywords: [], cardIds: [] });
  M!.awaiting = true;
}

const kw = (t: string) => t.toLowerCase().replace(/[^a-z ]/g, " ").split(/\s+/).filter((w) => w.length > 3).slice(0, 2);

export const mockApi: Api = {
  async start(genre, mode) {
    await sleep(400);
    M = { mode, genre, turns: [], funcs: [], blockStart: 0, step: 0, awaiting: false, nextAction: "clarify", log: [] };
    ask("open_ended", `${genre === "narrative" ? "Narrative" : "Argumentative"} essays. ${OPEN}`);
    return snapshot();
  },
  async state() { return snapshot(); },
  async answerStream(text: string, h: StreamHandlers, signal: AbortSignal) {
    if (!M || !M.awaiting) throw new ApiError("No question is awaiting an answer.", 400);
    if (M.funcs.some((f) => f.status === "pending")) throw new ApiError("Review every proposed card before answering the next question.", 409);
    if (/fail/i.test(text) && !(globalThis as { __failed?: boolean }).__failed) { (globalThis as { __failed?: boolean }).__failed = true; throw new ApiError("Cannot reach the server.", 0, true); }
    const turn = M.turns[M.turns.length - 1];
    turn.answer = text; turn.keywords = kw(text); M.awaiting = false;
    if (M.mode === "baseline") {
      h.onStage("Planning…"); await sleep(500, signal);
      h.onStage("Writing code…"); await sleep(500, signal);
      const f = pickCard(M.turns.length - 1); if (f) h.onCard(withExamples(f));
      ask("chat", "That makes sense. What else matters to you about this?");
      return snapshot();
    }
    h.onStage("Working out how open-ended this is…"); await sleep(900, signal);
    const score = /slow/i.test(text) ? 55 : SCORES[M.step % SCORES.length]; M.step += 1;
    turn.softness = score; turn.specification = `The user wants essays where: ${text.slice(0, 80)}`;
    const action = score >= 65 ? "clarify" : score > 30 ? "generate_then_clarify" : "generate_then_suggest";
    h.onScored({ score, action, specification: turn.specification, keywords: turn.keywords });
    if (action !== "clarify") {
      for (const stage of ["Planning…", "Writing code…", "Checking the code…", "Trying it on sample essays…"]) { h.onStage(stage); await sleep(/slow/i.test(text) ? 4500 : 500, signal); }
      const n = action === "generate_then_suggest" ? 2 : 1;
      for (let k = 0; k < n; k++) { const f = pickCard(M.turns.length - 1); if (f) { h.onCard(withExamples(f)); await sleep(300, signal); } }
      if (!M.funcs.some((f) => f.status === "pending")) h.onNotice("I couldn't turn that into a working measure. Let's clarify instead.");
    }
    if (!M.funcs.some((f) => f.status === "pending")) next(action);
    else M.nextAction = action === "generate_then_suggest" ? "suggest" : "clarify";
    return snapshot();
  },
  async review(fid, decision, feedback) {
    const f = M!.funcs[fid];
    if (f.status !== "pending") throw new ApiError(`Function ${fid} is not pending.`, 400);
    if (decision === "refine") {
      f.status = "refined"; f.refineNote = feedback;
      const n = pickCard(f.turn, "Refined " + f.name); if (n) f.supersededBy = n.id;
    } else f.status = decision === "accept" ? "accepted" : "rejected";
    if (!M!.funcs.some((x) => x.status === "pending") && M!.turns[M!.turns.length - 1].answer) next(M!.nextAction === "suggest" ? "generate_then_suggest" : "generate_then_clarify");
    return snapshot();
  },
  async revisit(fid, decision) {
    const f = M!.funcs[fid];
    if (f.status !== "accepted" && f.status !== "rejected") throw new ApiError("Only accepted/rejected cards can be flipped.", 400);
    f.status = decision === "accept" ? "accepted" : "rejected";
    return snapshot();
  },
  async skip(kind) {
    M!.turns[M!.turns.length - 1].answer = kind === "next" ? "(nothing to add)" : "(new topic)";
    M!.awaiting = false; M!.blockStart = M!.turns.length;
    ask("open_ended", "What do the essays in the biggest group have in common that you'd care about?");
    return snapshot();
  },
  async examples(fid, exclude) {
    const c = colOf(fid);
    const pool = ESSAYS.map((_, i) => i).filter((i) => !exclude.includes(ESSAYS[i].id)).sort(() => Math.random() - 0.5).slice(0, 3);
    return pool.map((i) => ({ id: ESSAYS[i].id, excerpt: ESSAYS[i].text.slice(0, 90), value: c[i] }));
  },
  async essay(id) {
    const e = ESSAYS.find((x) => x.id === id)!;
    const acc = M!.funcs.filter((f) => f.status === "accepted");
    return { id, text: e.text + " " + e.text, names: acc.map((f) => f.name), values: acc.map((f) => LIB[f.id % LIB.length].fn(e.text)) };
  },
  async cancel() { /* the mock has nothing to cancel */ },
  event(name, data) { M?.log.push({ event: "ui_" + name, ...data }); },
  async log() { return M?.log ?? []; },
  async trace() { return []; },   // the mock has no pipeline: run the real server (or dev_fake_server.py) to see steps
};

function pickCard(turn: number, name?: string): FunctionCard | null {
  const idx = M!.funcs.length;
  const lib = LIB[idx % LIB.length];
  if (idx >= 8) return null;
  const f: FunctionCard = { id: idx, name: name ?? lib.name, description: lib.description, steps: lib.steps, methodType: lib.methodType, code: `def score(text):\n    # ${lib.name}\n    return 0.0\n`, status: "pending", samples: [], warnings: [], turn, sameShare: null, modalValue: null, examples: [], supersededBy: null, similarTo: null };
  M!.funcs.push(f);
  return f;
}

function next(action: string) {
  if (action === "generate_then_suggest" || M!.nextAction === "suggest") ask("suggest", SUGGEST);
  else ask("clarify", CLARIFY[M!.turns.length % CLARIFY.length]);
}
