import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import function_agent as F  # noqa: E402
import registry as R  # noqa: E402
import sandbox as SB  # noqa: E402

GOOD = "import re\ndef score(text):\n    return float(len(re.findall(r'\\w+', text)))\n"


def test_validate_rejections():
    assert SB.validate(GOOD) is None
    assert "Import not allowed" in SB.validate("import os\ndef score(t): return 0.0")
    assert "Import not allowed" in SB.validate("from subprocess import run\ndef score(t): return 0.0")
    assert "Name not allowed" in SB.validate("def score(t):\n    return float(len(open('x').read()))")
    assert "Name not allowed" in SB.validate("def score(t):\n    exec('1')\n    return 0.0")
    assert "Dunder" in SB.validate("def score(t):\n    return float(t.__class__ is str)")
    assert "SyntaxError" in SB.validate("def score(t) return 0")
    assert "named score" in SB.validate("def other(t): return 0.0")


def test_run_ok_and_empty_text():
    vals, err = SB.run(GOOD, ["", "one two three"])
    assert err is None and vals == [0.0, 3.0]


def test_run_reports_runtime_error_and_nonfinite():
    _, err = SB.run("def score(t):\n    return 1 / 0\n", ["x"])
    assert "ZeroDivisionError" in err
    _, err = SB.run("def score(t):\n    return float('nan')\n", ["x"])
    assert "Non-finite" in err


def test_run_timeout(monkeypatch):
    monkeypatch.setattr(SB, "TIMEOUT_S", 2)
    _, err = SB.run("def score(t):\n    while True:\n        pass\n", ["x"])
    assert "Timeout" in err


def _fn(name, code):
    return {"name": name, "description": "d", "code": code}


def test_agent_retries_with_error_feedback():
    calls = []
    bad = _fn("word count", "import os\ndef score(t): return 0.0")
    good = _fn("word count", GOOD)
    outs = iter([json.dumps([bad]), json.dumps([good])])

    def llm(system, user, model, temp):
        calls.append(user)
        return next(outs)
    reg = R.Registry()
    funcs, failures = F.generate_functions("Q: x\nA: y", reg, llm)
    assert len(funcs) == 1 and failures == [] and len(calls) == 2
    assert "Import not allowed: os" in calls[1]          # error text sent back
    assert funcs[0].status == "pending" and funcs[0].sample_values[0] == 0.0


def test_agent_gives_up_and_reports():
    bad = json.dumps([_fn("x", "def score(t): return 1/0")])
    reg = R.Registry()
    funcs, failures = F.generate_functions("q", reg, lambda *a: bad, max_tries=2)
    assert funcs == [] and failures


def test_registry_lifecycle():
    reg = R.Registry()
    f = reg.add("a", "desc", GOOD)
    reg.set_status(f.id, "accepted")
    assert reg.accepted_names() == ["a"]
    reg.refine(f.id, "a2", "desc2", GOOD)
    assert f.status == "pending" and f.versions[0][0] == "a" and reg.accepted_names() == []


CONST = "def score(text):\n    return 0.0\n"
STATS = "import re\ndef score(text):\n    return float(len(re.findall(r'\\d+%?', text)))\n"


def test_constant_function_is_sent_back_then_repaired():
    calls = []
    outs = iter([json.dumps([_fn("stat count", CONST)]), json.dumps([_fn("stat count", STATS)])])

    def llm(system, user, model, temp):
        calls.append(user)
        return next(outs)
    reg = R.Registry()
    funcs, failures = F.generate_functions("q", reg, llm)
    assert len(funcs) == 1 and failures == [] and funcs[0].warnings == []
    assert "all" in calls[1] and "sample texts" in calls[1]       # feedback mentions the constant


def test_constant_kept_with_warning_on_last_try():
    reg = R.Registry()
    funcs, _ = F.generate_functions("q", reg, lambda *a: json.dumps([_fn("x", CONST)]), max_tries=2)
    assert len(funcs) == 1 and funcs[0].warnings


def test_duplicate_name_and_values_dropped():
    reg = R.Registry()
    existing = reg.add("Stat Count", "d", STATS, [1.0, 2.0])
    reg.set_status(existing.id, "rejected")                       # rejected still blocks repeats
    dup_name = json.dumps([_fn("stat count!", STATS)])
    funcs, failures = F.generate_functions("q", reg, lambda *a: dup_name, max_tries=2)
    assert funcs == [] and any("duplicate" in f for f in failures)
    # same values under a new name is also a duplicate
    vals, _ = SB.run(STATS, SB.SAMPLE_TEXTS)
    reg2 = R.Registry()
    reg2.add("other name", "d", STATS, vals)
    out = json.dumps([_fn("brand new name", STATS)])
    funcs, _ = F.generate_functions("q", reg2, lambda *a: out, max_tries=1)
    assert funcs == []


def test_samples_are_varied():
    assert len(SB.SAMPLE_TEXTS) >= 8 and SB.SAMPLE_TEXTS[0] == ""
