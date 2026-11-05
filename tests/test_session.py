import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import registry as R  # noqa: E402
import session as SE  # noqa: E402

GOOD = "import re\ndef score(text):\n    return float(len(re.findall(r'\\w+', text)))\n"
FUNC_JSON = json.dumps([{"name": "word count", "description": "counts words", "code": GOOD}])


class FakeLLM:
    """Returns function JSON for the function prompt, a plain question otherwise."""
    def __call__(self, system, user, model, temp):
        if "scoring functions" in system:
            return FUNC_JSON
        return "A generated question?"


def make(scores):
    it = iter(scores)
    sess = SE.Session(FakeLLM(), R.Registry(), softness_fn=lambda msgs: {"score": next(it)})
    return sess


def test_high_softness_clarifies_without_generating():
    s = make([80])
    s.start()
    r = s.submit_answer("I like originality")
    assert r["action"] == "clarify" and r["new_functions"] == [] and s.registry.funcs == []
    assert s.next_question() == "A generated question?"
    assert s.history.turns[-1].qtype == "clarify"


def test_mid_softness_generates_then_clarifies_and_blocks_until_reviewed():
    s = make([50])
    s.start()
    r = s.submit_answer("count the words")
    assert r["action"] == "generate_then_clarify" and len(r["new_functions"]) == 1
    with pytest.raises(SE.ReviewPending):
        s.next_question()                      # blocked: card still pending
    s.review(0, "accept")
    s.next_question()
    assert s.history.turns[-1].qtype == "clarify" and s.registry.funcs[0].status == "accepted"


def test_low_softness_generates_then_suggests_and_reply_stays_in_block():
    s = make([20, 20])
    s.start()
    s.submit_answer("at least 500 words")
    s.review(0, "reject")
    assert s.next_question().startswith("Before we continue")
    seen = []
    s.softness_fn = lambda msgs: (seen.append(list(msgs)) or {"score": 20})
    s.submit_answer("also at least 3 paragraphs")
    assert seen[0] == ["at least 500 words", "also at least 3 paragraphs"]   # same block


def test_new_topic_starts_new_block():
    s = make([20])
    s.start()
    s.submit_answer("500 words")
    s.review(0, "accept")
    s.next_question()                          # suggestion
    s.new_topic()
    assert s.block_start == 2 and s.history.turns[-1].qtype == "open_ended"
    seen = []
    s.softness_fn = lambda msgs: (seen.append(list(msgs)) or {"score": 80})
    s.submit_answer("something new")
    assert seen[0] == ["something new"]


def test_cannot_answer_while_card_pending_or_without_question():
    s = make([50])
    with pytest.raises(RuntimeError):
        s.submit_answer("no question asked yet")
    s.start()
    s.submit_answer("x")
    with pytest.raises(RuntimeError):          # question not asked yet
        s.submit_answer("again")


def test_refine_keeps_history_and_adds_pending():
    s = make([50])
    s.start()
    s.submit_answer("count words")
    new = s.review(0, "refine", feedback="exclude stop words")
    assert s.registry.funcs[0].status == "refined" and len(new) == 1
    assert s.registry.funcs[new[0].id].status == "pending"
    with pytest.raises(ValueError):
        s.review(0, "accept")                  # no longer pending


def test_event_log_written(tmp_path):
    p = tmp_path / "log.jsonl"
    it = iter([80])
    s = SE.Session(FakeLLM(), R.Registry(), log=SE.EventLog(str(p)),
                   softness_fn=lambda m: {"score": next(it)})
    s.start()
    s.submit_answer("hi")
    events = [json.loads(line)["event"] for line in p.read_text().splitlines()]
    assert events == ["question", "answer", "softness"]
