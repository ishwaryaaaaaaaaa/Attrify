"""Tests for what the UX spec added: streaming answers, card details, panel endpoints, hooks, keywords."""
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import function_agent as F  # noqa: E402
import question_agent as Q  # noqa: E402
import registry as R  # noqa: E402
import server  # noqa: E402
import session as SE  # noqa: E402
import softness as S  # noqa: E402

GOOD = "import re\ndef score(text):\n    return float(len(re.findall(r'\\w+', text)))\n"
FUNC = json.dumps([{"name": "word count", "description": "counts words", "code": GOOD}])


class FakeLLM:
    def __call__(self, system, user, model, temp):
        return FUNC if "scoring functions" in system else "next question?"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(S, "LLM", FakeLLM)
    scores = {"v": 50}
    monkeypatch.setattr(S, "softness", lambda msgs, llm, **k: {"score": scores["v"], "run_scores": [scores["v"]],
                                                              "specification": "s"})
    server.STATE.update(sess=None, fturn={}, preview={})
    c = TestClient(server.app)
    c.scores = scores
    return c


def events(text):
    out = []
    for block in text.strip().split("\n\n"):
        kind = next(ln[6:].strip() for ln in block.split("\n") if ln.startswith("event:"))
        data = "".join(ln[5:].strip() for ln in block.split("\n") if ln.startswith("data:"))
        out.append((kind, json.loads(data)))
    return out


# ----- server -----
def test_answer_stream_sends_stage_scored_card_and_done(client):
    client.post("/api/session", json={})
    ev = events(client.post("/api/answer/stream", json={"text": "count the words"}).text)
    kinds = [k for k, _ in ev if k != "trace"]            # pipeline trace steps are streamed too (see test_trace.py)
    assert kinds[0] == "stage" and kinds[-1] == "done"
    assert kinds.index("scored") < kinds.index("card") < kinds.index("done")
    scored = dict(ev)["scored"]
    assert scored["score"] == 50 and scored["action"] == "generate_then_clarify"
    assert scored["keywords"] == ["count", "words"]
    card = dict(ev)["card"]
    assert card["steps"] and card["methodType"] == "surface statistic" and len(card["examples"]) == 3
    assert 0 < card["sameShare"] <= 1 and card["status"] == "pending"
    done = dict(ev)["done"]
    assert done["pending"] == [0] and done["last"]["action"] == "generate_then_clarify"
    assert done["turns"][0]["specification"] == "s" and done["turns"][0]["keywords"] == ["count", "words"]
    assert done["turns"][0]["cardIds"] == [0] and done["coverage"]["points"] == []   # nothing accepted yet


def test_answer_stream_rejects_without_session_and_while_card_pending(client):
    assert client.post("/api/answer/stream", json={"text": "x"}).status_code == 409
    client.post("/api/session", json={})
    client.post("/api/answer/stream", json={"text": "count"})
    assert client.post("/api/answer/stream", json={"text": "again"}).status_code in (400, 409)


def test_clarify_only_stream_has_no_cards_and_asks_next_question(client):
    client.post("/api/session", json={})
    client.scores["v"] = 80
    ev = events(client.post("/api/answer/stream", json={"text": "originality"}).text)
    assert "card" not in [k for k, _ in ev]
    assert dict(ev)["question"]["qtype"] == "clarify"


def test_card_examples_and_essay_endpoints(client):
    client.post("/api/session", json={})
    client.post("/api/answer", json={"text": "x"})
    ex = client.get("/api/cards/0/examples?n=3").json()["examples"]
    assert len(ex) == 3 and {"id", "excerpt", "value"} <= set(ex[0])
    ids = ",".join(str(e["id"]) for e in ex)
    more = client.get(f"/api/cards/0/examples?n=3&exclude={ids}").json()["examples"]
    assert not {e["id"] for e in ex} & {e["id"] for e in more}
    assert client.get("/api/cards/99/examples").status_code == 404
    client.post("/api/review", json={"fid": 0, "decision": "accept"})
    essay = client.get(f"/api/essay/{ex[0]['id']}").json()
    assert essay["text"] and essay["names"] == ["word count"] and len(essay["values"]) == 1
    assert client.get("/api/essay/-5").status_code == 404


def test_state_has_a_table_row_for_every_essay_and_coverage_details(client):
    client.post("/api/session", json={})
    client.post("/api/answer", json={"text": "x"})
    st = client.post("/api/review", json={"fid": 0, "decision": "accept"}).json()
    assert len(st["table"]["rows"]) == st["n_essays"] == 50
    assert len(st["coverage"]["ids"]) == len(st["coverage"]["points"]) == 50
    assert st["coverage"]["explained"][0] > 0 and st["coverage"]["eps"] > 0
    assert client.get("/api/state?eps=0.5").json()["coverage"]["eps"] == 0.5


