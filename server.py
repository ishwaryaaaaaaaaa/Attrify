"""FastAPI server for the AttriFy UI (Phase 6). Single local user, one global session.

Run (from attrify/):   python -m uvicorn server:app --port 8000
Env: OPENAI_API_KEY (+ ATTRIFY_BASE_URL / ATTRIFY_*_MODEL) as in config.py
     ATTRIFY_CORPUS_CSV, ATTRIFY_TEXT_COL (default full_text), ATTRIFY_N (default 200)
     -> real corpus; otherwise the SYNTHETIC demo corpus is used and flagged in the UI.
"""
import os
import threading

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import attribute_table as AT
import corpus as C
from baseline import BaselineSession
import registry as R
import session as SE
import softness as S

app = FastAPI(title="AttriFy")
LOCK = threading.Lock()
STATE = {"sess": None, "fturn": {}, "synthetic": True}
HERE = os.path.dirname(os.path.abspath(__file__))


class StartReq(BaseModel):
    genre: str = "argumentative"
    mode: str = "attrify"          # "attrify" | "baseline"


class AnswerReq(BaseModel):
    text: str


class ReviewReq(BaseModel):
    fid: int
    decision: str
    feedback: str | None = None


def _sess():
    if STATE["sess"] is None:
        raise HTTPException(409, "No session. Start one first.")
    return STATE["sess"]


def _advance(sess):
    """Ask the next question once nothing is pending and no answer is awaited."""
    if not sess.awaiting_answer and not sess.pending():
        sess.next_question()


def _note_new_functions(sess, funcs):
    turn = len(sess.history.turns) - 1
    for f in funcs:
        STATE["fturn"][f.id] = turn


def _state():
    sess = _sess()
    h = sess.history
    turns = [{"i": i, "qtype": t.qtype, "question": t.question, "answer": t.answer,
              "softness": t.softness, "new_block": i == 0 or i == sess.block_start and i > 0}
             for i, t in enumerate(h.turns)]
    funcs = [{"id": f.id, "name": f.name, "description": f.description, "code": f.code,
              "status": f.status, "samples": f.sample_values, "warnings": f.warnings,
              "turn": STATE["fturn"].get(f.id, 0)} for f in sess.registry.funcs]
    t = sess.table
    table = {"names": t.names, "fids": t.fids, "hists": [], "rows": []}
    for j in range(len(t.names)):
        c, e = t.histogram(j, bins=8)
        table["hists"].append({"counts": c, "edges": e})
    for i in range(min(15, len(t.texts))):
        table["rows"].append({"id": t.corpus[i]["id"], "text": t.texts[i][:90],
                              "values": [float(col[i]) for col in t.columns]})
    cov = {"points": [], "labels": [], "largest": None}
    P, labels = t.clusters()
    if P is not None:
        cov = {"points": np.round(P, 4).tolist(), "labels": labels.tolist(),
               "largest": t.largest_cluster(labels)}
    last = h.turns[-1] if h.turns else None
    return {"synthetic": STATE["synthetic"], "mode": getattr(sess, "mode", "attrify"),
            "n_essays": len(t.texts), "turns": turns,
            "functions": funcs, "pending": [f.id for f in sess.pending()],
            "awaiting_answer": sess.awaiting_answer,
            "current_question": last.question if (last and sess.awaiting_answer) else None,
            "can_skip": bool(last and sess.awaiting_answer and last.qtype == "suggest"),
            "table": table, "coverage": cov}


def _load_corpus():
    path = os.environ.get("ATTRIFY_CORPUS_CSV")
    if path:
        STATE["synthetic"] = False
        return C.load_csv(path, text_col=os.environ.get("ATTRIFY_TEXT_COL", "full_text"),
                          n=int(os.environ.get("ATTRIFY_N", "200")))
    STATE["synthetic"] = True
    return C.demo_corpus(90)


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "ui.html"))


@app.post("/api/session")
def start(req: StartReq):
    with LOCK:
        try:
            llm = S.LLM()
        except Exception as e:  # missing key etc.
            raise HTTPException(500, f"Could not create LLM client: {e}")
        if req.mode not in ("attrify", "baseline"):
            raise HTTPException(400, "mode must be 'attrify' or 'baseline'")
        table = AT.AttributeTable(_load_corpus())
        STATE["fturn"] = {}
        cls = BaselineSession if req.mode == "baseline" else SE.Session
        sess = cls(llm, R.Registry(), genre=req.genre, table=table,
                   log=SE.EventLog(f"session_log_{req.mode}.jsonl"))
        sess.start()
        STATE["sess"] = sess
        return _state()


@app.get("/api/state")
def state():
    with LOCK:
        return _state()


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


@app.post("/api/review")
def review(req: ReviewReq):
    with LOCK:
        sess = _sess()
        try:
            new = sess.review(req.fid, req.decision, req.feedback)
        except (ValueError, IndexError) as e:
            raise HTTPException(400, str(e))
        if new:
            for f in new:
                STATE["fturn"][f.id] = STATE["fturn"].get(req.fid, len(sess.history.turns) - 1)
        _advance(sess)
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
        return _state()


@app.post("/api/skip")
def skip():
    """Decline the suggestion invitation: new block with an open-ended question."""
    with LOCK:
        sess = _sess()
        if sess.pending() or not sess.awaiting_answer or sess.history.turns[-1].qtype != "suggest":
            raise HTTPException(400, "Nothing to skip.")
        sess.history.answer_last("(skipped)")
        sess.awaiting_answer = False
        sess.log.log("skip")
        sess.new_topic()
        return _state()
