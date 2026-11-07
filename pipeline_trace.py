"""Pipeline trace: every backend step (LLM call, computation, decision) is recorded with what went in and
what came out, so the UI's Pipeline Inspector can show the whole process.

A step is a JSON-able dict:
  id, turn (index of the answered turn it belongs to; -1 = before the first answer), t (epoch seconds),
  ms, agent, step, kind ("llm" | "compute" | "sandbox" | "decision" | "io"), status ("ok" | "retry" | "error"),
  note (plain words: what happens here), inputs {..}, outputs {..},
  llm {model, temperature, system, user, response}  (LLM steps only),
  viz [ {type: readings|matrix|bars|code|formula|table, ...} ]  (pictures the UI draws).

Usage: wrap the LLM client with TracedLLM; label calls with `with scope(agent, step):`; add other steps
with add(...); add parse results to the call just made with attach(...). The tracer never sees API keys:
only the prompts and responses are stored.
"""
import contextvars
import json
import threading
import time

_scope: contextvars.ContextVar = contextvars.ContextVar("pipeline_scope", default=None)
_last: contextvars.ContextVar = contextvars.ContextVar("pipeline_last_llm", default=None)


class Tracer:
    def __init__(self, path=None, turn_fn=None):
        self.steps, self.path, self.turn_fn, self.listener = [], path, turn_fn, None
        self._lock = threading.Lock()

    def _turn(self):
        try:
            return int(self.turn_fn()) if self.turn_fn else -1
        except Exception:
            return -1

    def add(self, agent, step, kind="compute", note="", inputs=None, outputs=None, viz=None, ms=None,
            status="ok", llm=None):
        with self._lock:
            rec = {"id": len(self.steps), "turn": self._turn(), "t": time.time(), "ms": ms, "agent": agent,
                   "step": step, "kind": kind, "status": status, "note": note, "inputs": inputs or {},
                   "outputs": outputs or {}, "viz": viz or []}
            if llm is not None:
                rec["llm"] = llm
            self.steps.append(rec)
        self._emit(rec)
        return rec

    def update(self, rec, **fields):
        with self._lock:
            for k, v in fields.items():
                if k in ("inputs", "outputs") and isinstance(v, dict):
                    rec[k] = {**rec.get(k, {}), **v}
                elif k == "viz" and isinstance(v, list):
                    rec["viz"] = rec.get("viz", []) + v
                else:
                    rec[k] = v
        self._emit(rec)

    def _emit(self, rec):
        fn = self.listener
        if fn:
            try:
                fn(rec)
            except Exception:
                pass

    def save(self):
        if not self.path:
            return
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.steps, f, default=str)
        except OSError:
            pass


TRACER = Tracer()


def new_tracer(path=None, turn_fn=None):
    """Start a fresh trace (called when a session starts)."""
    global TRACER
    TRACER = Tracer(path, turn_fn)
    return TRACER


def add(*a, **k):
    return TRACER.add(*a, **k)


class scope:
    """`with scope("Softness Agent", "Restate"):` labels every LLM call made inside it."""

    def __init__(self, agent, step, note=""):
        self.v = {"agent": agent, "step": step, "note": note}

    def __enter__(self):
        self.tok = _scope.set(self.v)
        return self

    def __exit__(self, *exc):
        _scope.reset(self.tok)


def current():
    return _scope.get() or {}


def attach(**fields):
    """Add parse results (outputs=..., viz=[...], status=...) to the LLM step made last in this context."""
    rec = _last.get()
    if rec is not None:
        TRACER.update(rec, **fields)
    return rec


def note_retry(reason):
    """A model answer that could not be parsed: mark its step and keep going (the caller retries)."""
    attach(status="retry", outputs={"problem": str(reason)})


class TracedLLM:
    """Wraps any llm(system, user, model, temperature) callable and records each call as a step."""

    def __init__(self, inner):
        self.inner = inner

    def __call__(self, system, user, model, temperature):
        sc = current()
        info = {"model": model, "temperature": temperature, "system": system, "user": user}
        t0 = time.perf_counter()
        try:
            out = self.inner(system, user, model, temperature)
        except Exception as e:
            rec = TRACER.add(sc.get("agent", "LLM"), sc.get("step", "LLM call"), kind="llm", note=sc.get("note", ""),
                             ms=round((time.perf_counter() - t0) * 1000), status="error",
                             llm={**info, "response": None}, outputs={"error": f"{type(e).__name__}: {e}"})
            _last.set(rec)
            raise
        rec = TRACER.add(sc.get("agent", "LLM"), sc.get("step", "LLM call"), kind="llm", note=sc.get("note", ""),
                         ms=round((time.perf_counter() - t0) * 1000), llm={**info, "response": out})
        _last.set(rec)
        return out
