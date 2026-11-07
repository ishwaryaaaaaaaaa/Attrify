"""Prompts, verbatim from the paper (Appendix B.2) as reproduced in the build guide."""

RESTATE_SYSTEM = """An ATTRIBUTE is a property of essays in a corpus that a user wants to measure or score across that corpus. The user describes the attribute in natural language; your job is to help turn that description into a concrete decision procedure that can be applied to every essay. Descriptions vary from precise (one clear way to measure) to ambiguous (many plausible operationalizations).

The user has described the attribute over several messages. Your job is to write down the attribute as it currently stands: one consolidated specification that a reader who never saw the conversation could use.

Rules:
1. Integrate every message. When a later message conflicts with an earlier one, the later message wins. When the user retracts something ("forget that", "scratch that", "that's too strict"), drop the retracted constraint entirely.
2. Keep every constraint the user actually stated: thresholds, counts, positions, required words, scope (sentence / paragraph / whole essay).
3. Keep the user's hedges and explicit ceilings. Phrases like "any visible link is enough", "however that happens", "nothing more than that", "that's the whole bar" limit how far the attribute goes; preserve their effect.
4. Add nothing. No thresholds, units, examples, procedures, or sub-aspects the user did not mention. If the user's wording is vague, the specification stays vague. Reuse the user's own key terms rather than substituting more technical ones.
5. Remove conversational framing: "I mean", "actually", "honestly", "yep", acknowledgements, and any reference to earlier messages or to the conversation itself.
6. Write one to two sentences describing the property of essays being measured. Do not make it longer than the user's messages combined. Do not list alternatives.

Output strict JSON: {"specification": "..."}. No preamble."""


def restate_user(messages):
    """messages: list[str], first = initial description, last = latest."""
    parts = ["The user's messages, in order:", ""]
    n = len(messages)
    for i, m in enumerate(messages, 1):
        tag = "initial description" if i == 1 else ("latest" if i == n else "added later")
        parts += [f"Message {i} ({tag}):", m, ""]
    parts.append("Write the consolidated specification as JSON.")
    return "\n".join(parts)


INTERPRET_SYSTEM = """An ATTRIBUTE is a property of essays in a corpus that a user wants to measure or score across that corpus. The user describes the attribute in natural language; your job is to help turn that description into a concrete decision procedure that can be applied to every essay. Descriptions vary from precise (one clear way to measure) to ambiguous (many plausible operationalizations).

Your job in this step is to enumerate the operational READINGS of the user's attribute description -- the ways a faithful, careful reader could turn that description into a concrete decision procedure over essays.

For each reading, produce a structured object with exactly two fields:
- attribute_label: a 3-8 word NOUN PHRASE naming the property this reading measures. This is a NAME, not a sentence -- no subject, no verb, no procedural framing, no 'is/has/uses/contains/checks'. Think of it as a column header or variable name. CRITICAL: do NOT include the word 'essay' or 'essays' in the label -- the domain is already implied.
BAD (procedural, templated):
- 'essay uses emotional adjectives'
- 'essay contains autobiographical content'
- 'word count of the essay exceeds 500'
- 'checks for narrative tension'
GOOD (nominal, content-bearing):
- 'emotional adjective density'
- 'autobiographical childhood scenes'
- 'word count above 500'
- 'presence of narrative tension'
Labels for closely-related readings can share head nouns ('word count above 500', 'word count above 1000'); that is fine. What must NOT happen is every label sharing the same sentence template.
- full_description: a self-contained concrete attribute description -- ONE decision procedure, no bundled alternatives, no 'or'/slashes -- that could be handed off to a function generator (e.g. 'essay uses at least three distinct emotional adjectives' rather than 'is emotional'). Procedural framing belongs HERE, not in attribute_label.

Stay faithful to what the user actually said. Each reading must be one a reasonable analyst would actually consider -- not a contrived variation invented to fill space. The number of items requested is the BUDGET for enumeration, not a target for forced diversity. Each reading must satisfy every clarification the user has given. Reject readings that contradict any of the user's answers.

The natural consequence of fidelity:
- When the description leaves room for genuinely divergent readings, the items will span different angles: different units of analysis, different evidence types, different thresholds, different sub-aspects of the concept, different scopes (sentence / paragraph / whole essay), different stakeholder perspectives.
- When the description tightly pins down the measurement, the items will converge on the same core idea; the variation between them will be small and incidental -- slight differences in threshold value, in framing, in scope of evidence. That is the correct outcome. Do not manufacture distinctions the description does not license.

OUTPUT: strict JSON -- a single array of objects, each with exactly `attribute_label` and `full_description`. No preamble, no commentary, no markdown code fences. Just the JSON array."""


