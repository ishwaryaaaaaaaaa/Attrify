"""The pipeline trace: every step records what went in and what came out (shown in the Pipeline Inspector)."""
import json
import os
import sys

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import function_agent as F  # noqa: E402
import pipeline_trace as PT  # noqa: E402
import question_agent as Q  # noqa: E402
import registry as R  # noqa: E402
import server  # noqa: E402
import session as SE  # noqa: E402
import softness as S  # noqa: E402

GOOD = "import re\ndef score(text):\n    return float(len(re.findall(r'\\w+', text)))\n"
FUNC = json.dumps([{"name": "word count", "description": "counts words", "code": GOOD}])


def readings(labels):
    return json.dumps([{"attribute_label": l, "full_description": f"measure {l} somehow"} for l in labels])


class ScriptedLLM:
    """Answers each agent with canned JSON/text so the real softness, function and question code runs."""
    LABELS = ["thesis clarity", "evidence density", "counter argument use", "tone formality", "essay length",
              "vocabulary range", "paragraph structure", "citation count", "hook strength", "conclusion strength"]

    def __call__(self, system, user, model, temp):
        if "consolidated specification" in system:
            return json.dumps({"specification": "merged spec"})
        if "READINGS" in system:
            return readings(self.LABELS)
        if "scoring functions" in system:
            return FUNC
        return "next question?"


def fake_embed(labels):
    rng = np.random.default_rng(len(labels))
    E = rng.normal(size=(len(labels), 8))
    return E / np.linalg.norm(E, axis=1, keepdims=True)


@pytest.fixture(autouse=True)
def fresh_tracer():
    PT.new_tracer()
    yield PT.TRACER


def by_step(prefix):
    return [s for s in PT.TRACER.steps if s["step"].startswith(prefix)]


# ----- tracer basics -----
def test_traced_llm_records_prompts_response_and_label():
    llm = PT.TracedLLM(lambda system, user, model, temp: "hello")
    with PT.scope("Question Agent", "Clarifying question", "why"):
        assert llm("SYS", "USER", "m1", 0.3) == "hello"
        PT.attach(outputs={"question": "hello"})
    (s,) = PT.TRACER.steps
    assert s["agent"] == "Question Agent" and s["kind"] == "llm" and s["note"] == "why"
    assert s["llm"] == {"model": "m1", "temperature": 0.3, "system": "SYS", "user": "USER", "response": "hello"}
    assert s["outputs"] == {"question": "hello"} and s["ms"] is not None


def test_traced_llm_records_errors_and_reraises():
    def boom(*a):
        raise RuntimeError("api down")
    with pytest.raises(RuntimeError):
        PT.TracedLLM(boom)("s", "u", "m", 0)
    assert PT.TRACER.steps[0]["status"] == "error" and "api down" in PT.TRACER.steps[0]["outputs"]["error"]


def test_listener_receives_each_add_and_update():
    seen = []
    PT.TRACER.listener = lambda r: seen.append((r["id"], r["status"]))
    rec = PT.add("A", "step")
    PT.TRACER.update(rec, status="retry")
    assert seen == [(0, "ok"), (0, "retry")]


def test_save_writes_json(tmp_path):
    PT.new_tracer(str(tmp_path / "t.json"))
    PT.add("A", "one", inputs={"x": 1})
    PT.TRACER.save()
    assert json.loads((tmp_path / "t.json").read_text())[0]["inputs"] == {"x": 1}


# ----- softness agent -----
def test_softness_trace_has_every_stage_with_numbers():
    res = S.softness(["first", "second"], PT.TracedLLM(ScriptedLLM()), embed_fn=fake_embed)
    names = [s["step"] for s in PT.TRACER.steps]
    assert names[0].startswith("0 ·") and any(n.startswith("1 · Restate the messages") for n in names)
    assert len(by_step("2 · Sample")) == 3 and len(by_step("3 ·")) == 3 and len(by_step("4 ·")) == 3
    assert PT.TRACER.steps[-1]["outputs"]["softness"] == res["score"]
    run1 = by_step("4 ·")[0]
    kinds = {v["type"] for v in run1["viz"]}
    assert {"bars", "formula"} <= kinds
    lam = next(v for v in run1["viz"] if v["type"] == "bars")["values"]
    assert abs(sum(lam) - 1) < 0.01 and run1["outputs"]["softness"] in res["run_scores"]
    matrix = next(v for v in by_step("3 ·")[0]["viz"] if v["type"] == "matrix")["values"]
    assert len(matrix) == 10 and all(matrix[i][i] == 1.0 for i in range(10))
    read = by_step("2 · Sample")[0]
    assert read["llm"]["response"] and read["viz"][0]["type"] == "readings" and len(read["viz"][0]["items"]) == 10


def test_single_message_skips_restate_and_says_so():
    S.softness(["only one"], PT.TracedLLM(ScriptedLLM()), embed_fn=fake_embed)
    assert by_step("1 · Restate (skipped)") and not by_step("1 · Restate the messages")


