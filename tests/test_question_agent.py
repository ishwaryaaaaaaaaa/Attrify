import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import question_agent as Q  # noqa: E402
import prompts  # noqa: E402


def fake(captured):
    def llm(system, user, model, temp):
        captured.append(user)
        return ' "What else matters?" '
    return llm


def test_history_format():
    h = Q.History()
    h.add("open_ended", "Q one?")
    h.answer_last("answer one", 70)
    h.add("clarify", "Q two?")
    s = h.format()
    assert "Q1: Q one?" in s and "A1: answer one" in s and "A2: (unanswered)" in s
    assert h.turns[0].softness == 70


def test_open_ended_fills_all_placeholders_and_cluster_context():
    cap = []
    h = Q.History()
    h.add("open_ended", "first?")
    h.answer_last("clear thesis")
    out = Q.open_ended(h, fake(cap), cluster_essays=[(3, 0, "excerpt text")])
    assert out == "What else matters?"          # stripped + unquoted
    assert "{" not in cap[0] and "}" not in cap[0]
    assert "Essay 3 (cluster 0): excerpt text" in cap[0] and "clear thesis" in cap[0]


def test_clarify_uses_titles_and_history():
    cap = []
    h = Q.History()
    h.add("open_ended", "q?")
    h.answer_last("I like originality")
    Q.clarify(h, fake(cap), function_titles=["novel idea count"])
    assert "- novel idea count" in cap[0] and "I like originality" in cap[0]
    assert "{" not in cap[0]


def test_suggest_and_opening_are_fixed_text():
    assert Q.suggest() == prompts.SUGGEST and "additional thoughts" in Q.suggest()
    assert Q.opening("narrative").startswith("Narrative essays.")