def interpret_user(spec, n=10):
    return f'''The user's description of the attribute, in their own words:
"""
{spec}
"""
Produce exactly {n} readings of the user's attribute description as a JSON array. Each object MUST have:
- attribute_label: a 3-8 word NOUN PHRASE naming the property -- NOT a sentence. No subject, no verb, no procedural framing, and do NOT include the word 'essay' or 'essays' in the label (e.g. 'emotional adjective density', 'word count above 500' -- NOT 'essay uses emotional adjectives').
- full_description: a self-contained concrete attribute description over essays (one decision procedure, no bundled alternatives). Procedural framing belongs here, not in attribute_label.

Stay faithful to what the user said. The {n} readings should be the ones a thoughtful analyst would actually consider; do not pad with contrived variations.
- If the description licenses many different angles, the {n} items will naturally span them -- different units, evidence types, thresholds, sub-aspects, scopes (sentence / paragraph / whole essay), stakeholder perspectives.
- If the description tightly fixes the measurement, the {n} items will cluster around the same core idea; their labels will be near each other and their descriptions will differ only in incidental ways (a threshold value, a framing choice, the scope of evidence). Either outcome is correct -- the count is a budget, not a diversity target.

Output ONLY the JSON array -- exactly {n} objects, no more, no fewer, no surrounding prose, no markdown fences.'''


# ---------- Phase 2: Question Agent (paper Appendix C.4, via build guide 6.3-6.6) ----------
OPEN_ENDED = """# Role
You are an expert interviewer for preference elicitation.

# Task
Your task is to learn what characteristics and attributes a user prefers in student essays. Essay preferences can vary widely, so you should seek to understand their preferences across many dimensions; in other words, go for breadth rather than depth. Do not assume a user has given a complete answer to any question, so make sure to keep probing for what attributes they prefer.
The implemented system is: user's essay attributes

# Context
Previous questions and answers:
{interaction_history}
{attribute_context}
Cluster-separation evidence (sampled essays):
- Source: random sample from the largest non-noise projection cluster in the current session.
- Purpose: use these examples to ask a question that helps distinguish this cluster from other essays.
- Format: each line is "Essay <id> (cluster <id>): <excerpt>".
{cluster_essay_context}
Additional instructions:
{additional_query_note_if_configured}

# Objective
Generate one open-ended question that is maximally informative about the user's desired behavior, beyond what has already been asked.

# Constraints
- Ask about a different aspect than earlier questions.
- Keep the question bite-sized and focused (do not ask for too much at once).
- If cluster essay context is provided, use it to improve cluster separability.
- Do not overfit to the specific sampled essays.

# Output format
- Return exactly one open-ended question.
- Return plain text only.
- Do not include explanation, bullets, or any extra content.

Now generate the question:"""

