import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import attribute_table as AT  # noqa: E402
import baseline as B  # noqa: E402
import corpus as C  # noqa: E402
import prompts  # noqa: E402
import registry as R  # noqa: E402
import session as SE  # noqa: E402

WORDS = "import re\ndef score(text):\n    return float(len(re.findall(r'\\w+', text)))\n"
FUNC = json.dumps([{"name": "word count", "description": "counts words", "code": WORDS}])
NUMS = json.dumps([{"name": "digit runs", "description": "counts digit runs",
                    "code": "import re\ndef score(text):\n    return float(len(re.findall(r'\\d+', text)))\n"}])


class FakeLLM:
    def __init__(self, funcs=(FUNC, NUMS)):
        self.chat_calls, self.funcs = [], list(funcs)

    def __call__(self, system, user, model, temp):
        if "scoring functions" in system:
            return self.funcs.pop(0) if self.funcs else "[]"
        self.chat_calls.append((system, user))
        return ' "That makes sense." '


def make():
    llm = FakeLLM()
    s = B.BaselineSession(llm, R.Registry(), table=AT.AttributeTable(C.demo_corpus(30)))
    return s, llm


def test_generates_every_turn_with_no_softness_gate():
    s, _ = make()
    s.softness_fn = lambda m: (_ for _ in ()).throw(AssertionError("softness must not be used"))
    s.start()
    r = s.submit_answer("I like clear writing")          # vague answer: AttriFy would only clarify
    assert r["score"] is None and r["action"] == "generate" and len(r["new_functions"]) == 1
    s.review(0, "accept")
    assert s.next_question() == "That makes sense."      # stripped of quotes
    r2 = s.submit_answer("and numbers")
    assert len(r2["new_functions"]) == 1                 # generated again on the next turn too


def test_reply_prompt_has_transcript_and_baseline_system():
    s, llm = make()
    s.start()
    s.submit_answer("I like clear writing")
    system, user = llm.chat_calls[0]
    assert system == prompts.BASELINE_SYSTEM
    assert user.startswith("Conversation so far:\nAssistant: Argumentative essays.")
    assert "User: I like clear writing" in user and "no speaker label" in user


def test_blocks_until_cards_reviewed_and_reply_shown_after():
    s, _ = make()
    s.start()
    s.submit_answer("x")
    with pytest.raises(SE.ReviewPending):
        s.next_question()
    s.review(0, "reject")
    s.next_question()
    assert s.history.turns[-1].qtype == "chat" and s.awaiting_answer
    with pytest.raises(RuntimeError):
        s.next_question()                                 # unanswered


def test_no_topic_phases_and_shared_table():
    s, _ = make()
    s.start()
    with pytest.raises(RuntimeError):
        s.new_topic()
    s.submit_answer("x")
    s.review(0, "accept")
    assert s.table.names == ["word count"]                # same table machinery as AttriFy
    assert s.mode == "baseline"


def test_refine_works_in_baseline():
    s, _ = make()
    s.start()
    s.submit_answer("count words")
    new = s.review(0, "refine", feedback="ignore short words")
    assert s.registry.funcs[0].status == "refined" and len(new) == 1