def test_event_log_and_cancel_endpoints(client):
    assert client.post("/api/cancel").status_code == 409          # no session yet
    client.post("/api/session", json={})
    assert client.post("/api/event", json={"name": "details_open", "data": {"cardId": 0}}).json() == {"ok": True}
    assert client.post("/api/cancel").json() == {"ok": True}
    names = [e["event"] for e in client.get("/api/log").json()]
    assert "session_start" in names and "ui_details_open" in names


def test_skip_kind_is_logged(client):
    client.post("/api/session", json={})
    client.scores["v"] = 10
    client.post("/api/answer", json={"text": "at least 500 words"})
    client.post("/api/review", json={"fid": 0, "decision": "reject"})
    client.post("/api/skip?kind=next")
    skips = [e for e in client.get("/api/log").json() if e["event"] == "skip"]
    assert skips and skips[0]["kind"] == "next"


def test_refine_records_note(client):
    client.post("/api/session", json={})
    client.post("/api/answer", json={"text": "x"})
    st = client.post("/api/review", json={"fid": 0, "decision": "refine", "feedback": "only long words"}).json()
    old = st["functions"][0]
    assert old["status"] == "refined" and old["refineNote"] == "only long words"


# ----- session hooks -----
def make(scores):
    it = iter(scores)
    return SE.Session(FakeLLM(), R.Registry(), softness_fn=lambda msgs: {"score": next(it)})


def test_cancel_during_scoring_skips_generation_and_clarifies():
    s = make([50])
    s.softness_fn = lambda msgs: (s.cancelled.set() or {"score": 50})     # Cancel pressed while scoring
    s.start()
    r = s.submit_answer("count the words")
    assert r["new_functions"] == [] and r["failures"] == ["Cancelled by the user."]
    assert s.registry.funcs == [] and s.next_question() == "next question?"


def test_hooks_report_stages_scored_and_cards_in_order():
    s = make([50])
    seen = []
    s.hooks = {"stage": lambda t: seen.append(("stage", t)), "scored": lambda d: seen.append(("scored", d["score"])),
               "card": lambda f: seen.append(("card", f.name))}
    s.start()
    s.submit_answer("count the words")
    kinds = [k for k, _ in seen]
    assert kinds[0] == "stage" and kinds.index("scored") < kinds.index("card")
    assert ("card", "word count") in seen
    assert s.history.turns[-1].keywords == ["count", "words"] and s.history.turns[-1].softness == 50


# ----- function agent helpers -----
def test_method_type_and_steps_helpers():
    assert F.method_type(GOOD) == "surface statistic"
    words = "W = {'a','b','c','d','e'}\ndef score(t):\n    return float(sum(1 for w in t.split() if w in W))\n"
    assert F.method_type(words) == "word-list check"
    assert F.method_type("def score(t) return") == "surface statistic"
    assert F.derive_steps("Split into sentences. Count the words; return the mean.") == \
        ["Split into sentences.", "Count the words;", "return the mean."]


def test_generated_card_keeps_llm_steps_or_derives_them():
    given = json.dumps([{"name": "word count", "description": "Counts words. Returns a number.", "code": GOOD,
                         "steps": ["Split on whitespace", "Count"]}])
    new, _ = F.generate_functions("Q: x\nA: y", R.Registry(), lambda *a: given)
    assert new[0].steps == ["Split on whitespace", "Count"] and new[0].method_type == "surface statistic"
    plain = json.dumps([{"name": "other count", "description": "Counts words. Returns a number.",
                         "code": GOOD.replace("\\w+", "[a-z]+")}])
    new2, _ = F.generate_functions("Q: x\nA: y", R.Registry(), lambda *a: plain)
    assert new2[0].steps == ["Counts words.", "Returns a number."]


def test_on_stage_and_on_card_hooks_fire():
    stages, cards = [], []
    F.generate_functions("Q: x\nA: y", R.Registry(), lambda *a: FUNC, on_stage=stages.append, on_card=cards.append)
    assert stages[0] == "Planning…" and "Trying it on sample essays…" in stages and len(cards) == 1


# ----- keywords -----
def test_keywords_are_local_and_skip_stopwords():
    assert Q.keywords("I like essays that feel original.") == ["essays", "feel"]
    assert Q.keywords("evidence evidence statistics and statistics evidence") == ["evidence", "statistics"]
    assert Q.keywords("") == [] and Q.keywords("the and of") == []
