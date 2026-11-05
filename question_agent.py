"""Question Agent: open-ended, clarifying, suggestion. Plus the interaction history."""
from dataclasses import dataclass, field

import config
import prompts


@dataclass
class Turn:
    qtype: str          # "open_ended" | "clarify" | "suggest"
    question: str
    answer: str = ""
    softness: int | None = None


@dataclass
class History:
    turns: list = field(default_factory=list)

    def add(self, qtype, question):
        self.turns.append(Turn(qtype, question))
        return self.turns[-1]

    def answer_last(self, answer, softness=None):
        self.turns[-1].answer, self.turns[-1].softness = answer, softness

    def format(self):
        if not self.turns:
            return "(none yet)"
        return "\n".join(f"Q{i}: {t.question}\nA{i}: {t.answer or '(unanswered)'}"
                         for i, t in enumerate(self.turns, 1))


def _fill(template, **kw):
    for k, v in kw.items():
        template = template.replace("{" + k + "}", v)
    return template


def _ask(llm, prompt):
    # Single-prompt style (paper gives one prompt body, no separate system prompt).
    return llm("", prompt, config.QUESTION_MODEL, config.QUESTION_TEMP).strip().strip('"')


def opening(genre):
    """Fixed first question, identical for both study conditions."""
    return prompts.OPENING[genre]


def open_ended(history, llm, cluster_essays=None, attribute_context="", note=""):
    """cluster_essays: list of (essay_id, cluster_id, excerpt) from the largest
    non-noise cluster (Phase 5 supplies this); None -> no cluster evidence."""
    ctx = "\n".join(f"Essay {i} (cluster {c}): {x}" for i, c, x in (cluster_essays or [])) or "(none)"
    p = _fill(prompts.OPEN_ENDED, interaction_history=history.format(),
              attribute_context=attribute_context, cluster_essay_context=ctx,
              additional_query_note_if_configured=note or "(none)")
    return _ask(llm, p)


def clarify(history, llm, function_titles=(), note=""):
    titles = "\n".join(f"- {t}" for t in function_titles) or "(none yet)"
    p = _fill(prompts.CLARIFY, interaction_history=history.format(),
              generated_function_titles=titles,
              additional_query_note_if_configured=note)
    return _ask(llm, p)


def suggest():
    return prompts.SUGGEST  # fixed text, no LLM
