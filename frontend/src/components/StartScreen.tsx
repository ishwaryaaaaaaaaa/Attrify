import { useState } from "react";
import { MOCK } from "../api";
import { useStore } from "../store";
import { Mode } from "../types";

export function StartScreen() {
  const startSession = useStore((s) => s.startSession);
  const working = useStore((s) => s.working);
  const error = useStore((s) => s.error);
  const [genre, setGenre] = useState("argumentative");
  const [mode, setMode] = useState<Mode>("attrify");
  const starting = working?.kind === "start";

  return (
    <main className="start">
      <h1>AttriFy</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        Turn a soft idea, like “a good essay”, into numbers you can inspect. {MOCK && <b>(Mock server: no real model is called.)</b>}
      </p>

      <div className="tutorial">
        <div className="card"><h4>1 · Say what you care about</h4>Describe what you care about in your own words. It can be vague.</div>
        <div className="card"><h4>2 · Review the ideas</h4>I will suggest ways to measure it. Accept, reject, or refine each one.</div>
        <div className="card"><h4>3 · Check the numbers</h4>Accepting means it is relevant to you, not that it has been proven correct. Check the sample values.</div>
      </div>

      <h4 style={{ marginBottom: 4 }}>Dataset</h4>
      <div className="pick" role="radiogroup" aria-label="Dataset">
        {[["argumentative", "Argumentative essays"], ["narrative", "Narrative essays"]].map(([v, l]) => (
          <label key={v}><input type="radio" name="genre" checked={genre === v} onChange={() => setGenre(v)} /> {l}</label>
        ))}
      </div>
      <h4 style={{ marginBottom: 4 }}>Condition</h4>
      <div className="pick" role="radiogroup" aria-label="Condition">
        <label><input type="radio" name="mode" checked={mode === "attrify"} onChange={() => setMode("attrify")} /> AttriFy (guided by softness)</label>
        <label><input type="radio" name="mode" checked={mode === "baseline"} onChange={() => setMode("baseline")} /> Baseline (plain chat)</label>
      </div>

      {error && <div className="banner red" role="alert" style={{ margin: "8px 0" }}>{error.message}</div>}
      <button className="btn primary" style={{ padding: "6px 22px", fontSize: 14, borderRadius: 18 }} disabled={starting} onClick={() => void startSession(genre, mode)}>
        {starting ? "Starting…" : "Start"}
      </button>
      {starting && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 8, marginTop: 18, height: 120 }} aria-hidden>
          <div className="skeleton" /><div className="skeleton" />
        </div>
      )}
    </main>
  );
}
