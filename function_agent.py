"""Function Agent: generate -> validate (AST) -> execute in sandbox -> observe -> retry.

Extra checks beyond the guide's minimum (found necessary in the Phase 4 live run):
  * constant-output check: a function returning the same value on every sample text is
    sent back for repair; if it is still constant on the last try it is kept but flagged.
  * duplicate filter: same normalized name, or an identical value vector to an existing
    (non-refined) function, is dropped.
Passing all checks still does NOT prove the function matches user intent.
"""
import re

import config
import prompts
import sandbox
from softness import _parse_json

MAX_TRIES = 3


def _norm(name):
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def _generate(llm, qa_pairs, avoid_names, errors=None):
    system = prompts.FUNCTION_SYSTEM.replace("{libs}", ", ".join(sandbox.ALLOWED_IMPORTS))
    user = prompts.function_user(qa_pairs, "\n".join(avoid_names) or "(none)", errors)
    out = _parse_json(llm(system, user, config.FUNCTION_MODEL, config.FUNCTION_TEMP))
    assert isinstance(out, list)
    return [{"name": str(o["name"]).strip(), "description": str(o["description"]).strip(),
             "code": str(o["code"])} for o in out]


def _is_constant(vals):
    return len(set(round(v, 9) for v in vals)) <= 1


def _duplicate_of(name, vals, existing):
    """existing: Func objects. Returns the duplicated function or None."""
    for f in existing:
        if f.status == "refined":
            continue
        if _norm(f.name) == _norm(name):
            return f
        if f.sample_values and not _is_constant(vals) and \
                [round(v, 6) for v in f.sample_values] == [round(v, 6) for v in vals]:
            return f
    return None


def generate_functions(qa_pairs, registry, llm, samples=None, max_tries=MAX_TRIES):
    """Returns (new_funcs, failures). New funcs are added to the registry as 'pending'.
    Funcs that stayed constant carry a warning in func.warnings."""
    samples = samples or sandbox.SAMPLE_TEXTS
    kept, errors = [], None
    for attempt in range(1, max_tries + 1):
        last = attempt == max_tries
        avoid = [f.name for f in registry.funcs if f.status != "refined"]  # incl. rejected
        try:
            cands = _generate(llm, qa_pairs, avoid, errors)
        except (ValueError, KeyError, TypeError, AssertionError) as e:
            errors = f"Output was not the required JSON list of objects ({e})."
            continue
        feedback = []
        for c in cands:
            vals, err = sandbox.run(c["code"], samples)
            if err:
                feedback.append(f"- {c['name']}: {err}")
                continue
            assert vals is not None
            dup = _duplicate_of(c["name"], vals, registry.funcs)
            if dup:
                feedback.append(f"- {c['name']}: duplicate of existing attribute '{dup.name}'; "
                                "propose a genuinely different reading or return nothing for it.")
                continue
            if _is_constant(vals) and not last:
                feedback.append(f"- {c['name']}: returned {vals[0]} on all {len(vals)} sample texts, "
                                "including texts that clearly differ on this property. Make it "
                                "discriminate, e.g. by counting/measuring the actual pattern.")
                continue
            f = registry.add(c["name"], c["description"], c["code"], vals)
            if _is_constant(vals):
                f.warnings.append(f"Returned {vals[0]} on every sample text; may not measure anything.")
            kept.append(f)
        if kept and not feedback:
            return kept, []
        if kept and attempt > 1:        # already have usable output; don't loop for extras
            return kept, feedback
        errors = "\n".join(feedback) if feedback else "No functions were returned."
        if kept:                        # first attempt: keep good ones, repair the rest only
            errors = "Only the following failed; return corrected versions for these only:\n" + errors
    return kept, (errors.splitlines() if errors else [])
