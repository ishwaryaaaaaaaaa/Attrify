export type QuestionType = "open_ended" | "clarify" | "suggest" | "chat";
export type CardStatus = "pending" | "accepted" | "rejected" | "refined";
export type Mode = "attrify" | "baseline";

export interface Turn {
  i: number;
  id: string;
  blockId: number;
  qtype: QuestionType;
  question: string;
  answer: string;
  softness: number | null;
  new_block: boolean;
  specification: string;
  keywords: string[];
  cardIds: number[];
}

export interface Example {
  id: number;
  excerpt: string;
  value: number;
}

export interface FunctionCard {
  id: number;
  name: string;
  description: string;
  steps: string[];
  methodType: string;
  code: string;
  status: CardStatus;
  samples: number[];
  warnings: string[];
  turn: number;
  sameShare: number | null;
  modalValue: number | null;
  examples: Example[];
  supersededBy: number | null;
  similarTo: string | null;
  refineNote?: string | null;
}

export interface TableRow {
  id: number;
  text: string;
  values: number[];
  cluster: number;
}

export interface TableData {
  names: string[];
  fids: number[];
  hists: { counts: number[]; edges: number[] }[];
  rows: TableRow[];
}

export interface Coverage {
  points: [number, number][];
  ids: number[];
  labels: number[];
  largest: number | null;
  explained: [number, number];
  eps: number | null;
}

export interface ServerState {
  synthetic: boolean;
  mode: Mode;
  genre: string;
  n_essays: number;
  turns: Turn[];
  functions: FunctionCard[];
  pending: number[];
  awaiting_answer: boolean;
  current_question: string | null;
  can_skip: boolean;
  table: TableData;
  coverage: Coverage;
  last?: { score: number | null; action: string; failures: string[] };
}

export interface ScoredEvent {
  score: number;
  action: string;
  specification: string;
  keywords: string[];
}

export type VizBlock =
  | { type: "readings"; items: { label: string; description: string }[] }
  | { type: "matrix"; title?: string; labels: string[]; values: number[][] }
  | { type: "bars"; title?: string; labels: string[]; values: number[] }
  | { type: "code"; title?: string; code: string }
  | { type: "formula"; lines: string[] }
  | { type: "table"; title?: string; columns: string[]; rows: (string | number)[][] };

/** One recorded backend step (see pipeline_trace.py). */
export interface TraceStep {
  id: number;
  turn: number;
  t: number;
  ms: number | null;
  agent: string;
  step: string;
  kind: "llm" | "compute" | "sandbox" | "decision" | "io";
  status: "ok" | "retry" | "error";
  note: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  viz: VizBlock[];
  llm?: { model: string; temperature: number; system: string; user: string; response: string | null };
}

export interface StreamHandlers {
  onStage: (text: string) => void;
  onTrace?: (s: TraceStep) => void;
  onScored: (e: ScoredEvent) => void;
  onCard: (c: FunctionCard) => void;
  onNotice: (text: string) => void;
}

export interface Api {
  start(genre: string, mode: Mode): Promise<ServerState>;
  state(eps?: number | null): Promise<ServerState>;
  answerStream(text: string, h: StreamHandlers, signal: AbortSignal): Promise<ServerState>;
  review(fid: number, decision: "accept" | "reject" | "refine", feedback?: string): Promise<ServerState>;
  revisit(fid: number, decision: "accept" | "reject"): Promise<ServerState>;
  skip(kind: "next" | "topic"): Promise<ServerState>;
  examples(fid: number, exclude: number[]): Promise<Example[]>;
  essay(id: number): Promise<{ id: number; text: string; names: string[]; values: number[] }>;
  cancel(): Promise<void>;
  event(name: string, data?: Record<string, unknown>): void;
  log(): Promise<unknown[]>;
  trace(): Promise<TraceStep[]>;
}

export class ApiError extends Error {
  status: number;
  network: boolean;
  constructor(message: string, status = 0, network = false) {
    super(message);
    this.status = status;
    this.network = network;
  }
}
