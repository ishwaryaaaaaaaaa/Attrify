"""Offline tests (no API, no model download). Run: python -m pytest tests -q  (from attrify/)"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import softness as S  # noqa: E402


def test_vendi_identical_is_one():
    E = np.tile(np.array([[1.0, 0.0, 0.0]]), (10, 1))
    assert abs(S.vendi_from_embeddings(E) - 1.0) < 1e-6
    assert S.vendi_to_softness(1.0) == 0


def test_vendi_orthogonal_is_n():
    E = np.eye(10)
    assert abs(S.vendi_from_embeddings(E) - 10.0) < 1e-6
    assert S.vendi_to_softness(10.0) == 100


def test_vendi_monotone():
    rng = np.random.default_rng(0)
    base = rng.normal(size=(1, 16))
    tight = base + 0.05 * rng.normal(size=(10, 16))
    loose = base + 1.0 * rng.normal(size=(10, 16))
    norm = lambda x: x / np.linalg.norm(x, axis=1, keepdims=True)  # noqa: E731
    assert S.vendi_from_embeddings(norm(tight)) < S.vendi_from_embeddings(norm(loose))


def test_policy_table():
    assert S.policy(65) == "clarify" and S.policy(90) == "clarify"
    assert S.policy(64) == "generate_then_clarify" and S.policy(31) == "generate_then_clarify"
    assert S.policy(30) == "generate_then_suggest" and S.policy(0) == "generate_then_suggest"


def test_json_retry_and_fence_tolerance():
    good = json.dumps([{"attribute_label": f"label {i}", "full_description": f"d{i}"} for i in range(10)])
    outs = iter(["not json", "```json\n" + good + "\n```"])
    llm = lambda *a, **k: next(outs)  # noqa: E731
    assert len(S.interpret("x", llm)) == 10


def test_json_wrong_count_retries_then_fails():
    bad = json.dumps([{"attribute_label": "a", "full_description": "b"}] * 9)
    llm = lambda *a, **k: bad  # noqa: E731
    try:
        S.interpret("x", llm)
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError")


def test_restate_called_for_multi_message():
    calls = []

    def llm(system, user, model, temp):
        calls.append((user, temp))
        return '{"specification": "merged"}'
    spec = S.softness.__globals__["restate"](["a", "b", "c"], llm)
    assert spec == "merged"
    assert "Message 3 (latest):" in calls[0][0] and calls[0][1] == 0.0


def test_softness_runs_in_parallel_and_averages():
    import threading
    import time
    seen = set()
    good = json.dumps([{"attribute_label": f"label {i}", "full_description": f"d{i}"} for i in range(10)])

    def llm(system, user, model, temp):
        seen.add(threading.get_ident())
        time.sleep(0.2)
        return good
    fake_embed = lambda labels: np.eye(len(labels))   # noqa: E731  -> all distinct -> softness 100
    t0 = time.time()
    r = S.softness(["x"], llm, runs=3, embed_fn=fake_embed)
    assert r["score"] == 100 and r["run_scores"] == [100, 100, 100]
    assert len(seen) == 3 and time.time() - t0 < 0.55       # 3 x 0.2s would be 0.6s if sequential
