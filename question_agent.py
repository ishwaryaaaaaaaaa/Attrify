"""Question Agent: open-ended, clarifying, suggestion. Plus the interaction history."""
from dataclasses import dataclass, field

import config
import pipeline_trace as PT
import prompts


@dataclass
class Turn:
    qtype: str          # "open_ended" | "clarify" | "suggest"
    question: str
    answer: str = ""
    softness: int | None = None
    specification: str = ""                       # the restated description the score was based on
    keywords: list = field(default_factory=list)  # two-word label for the history node


_STOP = set("i a an the and or of to in is it that this be are was for on with as my me but not so at by "
            "if im id just like really very want mean should would could can will have has had do does "
            "yes no there their they them we you your our its what which who how why when where".split())


def keywords(text, k=2):
    """Cheap local keywords (no LLM call): most frequent non-stopwords, first-seen order breaks ties."""
    import re
    words = [w for w in re.findall(r"[a-z][a-z'-]{2,}", (text or "").lower()) if w not in _STOP]
    freq = {}
    for i, w in enumerate(words):
        n, first = freq.get(w, (0, i))
        freq[w] = (n + 1, first)
    return [w for w, _ in sorted(freq.items(), key=lambda kv: (-kv[1][0], kv[1][1]))[:k]]


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
    out = llm("", prompt, config.QUESTION_MODEL, config.QUESTION_TEMP).strip().strip('"')
    PT.attach(outputs={"question": out})
    return out


def opening(genre):
    """Fixed first question, identical for both study conditions."""
    PT.add("Question Agent", "Opening question (fixed text)", "compute",
           note="The first question is fixed and identical in both study conditions. No model is called.",
           inputs={"genre": genre}, outputs={"question": prompts.OPENING[genre]})
    return prompts.OPENING[genre]


def open_ended(history, llm, cluster_essays=None, attribute_context="", note=""):
    """cluster_essays: list of (essay_id, cluster_id, excerpt) from the largest
    non-noise cluster (Phase 5 supplies this); None -> no cluster evidence."""
    ctx = "\n".join(f"Essay {i} (cluster {c}): {x}" for i, c, x in (cluster_essays or [])) or "(none)"
    p = _fill(prompts.OPEN_ENDED, interaction_history=history.format(),
              attribute_context=attribute_context, cluster_essay_context=ctx,
              additional_query_note_if_configured=note or "(none)")
    with PT.scope("Question Agent", "Open-ended question",
                  "A new topic: the prompt holds the whole history and sample essays from the largest cluster of the "
                  "coverage graph, so the model asks about something the accepted attributes do not separate yet."):
        return _ask(llm, p)


def clarify(history, llm, function_titles=(), note=""):
    titles = "\n".join(f"- {t}" for t in function_titles) or "(none yet)"
    p = _fill(prompts.CLARIFY, interaction_history=history.format(),
              generated_function_titles=titles,
              additional_query_note_if_configured=note)
    with PT.scope("Question Agent", "Clarifying question",
                  "The prompt holds the history and the titles of the generated functions, so the model asks about "
                  "the one detail that is still vague."):
        return _ask(llm, p)


def suggest():
    PT.add("Question Agent", "Suggestion invitation (fixed text)", "compute",
           note="The attribute was pinned down (softness at most 30), so the system invites more ideas. Fixed text, no model call.",
           outputs={"question": prompts.SUGGEST})
    return prompts.SUGGEST  # fixed text, no LLM
