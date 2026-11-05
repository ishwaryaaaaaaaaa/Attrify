"""Softness Agent: restate -> sample 10 readings -> embed labels -> Vendi -> 0-100.

LLM and embedder are injectable so the math can be tested offline.
"""
import json
import re

import numpy as np

import config
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
    raise RuntimeError(f"LLM output unusable after {config.JSON_RETRIES} tries: {last}")


# ---------- steps ----------
def restate(messages, llm):
    def check(o):
        assert isinstance(o["specification"], str) and o["specification"].strip()
    out = _call_json(llm, prompts.RESTATE_SYSTEM, prompts.restate_user(messages),
                     config.RESTATE_MODEL, config.RESTATE_TEMP, check)
    return out["specification"].strip()


def interpret(spec, llm, n=config.N_READINGS):
    def check(o):
        assert isinstance(o, list) and len(o) == n
        for r in o:
            assert r["attribute_label"].strip() and r["full_description"].strip()
    out = _call_json(llm, prompts.INTERPRET_SYSTEM, prompts.interpret_user(spec, n),
                     config.INTERPRET_MODEL, config.INTERPRET_TEMP, check)
    return out


_embedder = None


def embed(labels):
    """Embed labels only (never the generated code), L2-normalised."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(config.EMBED_MODEL)
    return _embedder.encode(labels, normalize_embeddings=True)


def vendi_from_embeddings(E):
    """Effective number of distinct items. 1 = all identical, n = all distinct."""
    n = len(E)
    K = E @ E.T
    K = (K + K.T) / 2
    K = np.clip(K, 0, 1)
    np.fill_diagonal(K, 1.0)
    lam = np.linalg.eigvalsh(K / n)
    lam = lam[lam > 1e-12]
    return float(np.exp(-np.sum(lam * np.log(lam))))


def vendi_to_softness(V, n=config.N_READINGS):
    return round(min(100, max(0, 100 * (V - 1) / (n - 1))))


def softness_of_labels(labels, embed_fn=embed):
    return vendi_to_softness(vendi_from_embeddings(np.asarray(embed_fn(labels))), len(labels))


def softness(messages, llm, runs=config.N_RUNS, embed_fn=embed):
    """Full Softness Agent. messages: user messages of the current block, in order.
    Restate once (temp 0), then sample readings `runs` times and average.
    Returns dict with score, per-run scores, specification, and readings."""
    if isinstance(messages, str):
        messages = [messages]
    spec = messages[0] if len(messages) == 1 else restate(messages, llm)
    # The sampling calls are independent network requests: run them in parallel.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, runs)) as pool:
        all_readings = list(pool.map(lambda _: interpret(spec, llm), range(runs)))
    scores = [softness_of_labels([r["attribute_label"] for r in readings], embed_fn)
              for readings in all_readings]           # embedding stays sequential
    return {"score": round(float(np.mean(scores))), "run_scores": scores,
            "specification": spec, "readings": all_readings}


def policy(s):
    """Paper Table 2."""
    if s >= config.HIGH_SOFT:
        return "clarify"            # no function generation
    if s > config.LOW_SOFT:
        return "generate_then_clarify"
    return "generate_then_suggest"
