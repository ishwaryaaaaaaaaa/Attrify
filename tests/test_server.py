import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server  # noqa: E402
import softness as S  # noqa: E402

WORDS = "import re\ndef score(text):\n    return float(len(re.findall(r'\\w+', text)))\n"
FUNC = json.dumps([{"name": "word count", "description": "counts words", "code": WORDS}])


class FakeLLM:
    def __call__(self, system, user, model, temp):
        return FUNC if "scoring functions" in system else "next question?"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)                               # session_log.jsonl lands in tmp
    monkeypatch.setattr(S, "LLM", FakeLLM)
    scores = {"v": 50}
    monkeypatch.setattr(S, "softness", lambda msgs, llm, **k: {"score": scores["v"], "run_scores": [scores["v"]],
                                                              "specification": "s"})
    server.STATE.update(sess=None, fturn={})
    c = TestClient(server.app)
    c.scores = scores
    return c


def test_index_serves_ui(client):
    r = client.get("/")
    assert r.status_code == 200 and "AttriFy" in r.text


def test_requires_session(client):
    assert client.get("/api/state").status_code == 409


def test_full_flow_pending_blocks_then_review_advances(client):
    st = client.post("/api/session", json={"genre": "narrative"}).json()
    assert st["synthetic"] and st["current_question"].startswith("Narrative essays")
    st = client.post("/api/answer", json={"text": "count the words"}).json()
    assert st["last"]["action"] == "generate_then_clarify" and st["pending"] == [0]
    assert st["current_question"] is None                      # no next question while a card is pending
    assert client.post("/api/answer", json={"text": "again"}).status_code in (400, 409)
    st = client.post("/api/review", json={"fid": 0, "decision": "accept"}).json()
    assert st["pending"] == [] and st["current_question"] == "next question?"
    assert st["table"]["names"] == ["word count"] and len(st["table"]["hists"]) == 1
    assert st["coverage"]["points"] and st["functions"][0]["turn"] == 0


def test_revisit_flips_decision_and_table(client):
    client.post("/api/session", json={})
    client.post("/api/answer", json={"text": "x"})
    client.post("/api/review", json={"fid": 0, "decision": "accept"})
    st = client.post("/api/revisit", json={"fid": 0, "decision": "reject"}).json()
    assert st["table"]["names"] == [] and st["functions"][0]["status"] == "rejected"
    st = client.post("/api/revisit", json={"fid": 0, "decision": "accept"}).json()
    assert st["table"]["names"] == ["word count"]


def test_bad_review_inputs(client):
    client.post("/api/session", json={})
    client.post("/api/answer", json={"text": "x"})
    assert client.post("/api/review", json={"fid": 0, "decision": "maybe"}).status_code == 400
    assert client.post("/api/review", json={"fid": 0, "decision": "refine"}).status_code == 400
    assert client.post("/api/review", json={"fid": 99, "decision": "accept"}).status_code == 400
    assert client.post("/api/revisit", json={"fid": 0, "decision": "accept"}).status_code == 400  # still pending


def test_skip_only_after_suggestion(client):
    client.post("/api/session", json={})
    assert client.post("/api/skip").status_code == 400
    client.scores["v"] = 10
    client.post("/api/answer", json={"text": "at least 500 words"})
    st = client.post("/api/review", json={"fid": 0, "decision": "reject"}).json()
    assert st["can_skip"] and st["current_question"].startswith("Before we continue")
    st = client.post("/api/skip").json()
    assert not st["can_skip"] and st["current_question"] == "next question?"
    assert st["turns"][-1]["qtype"] == "open_ended"


def test_ui_html_is_self_contained():
    html = open(os.path.join(os.path.dirname(__file__), "..", "ui.html"), encoding="utf-8").read()
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "") and "https://" not in html


def test_baseline_mode_via_api(client):
    st = client.post("/api/session", json={"mode": "baseline"}).json()
    assert st["mode"] == "baseline"
    st = client.post("/api/answer", json={"text": "I like clear writing"}).json()
    assert st["last"]["score"] is None and st["pending"] == [0]      # generated despite vague answer
    st = client.post("/api/review", json={"fid": 0, "decision": "accept"}).json()
    assert st["current_question"] == "next question?" and st["turns"][-1]["qtype"] == "chat"
    assert client.post("/api/skip").status_code == 400
    assert client.post("/api/session", json={"mode": "other"}).status_code == 400
