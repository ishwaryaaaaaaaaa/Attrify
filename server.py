"""FastAPI server for the AttriFy UI. Single local user, one global session.

Run (from attrify/):   python -m uvicorn server:app --port 8000
Env: OPENAI_API_KEY (+ ATTRIFY_BASE_URL / ATTRIFY_*_MODEL) as in config.py
     The essays live in a SQLite database, data/attrify.db (fixed: essays cannot be changed or deleted).
     ATTRIFY_CORPUS_CSV, ATTRIFY_TEXT_COL (default full_text), ATTRIFY_N (default 200)
     -> imports a real corpus into the database once. Otherwise the 50 hand-written sample essays are used
     and flagged in the UI.

The React app (frontend/, built to frontend/dist) is served at "/". If it has not been built,
the older single-file ui.html is served instead.
"""
import json
import os
import queue
import random
import threading
import time

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import attribute_table as AT
import config
import corpus as C
from baseline import BaselineSession
import pipeline_trace as PT
import registry as R
import sandbox
import session as SE
import softness as S

app = FastAPI(title="AttriFy")
LOCK = threading.Lock()
STATE = {"sess": None, "fturn": {}, "synthetic": True, "preview": {}, "genre": "argumentative", "dataset": "sample"}
HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "frontend", "dist")


class StartReq(BaseModel):
    genre: str = "argumentative"
    mode: str = "attrify"          # "attrify" | "baseline"


class AnswerReq(BaseModel):
    text: str


class ReviewReq(BaseModel):
    fid: int
    decision: str
    feedback: str | None = None


class EventReq(BaseModel):
    name: str
    data: dict = {}


def _sess():
    if STATE["sess"] is None:
        raise HTTPException(409, "No session. Start one first.")
    return STATE["sess"]


def _advance(sess):
    """Ask the next question once nothing is pending and no answer is awaited."""
    if not sess.awaiting_answer and not sess.pending():
        sess.next_question()


# ----- cards -----
def _register_card(sess, f, turn=None):
    """Remember which turn made a card, and precompute its column over the corpus so the card
    can show 'same value on X% of essays' and sample essays before the user decides."""
    STATE["fturn"][f.id] = len(sess.history.turns) - 1 if turn is None else turn
    t0 = time.perf_counter()
    vals, err = sandbox.run(f.code, sess.table.texts)
    STATE["preview"][f.id] = None if err else [float(v) for v in vals]
    ms = round((time.perf_counter() - t0) * 1000)
    if err:
        PT.add("Attribute Table", f"Preview “{f.name}” on all essays (failed)", "sandbox", status="error", ms=ms,
               outputs={"error": err})
    else:
        arr = np.round(np.asarray(vals, dtype=float), 9)
        counts = np.unique(arr, return_counts=True)[1]
        PT.add("Attribute Table", f"Preview “{f.name}” on all essays", "sandbox",
               note="Before you decide, the function is run on every essay (it is not in the table yet) so the card can "
                    "show how many essays get the same value and which essays score lowest, middle and highest.",
               inputs={"essays": len(arr)},
               outputs={"min": round(float(arr.min()), 4), "max": round(float(arr.max()), 4),
                        "share_with_the_most_common_value": round(float(counts.max() / len(arr)), 3)}, ms=ms)
    accepted = [a for a in sess.registry.accepted() if a.id != f.id]
    if accepted and f.similar_to is None:
        try:                                       # name similarity > 0.9 -> "Looks similar to: ..."
            E = S.embed([f.name] + [a.name for a in accepted])
            sims = E[1:] @ E[0]
            if float(sims.max()) > 0.9:
                f.similar_to = accepted[int(sims.argmax())].name
            PT.add("Attribute Table", f"Similar-name check for “{f.name}”", "compute",
                   note="The new name is embedded and compared with the accepted names. Above 0.9 the card says 'Looks similar to…'.",
                   inputs={"new": f.name, "accepted": [a.name for a in accepted]},
                   outputs={"best_match": accepted[int(sims.argmax())].name, "cosine_similarity": round(float(sims.max()), 3),
                            "flagged": f.similar_to is not None})
        except Exception:
            pass


def _note_new_functions(sess, funcs, turn=None):
    for f in funcs:
        _register_card(sess, f, turn)


def _excerpt(sess, i, n=90):
    return sess.table.texts[i][:n]


