import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import attribute_table as AT  # noqa: E402
import corpus as C  # noqa: E402
import registry as R  # noqa: E402
import session as SE  # noqa: E402

WORDS = "import re\ndef score(text):\n    return float(len(re.findall(r'\\w+', text)))\n"
NUMS = "import re\ndef score(text):\n    return float(len(re.findall(r'\\d+', text)))\n"
BAD = "def score(text):\n    return 1 / 0\n"


def make_table():
    return AT.AttributeTable(C.demo_corpus(90))


def add(table, reg, name, code):
    f = reg.add(name, "d", code)
    table.add_column(f)
    return f


def test_add_column_and_matrix_shape():
    t, reg = make_table(), R.Registry()
    add(t, reg, "words", WORDS)
    add(t, reg, "numbers", NUMS)
    assert t.matrix().shape == (90, 2) and t.names == ["words", "numbers"]
    counts, edges = t.histogram(0, bins=5)
    assert sum(counts) == 90 and len(edges) == 6


def test_broken_function_raises_and_adds_nothing():
    t, reg = make_table(), R.Registry()
    f = reg.add("bad", "d", BAD)
    with pytest.raises(ValueError):
        t.add_column(f)
    assert t.columns == []


def test_project_empty_and_single_column():
    t, reg = make_table(), R.Registry()
    assert t.project() is None and t.clusters() == (None, None) and t.cluster_sample() is None
    add(t, reg, "words", WORDS)
    P = t.project()
    assert P.shape == (90, 2) and np.allclose(P[:, 1], 0)       # padded second axis


def test_constant_column_does_not_break_standardization():
    t, reg = make_table(), R.Registry()
    add(t, reg, "const", "def score(text):\n    return 5.0\n")
    add(t, reg, "words", WORDS)
    assert np.isfinite(t.project()).all()


def test_clusters_and_sampler():
    t, reg = make_table(), R.Registry()
    add(t, reg, "words", WORDS)
    add(t, reg, "numbers", NUMS)
    P, labels = t.clusters()
    assert P.shape == (90, 2) and labels.shape == (90,)
    sample = t.cluster_sample(k=4, excerpt_chars=50)
    if sample is not None:                                       # clusters can legitimately be absent
        assert len(sample) <= 4 and all(len(x[2]) <= 50 for x in sample)
        assert all(isinstance(x[0], int) for x in sample)


def test_session_accept_adds_column_and_failure_keeps_pending():
    import json
    good = json.dumps([{"name": "word count", "description": "d", "code": WORDS}])
    bad = json.dumps([{"name": "boom", "description": "d", "code": BAD}])

    class LLM:
        def __init__(self, out):
            self.out = out

        def __call__(self, system, user, model, temp):
            return self.out if "scoring functions" in system else "q?"

    t = make_table()
    s = SE.Session(LLM(good), R.Registry(), table=t, softness_fn=lambda m: {"score": 50})
    s.start()
    r = s.submit_answer("count words")
    s.review(r["new_functions"][0].id, "accept")
    assert t.names == ["word count"] and s.cluster_provider is not None

    # function that passes the 9 sandbox samples but would fail on the corpus -> stays pending
    s2 = SE.Session(LLM(good), R.Registry(), table=t, softness_fn=lambda m: {"score": 50})
    s2.start()
    r2 = s2.submit_answer("x")
    f = r2["new_functions"][0]
    f.code = ("def score(text):\n    if len(text) > 10 ** 6:\n        return 0.0\n"
              "    return 1 / (len(text) - len(text))\n")
    with pytest.raises(ValueError):
        s2.review(f.id, "accept")
    assert f.status == "pending"
    del bad