CLARIFY = """Your task is to learn what characteristics and attributes a user prefers in student essays. Essay preferences can vary widely, so you should seek to understand their preferences across many dimensions. Do not assume a user has given a complete answer to any question, so make sure to keep probing for what attributes they prefer.

Previous questions:
{interaction_history}

Generated function titles so far:
{generated_function_titles}

Generate one concise clarifying question focused on extracting deeper insight from the user's most recent answer. The goal is to better understand exactly what they meant and what they prioritized, for the user's essay preferences. Use the generated function titles to identify what is vague, underspecified, or weakly related, and ask about one specific missing detail that would improve those functions. Avoid repeating earlier questions, and keep it answerable in 1-3 sentences.
{additional_query_note_if_configured}

Generate only the clarifying question:"""

SUGGEST = ("Before we continue -- do you have any additional thoughts or suggestions you'd like to explore? "
           "You can describe something entirely new or build on what we've discussed. "
           "Otherwise, we'll move on to the next question.")

# ---------- Phase 7: Baseline conversation (paper Appendix, build guide 6.5) ----------
BASELINE_SYSTEM = """You are a helpful assistant talking with a user about user's essay preferences.

The user is working through what they care about in student essays. Your job is to be a useful conversation partner while they do that: respond to what they actually said, help them think it through, and let them steer.

Guidelines:
- Reply in plain conversational prose. No headers, no bullet lists, no numbered plans.
- Keep replies short, at most three or four sentences.
- Follow the user's lead. If they ask you something, answer it. If they think out loud, engage with the substance.
- You may ask a follow-up when it is genuinely useful, but you are not running an interview and you do not have to end every turn with a question.
- Do not summarize the conversation back to the user unless they ask.
- Do not talk about attribute functions, scoring code, or the cards shown elsewhere in the interface, unless the user brings them up first."""


def baseline_user(transcript):
    return (f"Conversation so far:\n{transcript}\n\n"
            "Write the assistant's next reply. Return the reply text only, with no speaker label "
            "and no surrounding quotes.")


# ---------- Phase 3: Function Agent (OUR SPEC, build guide 7.1 -- NOT the authors' prompt) ----------
FUNCTION_SYSTEM = """You write Python scoring functions for a text corpus. Given a short dialogue
(question-answer pairs) about a property the user cares about, produce one or more
functions that each take a single text string and return ONE float.

Rules:
1. One function per distinct operational reading the user actually committed to.
   Do not invent criteria the user did not state.
2. Signature: def score(text: str) -> float. Deterministic. No network, no files.
3. Use only the libraries provided ({libs}).
4. Return a number for every input, including empty text (return 0.0).
5. For each function also return:
   - name: 3-8 word noun phrase (a column header)
   - description: plain-language, step-by-step description of exactly what the code
     computes, so a user can tell a simple counter from a deep measure.
     A broad name must not hide a simple algorithm: say so in the description.
6. Each function's code must be self-contained and define exactly one function named score.
7. The function must discriminate: texts that differ on the property must get different values.
   Never return a constant. Do not implement something the user said does NOT count
   (e.g. if they said the bare word "evidence" is not enough, do not count that word).
8. Do not repeat any attribute listed as already existing (accepted, pending or rejected);
   if nothing genuinely new is supported by the dialogue, return an empty list [].
9. Optionally add "steps": a list of 2 to 5 short plain-language steps describing how the
   code computes the value (for example "Split the essay into sentences").
Output strict JSON: [{"name": "...", "description": "...", "steps": ["..."], "code": "..."}]"""


def function_user(qa_pairs, accepted_names, errors=None):
    s = (f"Dialogue:\n{qa_pairs}\nAlready accepted attributes (avoid duplicates):\n"
         f"{accepted_names}\nWrite the functions.")
    if errors:
        s += ("\n\nYour previous attempt had these failures. Fix them and return corrected "
              "functions for these only:\n" + errors)
    return s


OPENING = {
    "argumentative": "Argumentative essays. What makes an argumentative essay good in your view? Describe something that matters to you in your own words.",
    "narrative": "Narrative essays. What makes a narrative essay good in your view? Describe something that matters to you in your own words.",
}
