"""Policy controller (Phase 4): one session = softness -> policy table -> next interaction.

Flow per user answer (paper Table 2):
  s >= 65        : no function generation, ask a CLARIFYING question
  30 < s < 65    : generate functions, user reviews cards, then CLARIFYING question
  s <= 30        : generate functions, user reviews cards, then SUGGESTION invitation
A reply to the suggestion joins the current block and the loop restarts from restatement.
Skipping the suggestion starts a new block with an open-ended question.

Blocking rule: next_question() refuses while any proposed card is still 'pending'.
Logging: JSONL file (the paper used MongoDB; swap EventLog for a DB writer if needed).
"""
import json
import threading
import time

import config
import function_agent
import pipeline_trace as PT
import question_agent as Q
import softness as S


class EventLog:
    def __init__(self, path=None):
        self.path, self.events = path, []

    def log(self, event, **data):
        rec = {"t": time.time(), "event": event, **data}
        self.events.append(rec)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")


class ReviewPending(Exception):
    """Raised when the next question is requested before every card is reviewed."""


class Session:
    def __init__(self, llm, registry, genre="argumentative", log=None, softness_fn=None,
                 cluster_provider=None, table=None):
        self.llm, self.registry, self.genre = llm, registry, genre
        self.table = table                              # AttributeTable (Phase 5) or None
        if table is not None and cluster_provider is None:
            cluster_provider = table.cluster_sample
        self.log = log or EventLog()
        self.softness_fn = softness_fn or (lambda msgs: S.softness(msgs, llm))
        self.cluster_provider = cluster_provider      # Phase 5 supplies cluster essays
        self.history = Q.History()
        self.block_start = 0       # index in history.turns where the current block began
        self.next_action = None    # "clarify" | "suggest" | "open_ended"
        self.awaiting_answer = False
        self.hooks = {}            # optional UI callbacks: stage(text), scored(dict), card(func)
        self.cancelled = threading.Event()   # set by the UI's Cancel link; skips function generation

    # ----- helpers -----
    def _block_turns(self):
        return self.history.turns[self.block_start:]

    def _block_user_messages(self):
        return [t.answer for t in self._block_turns() if t.answer]

    def _block_qa(self):
        return "\n".join(f"Q: {t.question}\nA: {t.answer}" for t in self._block_turns() if t.answer)

    def pending(self):
        return [f for f in self.registry.funcs if f.status == "pending"]

    def _hook(self, name, *args):
        fn = self.hooks.get(name)
        if fn:
            fn(*args)

    def _ask(self, qtype, text):
        self.history.add(qtype, text)
        self.awaiting_answer = True
        self.log.log("question", qtype=qtype, text=text)
        return text

    # ----- public API -----
    def start(self):
        return self._ask("open_ended", Q.opening(self.genre))

    def submit_answer(self, answer):
        """Record the user's answer, score softness, apply the policy.
        Returns dict: score, action, new_functions, failures."""
        if not self.awaiting_answer:
            raise RuntimeError("No question is awaiting an answer.")
        if self.pending():
            raise ReviewPending("Review every proposed card before answering the next question.")
        self.history.answer_last(answer)
        self.history.turns[-1].keywords = Q.keywords(answer)
        self.awaiting_answer = False
        self.cancelled.clear()
        self.log.log("answer", text=answer)
        PT.add("You", "Answer received", "io",
               note="Your answer is stored. Two keywords are picked locally (no model) for the History node.",
               outputs={"answer": answer, "keywords": self.history.turns[-1].keywords})

        self._hook("stage", "Working out how open-ended this is…")
        res = self.softness_fn(self._block_user_messages())
        s = res["score"]
        self.history.turns[-1].softness = s
        self.history.turns[-1].specification = res.get("specification") or ""
        action = S.policy(s)
        PT.add("Policy", "Choose what happens next", "decision",
               note="Paper Table 2: a high softness means the attribute is still vague, so only ask a clarifying question; "
                    "a middle score also proposes functions; a low score means it is pinned down.",
               inputs={"softness": s, "clarify_only_at_or_above": config.HIGH_SOFT, "suggest_at_or_below": config.LOW_SOFT},
               outputs={"action": action,
                        "meaning": {"clarify": "No functions. Ask a clarifying question.",
                                    "generate_then_clarify": "Write functions, you review them, then a clarifying question.",
                                    "generate_then_suggest": "Write functions, you review them, then an invitation to add more or move on."}[action]})
        self.log.log("softness", score=s, run_scores=res.get("run_scores"),
                     specification=res.get("specification"), policy=action)
        self._hook("scored", {"score": s, "action": action, "specification": res.get("specification") or "",
                              "keywords": self.history.turns[-1].keywords})

        new, failures = [], []
        if action == "clarify":
            self.next_action = "clarify"
        elif self.cancelled.is_set():
            failures = ["Cancelled by the user."]
            self.next_action = "clarify"
            self.log.log("cancelled")
        else:
            new, failures = function_agent.generate_functions(
                self._block_qa(), self.registry, self.llm,
                on_stage=lambda t: self._hook("stage", t), on_card=lambda f: self._hook("card", f))
            self.log.log("functions", ids=[f.id for f in new], names=[f.name for f in new],
                         failures=failures)
            self.next_action = "clarify" if action == "generate_then_clarify" else "suggest"
        return {"score": s, "action": action, "new_functions": new, "failures": failures}

    def review(self, fid, decision, feedback=None):
        """decision: accept | reject | refine (refine needs feedback text)."""
        f = self.registry.funcs[fid]
        if f.status != "pending":
            raise ValueError(f"Function {fid} is not pending (status={f.status}).")
        self.log.log("review", fid=fid, decision=decision, feedback=feedback)
        PT.add("You", f"Review: {decision} “{f.name}”", "io",
               note="Accept adds a column to the attribute table. Reject drops the card. Refine asks the Function Agent again with your note.",
               inputs={"card": f.name, "decision": decision, "feedback": feedback})
        if decision == "accept":
            if self.table is not None:
                self.table.add_column(f)    # may raise ValueError; card then stays pending
            self.registry.set_status(fid, "accepted")
        elif decision == "reject":
            self.registry.set_status(fid, "rejected")
        elif decision == "refine":
            if not feedback:
                raise ValueError("refine needs feedback text")
            self.registry.set_status(fid, "refined")   # old version kept for history
            f.refine_note = feedback
            qa = (self._block_qa() + f"\nRefinement request for '{f.name}': {feedback}")
            new, failures = function_agent.generate_functions(
                qa, self.registry, self.llm,
                on_stage=lambda t: self._hook("stage", t), on_card=lambda n: self._hook("card", n))
            if new:
                f.superseded_by = new[0].id
            self.log.log("functions", ids=[n.id for n in new], names=[n.name for n in new],
                         failures=failures, refined_from=fid)
            return new
        else:
            raise ValueError("decision must be accept, reject or refine")

    def next_question(self):
        if self.awaiting_answer:
            raise RuntimeError("Previous question is still unanswered.")
        if self.pending():
            raise ReviewPending(f"{len(self.pending())} card(s) still pending review.")
        self._hook("stage", "Thinking of the next question…")
        if self.next_action == "clarify":
            q = Q.clarify(self.history, self.llm, [f.name for f in self.registry.funcs])
            return self._ask("clarify", q)
        if self.next_action == "suggest":
            return self._ask("suggest", Q.suggest())
        return self.new_topic()

    def new_topic(self):
        """Skip the suggestion / move on: new block, open-ended question."""
        self.block_start = len(self.history.turns)
        clusters = self.cluster_provider() if self.cluster_provider else None
        q = Q.open_ended(self.history, self.llm, cluster_essays=clusters)
        self.next_action = None
        return self._ask("open_ended", q)
