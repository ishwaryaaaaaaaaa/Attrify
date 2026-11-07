"""Softness Agent: restate -> sample 10 readings -> embed labels -> Vendi -> 0-100.

LLM and embedder are injectable so the math can be tested offline.
Every stage is recorded in pipeline_trace (inputs, outputs, the matrices and eigenvalues) for the UI.
"""
import contextvars
import json
import re
import time

import numpy as np

import config
import pipeline_trace as PT
import prompts


# ---------- LLM (OpenAI-compatible) ----------
class LLM:
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI(base_url=config.BASE_URL) if config.BASE_URL else OpenAI()

    def __call__(self, system, user, model, temperature):
        r = self.client.chat.completions.create(
            model=model, temperature=temperature,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        return r.choices[0].message.content


def _parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)  # tolerate stray fences
    return json.loads(text)


def _call_json(llm, system, user, model, temp, check):
    last = None
    for _ in range(config.JSON_RETRIES):
        text = llm(system, user, model, temp)  # API errors propagate, not retried
        try:
            out = _parse_json(text)
            check(out)
            return out
        except (ValueError, KeyError, TypeError, AssertionError) as e:  # bad JSON / shape
            last = e
            PT.note_retry(f"unusable answer ({type(e).__name__}: {e}); asking again")
    raise RuntimeError(f"LLM output unusable after {config.JSON_RETRIES} tries: {last}")


# ---------- steps ----------
def restate(messages, llm):
    def check(o):
        assert isinstance(o["specification"], str) and o["specification"].strip()
    with PT.scope("Softness Agent", "1 · Restate the messages",
                  "Merge every message of this block into one specification (later messages win)."):
        out = _call_json(llm, prompts.RESTATE_SYSTEM, prompts.restate_user(messages),
                         config.RESTATE_MODEL, config.RESTATE_TEMP, check)
        spec = out["specification"].strip()
        PT.attach(outputs={"specification": spec})
    return spec


def interpret(spec, llm, n=config.N_READINGS, run=None):
    def check(o):
        assert isinstance(o, list) and len(o) == n
        for r in o:
            assert r["attribute_label"].strip() and r["full_description"].strip()
    tag = f" (run {run})" if run else ""
    with PT.scope("Softness Agent", f"2 · Sample {n} readings{tag}",
                  f"The model lists {n} different ways a careful reader could measure the attribute "
                  f"(temperature {config.INTERPRET_TEMP}, so every run differs a little)."):
        out = _call_json(llm, prompts.INTERPRET_SYSTEM, prompts.interpret_user(spec, n),
                         config.INTERPRET_MODEL, config.INTERPRET_TEMP, check)
        PT.attach(outputs={"readings": len(out), "labels": [r["attribute_label"] for r in out]},
                  viz=[{"type": "readings",
                        "items": [{"label": r["attribute_label"], "description": r["full_description"]} for r in out]}])
    return out


_embedder = None


