"""Baseline condition (Phase 7): plain LLM chat, no softness gate, no phases.

After EVERY user turn it calls the same Function Agent (same sandbox, registry, table and
coverage graph as AttriFy), so the comparison isolates the softness-guided clarification.
Same fixed opening question. Same review step: new cards must be accepted/rejected/refined
before the assistant's reply is shown (kept identical for fairness; the paper does not say
if the baseline blocked, so treat this as my choice and state it in the write-up).
"""
import config
import function_agent
import prompts
from session import ReviewPending, Session


class BaselineSession(Session):
    mode = "baseline"
    _reply = None

    def _transcript(self):
        lines = []
        for t in self.history.turns:
            lines.append(f"Assistant: {t.question}")
            if t.answer:
                lines.append(f"User: {t.answer}")
        return "\n".join(lines)

    def _all_qa(self):
        return "\n".join(f"Q: {t.question}\nA: {t.answer}" for t in self.history.turns if t.answer)

    def _chat_reply(self):
        out = self.llm(prompts.BASELINE_SYSTEM, prompts.baseline_user(self._transcript()),
                       config.BASELINE_MODEL, config.BASELINE_TEMP)
        return out.strip().strip('"')

    def submit_answer(self, answer):
        if not self.awaiting_answer:
            raise RuntimeError("No question is awaiting an answer.")
        if self.pending():
            raise ReviewPending("Review every proposed card before answering the next question.")
        self.history.answer_last(answer)
        self.awaiting_answer = False
        self.log.log("answer", text=answer)

        new, failures = function_agent.generate_functions(self._all_qa(), self.registry, self.llm)
        self.log.log("functions", ids=[f.id for f in new], names=[f.name for f in new], failures=failures)
        self._reply = self._chat_reply()     # generated now, shown once cards are reviewed
        self.next_action = "chat"
        return {"score": None, "action": "generate", "new_functions": new, "failures": failures}

    def next_question(self):
        if self.awaiting_answer:
            raise RuntimeError("Previous question is still unanswered.")
        if self.pending():
            raise ReviewPending(f"{len(self.pending())} card(s) still pending review.")
        if self._reply is None:
            raise RuntimeError("No reply is ready.")
        reply, self._reply = self._reply, None
        return self._ask("chat", reply)

    def new_topic(self):
        raise RuntimeError("The baseline has no topic phases.")