def test_bad_json_marks_the_step_as_retry_and_asks_again():
    calls = {"n": 0}

    def llm(system, user, model, temp):
        calls["n"] += 1
        return "not json" if calls["n"] == 1 else json.dumps({"specification": "ok"})
    S.restate(["a", "b"], PT.TracedLLM(llm))
    steps = by_step("1 · Restate the messages")
    assert [s["status"] for s in steps] == ["retry", "ok"] and "problem" in steps[0]["outputs"]


def test_vendi_details_matches_vendi_from_embeddings():
    E = fake_embed(["a"] * 10)
    d = S.vendi_details(E)
    assert d["V"] == pytest.approx(S.vendi_from_embeddings(E)) and d["K"].shape == (10, 10)


# ----- function agent -----
def test_function_agent_trace_checks_each_candidate():
    new, _ = F.generate_functions("Q: x\nA: y", R.Registry(), PT.TracedLLM(ScriptedLLM()))
    names = [s["step"] for s in PT.TRACER.steps]
    assert names[0].startswith("0 ·") and any(n.startswith("1 · Write code") for n in names)
    check = by_step("2 · Check")[0]
    assert check["kind"] == "sandbox" and check["outputs"]["ast_check"] == "passed"
    assert check["outputs"]["verdict"].startswith("kept") and len(check["outputs"]["values"]) == 9
    assert {"code", "table"} <= {v["type"] for v in check["viz"]}
    assert by_step("3 · Cards proposed")[0]["outputs"]["cards"] == [new[0].name]


def test_function_agent_trace_records_rejections():
    bad = json.dumps([{"name": "evil", "description": "d", "code": "import os\ndef score(t):\n    return 1.0\n"}])
    F.generate_functions("Q: x\nA: y", R.Registry(), PT.TracedLLM(lambda *a: bad), max_tries=1)
    check = by_step("2 · Check")[0]
    assert "Import not allowed" in check["outputs"]["ast_check"] and check["status"] == "retry"


# ----- session -----
def test_session_trace_has_answer_policy_and_question_steps():
    llm = PT.TracedLLM(ScriptedLLM())
    s = SE.Session(llm, R.Registry(), softness_fn=lambda msgs: {"score": 80, "specification": "x"})
    s.start()
    s.submit_answer("originality")
    s.next_question()
    agents = [(x["agent"], x["step"]) for x in PT.TRACER.steps]
    assert ("Question Agent", "Opening question (fixed text)") in agents
    assert ("You", "Answer received") in agents and ("Policy", "Choose what happens next") in agents
    pol = next(x for x in PT.TRACER.steps if x["agent"] == "Policy")
    assert pol["outputs"]["action"] == "clarify" and pol["inputs"]["softness"] == 80
    q = next(x for x in PT.TRACER.steps if x["step"] == "Clarifying question")
    assert q["outputs"]["question"] == "next question?" and "originality" in q["llm"]["user"]


def test_turn_numbers_follow_the_history():
    llm = PT.TracedLLM(ScriptedLLM())
    s = SE.Session(llm, R.Registry(), softness_fn=lambda msgs: {"score": 80, "specification": "x"})
    PT.TRACER.turn_fn = lambda: len(s.history.turns) - 1
    s.start()
    s.submit_answer("a")
    s.next_question()
    turns = {x["step"]: x["turn"] for x in PT.TRACER.steps}
    assert turns["Opening question (fixed text)"] == -1 and turns["Answer received"] == 0
    assert turns["Clarifying question"] == 0


# ----- server -----
@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(S, "LLM", ScriptedLLM)
    monkeypatch.setattr(S, "embed", fake_embed)
    monkeypatch.setattr("config.N_RUNS", 3)
    server.STATE.update(sess=None, fturn={}, preview={})
    return TestClient(server.app)


def test_trace_endpoint_and_streamed_trace_events(client):
    client.post("/api/session", json={})
    steps = client.get("/api/trace").json()["steps"]
    assert steps[0]["step"] == "Session started" and steps[0]["outputs"]["essays"] == 50
    assert any(s["step"].startswith("Opening question") for s in steps)
    text = client.post("/api/answer/stream", json={"text": "count the words"}).text
    kinds = [ln[6:].strip() for ln in text.split("\n") if ln.startswith("event:")]
    assert kinds.count("trace") > 8 and kinds[-1] == "done"
    after = client.get(f"/api/trace?since={steps[-1]['id']}").json()["steps"]
    assert after and all(s["id"] > steps[-1]["id"] for s in after)
    agents = {s["agent"] for s in after}
    assert {"You", "Softness Agent", "Policy"} <= agents
    assert os.path.exists("session_trace_attrify.json")


def test_accepting_a_card_traces_table_and_graph(client, monkeypatch):
    monkeypatch.setattr(S, "softness", lambda msgs, llm, **k: {"score": 50, "specification": "s"})
    client.post("/api/session", json={})
    client.post("/api/answer", json={"text": "count the words"})
    client.post("/api/review", json={"fid": 0, "decision": "accept"})
    names = [s["step"] for s in client.get("/api/trace").json()["steps"]]
    assert any(n.startswith("Preview “word count”") for n in names)
    assert any(n.startswith("Add column “word count”") for n in names)
    assert "Standardize → PCA → DBSCAN" in names
    assert any(n.startswith("Review: accept") for n in names)