def embed(labels):
    """Embed labels only (never the generated code), L2-normalised."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(config.EMBED_MODEL)
    return _embedder.encode(labels, normalize_embeddings=True)


def vendi_details(E):
    """Everything the Vendi score is made of: K, its eigenvalues, the entropy and V."""
    n = len(E)
    K = E @ E.T
    K = (K + K.T) / 2
    K = np.clip(K, 0, 1)
    np.fill_diagonal(K, 1.0)
    all_lam = np.linalg.eigvalsh(K / n)[::-1]            # largest first
    lam = all_lam[all_lam > 1e-12]
    H = float(-np.sum(lam * np.log(lam)))
    return {"K": K, "eigenvalues": all_lam, "entropy": H, "V": float(np.exp(H))}


def vendi_from_embeddings(E):
    """Effective number of distinct items. 1 = all identical, n = all distinct."""
    return vendi_details(E)["V"]


def vendi_to_softness(V, n=config.N_READINGS):
    return round(min(100, max(0, 100 * (V - 1) / (n - 1))))


def _score_run(labels, embed_fn, run=None):
    """Embed the labels, build K, compute Vendi and softness for ONE sample of readings, tracing each stage."""
    tag = f" (run {run})" if run else ""
    n = len(labels)
    t0 = time.perf_counter()
    E = np.asarray(embed_fn(labels))
    t1 = time.perf_counter()
    d = vendi_details(E)
    t2 = time.perf_counter()
    K, V = d["K"], d["V"]
    s = vendi_to_softness(V, n)
    off = (float(K.sum()) - n) / max(n * (n - 1), 1)
    PT.add("Softness Agent", f"3 · Embed labels and compare them{tag}", "compute",
           note="Only the 3-8 word labels are embedded (not the long descriptions). K[i][j] is the cosine similarity "
                "of label i and label j: near 1 = the same idea, near 0 = unrelated.",
           inputs={"labels": list(labels), "embedding_model": config.EMBED_MODEL},
           outputs={"embedding_shape": list(E.shape),
                    "first_label_vector_first_6": [round(float(x), 3) for x in E[0][:6]],
                    "average_similarity_between_labels": round(off, 3)},
           viz=[{"type": "matrix", "title": "K = E·Eᵀ  (cosine similarity between labels)",
                 "labels": list(labels), "values": np.round(K, 2).tolist()}],
           ms=round((t1 - t0) * 1000))
    lam = d["eigenvalues"]
    PT.add("Softness Agent", f"4 · Vendi score → softness{tag}", "compute",
           note="The Vendi score is the effective number of different readings: 1 = all labels say the same thing, "
                f"{n} = all completely different. It is exp(entropy) of the eigenvalues of K/n.",
           inputs={"K": f"{n}×{n} matrix above", "n": n},
           outputs={"entropy_H": round(d["entropy"], 4), "vendi_V": round(V, 3), "softness": s},
           viz=[{"type": "bars", "title": "Eigenvalues of K/n (they add up to 1)",
                 "labels": [f"λ{i + 1}" for i in range(len(lam))], "values": [round(float(x), 4) for x in lam]},
                {"type": "formula", "lines": [
                    f"K = E·Eᵀ, made symmetric, clipped to [0, 1], diagonal set to 1   (n = {n})",
                    f"λ = eigenvalues of K/n,   Σλ = {float(np.sum(lam)):.3f}",
                    f"H = −Σ λ·ln λ = {d['entropy']:.4f}",
                    f"V = exp(H) = {V:.3f}   (the effective number of distinct readings)",
                    f"softness = round(100 · (V − 1) / (n − 1)) = round(100 · {V - 1:.3f} / {n - 1}) = {s}"]}],
           ms=round((t2 - t1) * 1000))
    return s


def softness_of_labels(labels, embed_fn=None):
    return _score_run(list(labels), embed_fn or embed)


def softness(messages, llm, runs=config.N_RUNS, embed_fn=None):
    """Full Softness Agent. messages: user messages of the current block, in order.
    Restate once (temp 0), then sample readings `runs` times and average.
    Returns dict with score, per-run scores, specification, and readings."""
    embed_fn = embed_fn or embed        # looked up now (not at import) so tests and the fake server can replace it
    if isinstance(messages, str):
        messages = [messages]
    PT.add("Softness Agent", "0 · Messages of this block", "io",
           note="Softness is computed from ALL user messages since the current topic started, not only the last one.",
           inputs={"messages": list(messages)})
    if len(messages) == 1:
        spec = messages[0]
        PT.add("Softness Agent", "1 · Restate (skipped)", "compute",
               note="Only one message in this block, so it is used word for word. "
                    "From two messages on, a model merges them into one specification.",
               outputs={"specification": spec})
    else:
        spec = restate(messages, llm)
    # The sampling calls are independent network requests: run them in parallel. Each task runs in a copy of
    # the current context so its trace labels stay its own.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, runs)) as pool:
        futures = [pool.submit(contextvars.copy_context().run, interpret, spec, llm, config.N_READINGS, k + 1)
                   for k in range(runs)]
        all_readings = [f.result() for f in futures]
    scores = [_score_run([r["attribute_label"] for r in readings], embed_fn, k + 1)
              for k, readings in enumerate(all_readings)]          # embedding stays sequential
    score = round(float(np.mean(scores)))
    PT.add("Softness Agent", "5 · Average the runs", "compute",
           note="The sampling is repeated and averaged so one lucky or unlucky sample does not decide the score.",
           inputs={"run_scores": scores}, outputs={"softness": score},
           viz=[{"type": "formula",
                 "lines": [f"softness = round(({' + '.join(str(x) for x in scores)}) / {len(scores)}) = {score}"]}])
    return {"score": score, "run_scores": scores, "specification": spec, "readings": all_readings}


def policy(s):
    """Paper Table 2."""
    if s >= config.HIGH_SOFT:
        return "clarify"            # no function generation
    if s > config.LOW_SOFT:
        return "generate_then_clarify"
    return "generate_then_suggest"