def _examples(sess, fid, idx):
    vals = STATE["preview"].get(fid)
    if vals is None:
        return []
    return [{"id": sess.table.corpus[i]["id"], "excerpt": _excerpt(sess, i), "value": vals[i]} for i in idx]


def _func_json(f):
    sess = _sess()
    vals = STATE["preview"].get(f.id)
    same, modal, ex = None, None, []
    if vals:
        arr = np.round(np.asarray(vals), 9)
        uniq, counts = np.unique(arr, return_counts=True)
        modal, same = float(uniq[counts.argmax()]), float(counts.max() / len(arr))
        order = np.argsort(arr, kind="stable")
        pos = sorted({0, len(order) // 2, len(order) - 1})      # lowest, middle, highest value
        ex = _examples(sess, f.id, [int(order[p]) for p in pos])
    return {"id": f.id, "name": f.name, "description": f.description, "steps": f.steps,
            "methodType": f.method_type, "code": f.code, "status": f.status,
            "samples": f.sample_values, "warnings": f.warnings,
            "turn": STATE["fturn"].get(f.id, 0), "sameShare": same, "modalValue": modal,
            "examples": ex, "supersededBy": f.superseded_by, "similarTo": f.similar_to,
            "refineNote": f.refine_note}


# ----- state -----
def _state(eps=None):
    sess = _sess()
    h = sess.history
    block, turns = -1, []
    for i, t in enumerate(h.turns):
        is_new = i == 0 or (i == sess.block_start and i > 0)
        if is_new:
            block += 1
        turns.append({"i": i, "id": f"t{i}", "blockId": block, "qtype": t.qtype, "question": t.question,
                      "answer": t.answer, "softness": t.softness, "new_block": is_new,
                      "specification": t.specification, "keywords": t.keywords,
                      "cardIds": [fid for fid, tn in STATE["fturn"].items() if tn == i]})
    funcs = [_func_json(f) for f in sess.registry.funcs]
    t = sess.table
    P, labels = t.clusters(eps)
    table = {"names": t.names, "fids": t.fids, "hists": [], "rows": []}
    for j in range(len(t.names)):
        c, e = t.histogram(j, bins=11)
        table["hists"].append({"counts": c, "edges": e})
    for i in range(len(t.texts)):
        table["rows"].append({"id": t.corpus[i]["id"], "text": t.texts[i][:60],
                              "values": [float(col[i]) for col in t.columns],
                              "cluster": int(labels[i]) if labels is not None else -1})
    cov = {"points": [], "ids": [], "labels": [], "largest": None, "explained": [0.0, 0.0], "eps": None}
    if P is not None:
        cov = {"points": np.round(P, 4).tolist(), "ids": [c["id"] for c in t.corpus],
               "labels": labels.tolist(), "largest": t.largest_cluster(labels),
               "explained": [round(v, 4) for v in t.explained],
               "eps": round(float(eps or t._auto_eps(P)), 4)}
    last = h.turns[-1] if h.turns else None
    return {"synthetic": STATE["synthetic"], "mode": getattr(sess, "mode", "attrify"),
            "genre": STATE["genre"], "dataset": STATE["dataset"], "n_essays": len(t.texts), "turns": turns,
            "functions": funcs, "pending": [f.id for f in sess.pending()],
            "awaiting_answer": sess.awaiting_answer,
            "current_question": last.question if (last and sess.awaiting_answer) else None,
            "can_skip": bool(last and sess.awaiting_answer and last.qtype == "suggest"),
            "table": table, "coverage": cov}


def _load_corpus():
    """Essays come from the SQLite database (corpus.py). ATTRIFY_CORPUS_CSV imports a real CSV into it once;
    ATTRIFY_DATASET picks a dataset by name (default: the 50 hand-written sample essays)."""
    csv = os.environ.get("ATTRIFY_CORPUS_CSV")
    name = os.environ.get("ATTRIFY_DATASET") or C.SAMPLE
    if csv:
        name = C.import_csv(csv, text_col=os.environ.get("ATTRIFY_TEXT_COL", "full_text"),
                            n=int(os.environ.get("ATTRIFY_N", "200")), name=os.environ.get("ATTRIFY_DATASET"))
    essays, synthetic = C.load_dataset(name)
    STATE["synthetic"] = synthetic
    STATE["dataset"] = name
    return essays


# ----- pages -----
@app.get("/")
def index():
    built = os.path.join(DIST, "index.html")
    return FileResponse(built if os.path.exists(built) else os.path.join(HERE, "ui.html"))


if os.path.isdir(os.path.join(DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")


# ----- session -----
@app.post("/api/session")
def start(req: StartReq):
    with LOCK:
        try:
            llm = PT.TracedLLM(S.LLM())
        except Exception as e:  # missing key etc.
            raise HTTPException(500, f"Could not create LLM client: {e}")
        if req.mode not in ("attrify", "baseline"):
            raise HTTPException(400, "mode must be 'attrify' or 'baseline'")
        table = AT.AttributeTable(_load_corpus())
        STATE.update(fturn={}, preview={}, genre=req.genre)
        cls = BaselineSession if req.mode == "baseline" else SE.Session
        sess = cls(llm, R.Registry(), genre=req.genre, table=table,
                   log=SE.EventLog(f"session_log_{req.mode}.jsonl"))
        PT.new_tracer(f"session_trace_{req.mode}.json", lambda: len(sess.history.turns) - 1)
        PT.add("System", "Session started", "io",
               note="Which condition, which essays and which models will be used. Every later step is recorded below.",
               inputs={"condition": req.mode, "genre": req.genre},
               outputs={"dataset": STATE["dataset"], "essays": len(table.texts),
                        "models": {"restate": config.RESTATE_MODEL, "interpret_readings": config.INTERPRET_MODEL,
                                   "function_agent": config.FUNCTION_MODEL, "question_agent": config.QUESTION_MODEL},
                        "embedding_model": config.EMBED_MODEL, "temperatures": {
                            "restate": config.RESTATE_TEMP, "interpret": config.INTERPRET_TEMP,
                            "function": config.FUNCTION_TEMP, "question": config.QUESTION_TEMP},
                        "readings_per_run": config.N_READINGS, "runs_averaged": config.N_RUNS})
        sess.log.log("session_start", mode=req.mode, dataset=STATE["dataset"], genre=req.genre)
        sess.start()
        STATE["sess"] = sess
        PT.TRACER.save()
        return _state()


@app.get("/api/state")
def state(eps: float | None = Query(None)):
    with LOCK:
        return _state(eps)


@app.post("/api/answer")
def answer(req: AnswerReq):
    with LOCK:
        sess = _sess()
        try:
            r = sess.submit_answer(req.text)
        except SE.ReviewPending as e:
            raise HTTPException(409, str(e))
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        _note_new_functions(sess, r["new_functions"])
        _advance(sess)
        out = _state()
        out["last"] = {"score": r["score"], "action": r["action"], "failures": r["failures"]}
        return out


def _sse(kind, data):
    return f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"


@app.post("/api/answer/stream")
def answer_stream(req: AnswerReq):
    """Server-Sent Events: stage, scored, card, notice, question, then done (full state)."""
    sess = _sess()
    if not sess.awaiting_answer:
        raise HTTPException(400, "No question is awaiting an answer.")
    if sess.pending():
        raise HTTPException(409, "Review every proposed card before answering the next question.")
    q = queue.Queue()

    def emit(kind, data=None):
        q.put((kind, data))

    def on_card(f):
        _register_card(sess, f)
        emit("card", _func_json(f))

    def worker():
        with LOCK:
            try:
                sess.hooks = {"stage": lambda t: emit("stage", {"text": t}),
                              "scored": lambda d: emit("scored", d), "card": on_card}
                PT.TRACER.listener = lambda rec: emit("trace", rec)
                n_turns = len(sess.history.turns)
                r = sess.submit_answer(req.text)
                if r["action"] != "clarify" and not r["new_functions"]:
                    emit("notice", {"text": "I couldn't turn that into a working measure. Let's clarify instead."
                                    if r["failures"] else "No new measure came out of that. Let's continue."})
                _advance(sess)
                if len(sess.history.turns) > n_turns:
                    t = sess.history.turns[-1]
                    emit("question", {"qtype": t.qtype, "text": t.question})
                out = _state()
                out["last"] = {"score": r["score"], "action": r["action"], "failures": r["failures"]}
                emit("done", out)
            except SE.ReviewPending as e:
                emit("error", {"message": str(e), "status": 409})
            except Exception as e:
                emit("error", {"message": f"{type(e).__name__}: {e}", "status": 500})
            finally:
                sess.hooks = {}
                PT.TRACER.listener = None
                PT.TRACER.save()
                emit("end")

    def gen():
        threading.Thread(target=worker, daemon=True).start()
        while True:
            kind, data = q.get()
            if kind == "end":
                break
            yield _sse(kind, data)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/cancel")
def cancel():
    """Cancel link on slow generation: skips function generation, goes to a clarifying question.
    Deliberately lock-free so it works while the answer is being processed."""
    _sess().cancelled.set()
    return {"ok": True}


@app.post("/api/review")
def review(req: ReviewReq):
    with LOCK:
        sess = _sess()
        try:
            new = sess.review(req.fid, req.decision, req.feedback)
        except (ValueError, IndexError) as e:
            raise HTTPException(400, str(e))
        if new:
            _note_new_functions(sess, new, STATE["fturn"].get(req.fid, len(sess.history.turns) - 1))
        if req.decision == "accept":
            sess.table.trace_coverage()
        _advance(sess)
        PT.TRACER.save()
        return _state()


@app.post("/api/revisit")
def revisit(req: ReviewReq):
    """Change an earlier decision: accepted <-> rejected (adds/removes the table column)."""
    with LOCK:
        sess = _sess()
        f = sess.registry.funcs[req.fid]
        if req.decision not in ("accept", "reject") or f.status not in ("accepted", "rejected"):
            raise HTTPException(400, "Only accepted/rejected cards can be flipped.")
        sess.log.log("revisit", fid=req.fid, decision=req.decision)
        try:
            if req.decision == "accept" and f.status != "accepted":
                sess.table.add_column(f)
                sess.registry.set_status(req.fid, "accepted")
            elif req.decision == "reject" and f.status != "rejected":
                sess.table.remove_column(req.fid)
                sess.registry.set_status(req.fid, "rejected")
        except ValueError as e:
            raise HTTPException(400, str(e))
        sess.table.trace_coverage()
        PT.TRACER.save()
        return _state()


@app.post("/api/skip")
def skip(kind: str = "topic"):
    """Decline the suggestion invitation ('next' = nothing to add, 'topic' = new topic): new block
    with an open-ended question."""
    with LOCK:
        sess = _sess()
        if sess.pending() or not sess.awaiting_answer or sess.history.turns[-1].qtype != "suggest":
            raise HTTPException(400, "Nothing to skip.")
        sess.history.answer_last("(skipped)")
        sess.awaiting_answer = False
        sess.log.log("skip", kind=kind)
        PT.add("You", "Skipped the suggestion", "io",
               note="'Nothing to add' or 'new topic': a new block starts, so softness restarts from the next answer.",
               inputs={"kind": kind})
        sess.new_topic()
        PT.TRACER.save()
        return _state()


# ----- details used by the panels -----
@app.get("/api/cards/{fid}/examples")
def card_examples(fid: int, n: int = 3, exclude: str = ""):
    """'Show me 3 more essays': random essays with this card's values."""
    with LOCK:
        sess = _sess()
        vals = STATE["preview"].get(fid)
        if vals is None:
            raise HTTPException(404, "No values for this card.")
        skip_ids = {int(x) for x in exclude.split(",") if x.strip().lstrip("-").isdigit()}
        pool = [i for i in range(len(vals)) if sess.table.corpus[i]["id"] not in skip_ids]
        pick = random.sample(pool, min(max(n, 1), len(pool)))
        return {"examples": _examples(sess, fid, pick)}


@app.get("/api/essay/{eid}")
def essay(eid: int):
    with LOCK:
        t = _sess().table
        for i, c in enumerate(t.corpus):
            if c["id"] == eid:
                return {"id": eid, "text": t.texts[i], "names": t.names,
                        "values": [float(col[i]) for col in t.columns]}
        raise HTTPException(404, "Unknown essay.")


@app.post("/api/event")
def event(req: EventReq):
    """Frontend interaction events for the study log (details_open, node_open, export, ...)."""
    _sess().log.log("ui_" + req.name, **req.data)
    return {"ok": True}


@app.get("/api/trace")
def trace(since: int = -1):
    """Every recorded pipeline step with its id greater than `since` (the Pipeline Inspector's data)."""
    return {"steps": [s for s in PT.TRACER.steps if s["id"] > since]}


@app.get("/api/log")
def log():
    return _sess().log.events
