"""Function Agent: generate -> validate (AST) -> execute in sandbox -> observe -> retry.

Extra checks beyond the guide's minimum (found necessary in the Phase 4 live run):
  * constant-output check: a function returning the same value on every sample text is
    sent back for repair; if it is still constant on the last try it is kept but flagged.
  * duplicate filter: same normalized name, or an identical value vector to an existing
    (non-refined) function, is dropped.
Passing all checks still does NOT prove the function matches user intent.
"""
import re
import time

import config
import pipeline_trace as PT
import prompts
import sandbox
from softness import _parse_json

MAX_TRIES = 3


def _norm(name):
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def derive_steps(description):
    """Fallback 'how it works' steps: split the description into sentences."""
    parts = [p.strip() for p in re.split(r"(?<=[.;!?])\s+|\n+", description) if p.strip()]
    return parts[:6] or [description.strip()]


def method_type(code):
    """Heuristic tag shown on cards (the paper found 63% word lists, 26% surface statistics)."""
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return "surface statistic"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if any(m.split(".")[0] in ("sklearn", "transformers", "sentence_transformers", "torch", "spacy")
                   for m in mods):
                return "model-based"
        if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
            strs = [e for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(strs) >= 5:
                return "word-list check"
    return "surface statistic"


def _generate(llm, qa_pairs, avoid_names, errors=None):
    system = prompts.FUNCTION_SYSTEM.replace("{libs}", ", ".join(sandbox.ALLOWED_IMPORTS))
    user = prompts.function_user(qa_pairs, "\n".join(avoid_names) or "(none)", errors)
    out = _parse_json(llm(system, user, config.FUNCTION_MODEL, config.FUNCTION_TEMP))
    assert isinstance(out, list)
    res = []
    for o in out:
        steps = o.get("steps")
        steps = [str(s).strip() for s in steps if str(s).strip()] if isinstance(steps, list) else []
        res.append({"name": str(o["name"]).strip(), "description": str(o["description"]).strip(),
                    "code": str(o["code"]), "steps": steps})
    return res


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


def _trace_check(c, samples, vals, err, ast_error, verdict, ms, dup=None):
    """One trace step per candidate: AST rules, sandbox run on the sample texts, duplicate/constant checks."""
    viz = [{"type": "code", "title": "Code written by the model", "code": c["code"]}]
    if vals is not None:
        viz.append({"type": "table", "title": "What the function returned on each sample text",
                    "columns": ["#", "sample text", "value"],
                    "rows": [[i + 1, (t[:70] + "…") if len(t) > 70 else (t or "(empty text)"), round(v, 4)]
                             for i, (t, v) in enumerate(zip(samples, vals))]})
    PT.add("Function Agent", f"2 · Check “{c['name']}”", "sandbox",
           note="1) AST check: allowed imports only, no eval/open/getattr, must define score(text). "
                "2) Run score() in a separate Python process (timeout) on the sample texts. "
                "3) Reject duplicates and constant outputs.",
           inputs={"name": c["name"], "allowed_imports": sandbox.ALLOWED_IMPORTS, "sample_texts": len(samples)},
           outputs={"ast_check": ast_error or "passed", "sandbox_error": err, "duplicate_of": dup,
                    "values": None if vals is None else [round(v, 4) for v in vals], "verdict": verdict},
           viz=viz, ms=ms, status="ok" if verdict.startswith("kept") else "retry")


def generate_functions(qa_pairs, registry, llm, samples=None, max_tries=MAX_TRIES,
                       on_stage=None, on_card=None):
    """Returns (new_funcs, failures). New funcs are added to the registry as 'pending'.
    Funcs that stayed constant carry a warning in func.warnings.
    on_stage(text) / on_card(func) are optional UI hooks (status line and streamed cards)."""
    PT.add("Function Agent", "0 · Dialogue given to the Function Agent", "io",
           note="The question-answer pairs of this block, plus the names of attributes that already exist "
                "(so it does not repeat them).",
           inputs={"dialogue": qa_pairs,
                   "existing_attributes": [f.name for f in registry.funcs if f.status != "refined"]})
    kept, failures = _generate_functions(qa_pairs, registry, llm, samples, max_tries, on_stage, on_card)
    PT.add("Function Agent", "3 · Cards proposed", "decision",
           note="Every kept function becomes a card the user must accept, reject or refine.",
           outputs={"cards": [f.name for f in kept], "failures": failures})
    return kept, failures


def _generate_functions(qa_pairs, registry, llm, samples, max_tries, on_stage, on_card):
    samples = samples or sandbox.SAMPLE_TEXTS
    stage = on_stage or (lambda *_: None)
    kept, errors = [], None
    stage("Planning…")
    for attempt in range(1, max_tries + 1):
        last = attempt == max_tries
        avoid = [f.name for f in registry.funcs if f.status != "refined"]  # incl. rejected
        stage("Writing code…")
        try:
            with PT.scope("Function Agent", f"1 · Write code (attempt {attempt})",
                          "The model reads the dialogue and writes one Python score(text) function per reading the user committed to."
                          + (" The failures of the previous attempt are included in the prompt." if errors else "")):
                cands = _generate(llm, qa_pairs, avoid, errors)
                PT.attach(outputs={"functions": [{"name": c["name"], "description": c["description"], "steps": c["steps"]}
                                                 for c in cands]})
        except (ValueError, KeyError, TypeError, AssertionError) as e:
            PT.note_retry(f"Output was not the required JSON list of objects ({e})")
            errors = f"Output was not the required JSON list of objects ({e})."
            continue
        feedback = []
        stage("Checking the code…")
        for c in cands:
            stage("Trying it on sample essays…")
            ast_error = sandbox.validate(c["code"])
            t0 = time.perf_counter()
            vals, err = sandbox.run(c["code"], samples)
            ms = round((time.perf_counter() - t0) * 1000)
            if err:
                feedback.append(f"- {c['name']}: {err}")
                _trace_check(c, samples, vals, err, ast_error, "sent back to the model: " + err, ms)
                continue
            assert vals is not None
            dup = _duplicate_of(c["name"], vals, registry.funcs)
            if dup:
                feedback.append(f"- {c['name']}: duplicate of existing attribute '{dup.name}'; "
                                "propose a genuinely different reading or return nothing for it.")
                _trace_check(c, samples, vals, err, ast_error, f"dropped: duplicate of '{dup.name}'", ms, dup.name)
                continue
            if _is_constant(vals) and not last:
                feedback.append(f"- {c['name']}: returned {vals[0]} on all {len(vals)} sample texts, "
                                "including texts that clearly differ on this property. Make it "
                                "discriminate, e.g. by counting/measuring the actual pattern.")
                _trace_check(c, samples, vals, err, ast_error, f"sent back: constant output ({vals[0]}) on every sample", ms)
                continue
            f = registry.add(c["name"], c["description"], c["code"], vals)
            f.steps = c["steps"] or derive_steps(c["description"])
            f.method_type = method_type(c["code"])
            if _is_constant(vals):
                f.warnings.append(f"Returned {vals[0]} on every sample text; may not measure anything.")
            _trace_check(c, samples, vals, err, ast_error,
                         "kept as a card" + (" (flagged: constant output)" if _is_constant(vals) else ""), ms)
            kept.append(f)
            if on_card:
                on_card(f)
        if kept and not feedback:
            return kept, []
        if kept and attempt > 1:        # already have usable output; don't loop for extras
            return kept, feedback
        errors = "\n".join(feedback) if feedback else "No functions were returned."
        if kept:                        # first attempt: keep good ones, repair the rest only
            errors = "Only the following failed; return corrected versions for these only:\n" + errors
    return kept, (errors.splitlines() if errors else [])
