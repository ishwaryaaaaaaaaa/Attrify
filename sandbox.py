"""Sandbox: AST validation + subprocess execution with timeout (and memory limit on POSIX).

LIMITS (honest): this is a best-effort guard for LLM-written scoring code on your own
machine, not a security boundary. No network blocking; Windows has no RLIMIT_AS here.
"""
import ast
import importlib.util
import json
import math
import subprocess
import sys

CANDIDATE_LIBS = ["re", "math", "collections", "numpy", "spacy", "sentence_transformers"]
ALLOWED_IMPORTS = [m for m in CANDIDATE_LIBS if importlib.util.find_spec(m) is not None]
BANNED_NAMES = {"eval", "exec", "open", "compile", "__import__", "input", "globals",
                "locals", "getattr", "setattr", "delattr", "vars", "breakpoint"}
TIMEOUT_S = 60
MEM_MB = 1024

SAMPLE_TEXTS = [
    "",
    "Schools should start later. Teenagers need more sleep, and studies show tired students perform worse.",
    "I remember the summer my grandmother taught me to fish. The lake was cold and quiet.",
    "Some people think homework is useless; however, evidence suggests moderate homework helps. For example, "
    "a 2019 survey found gains in math. In conclusion, homework should stay.",
    "Good essays are good.",
    "According to a 2021 study (Lee, 2021), 63% of students who slept eight hours scored higher. "
    "Another report found a 12% drop in absences. A third survey of 1,200 teens agreed.",
    "Honestly I think pineapple on pizza is great! My friends hate it but they are wrong. "
    "Taste is personal, and mine is excellent.",
    "First, the policy is expensive. Second, it is unfair. Third, it has failed elsewhere. "
    "Finally, critics argue the opposite, but their claim ignores the data.",
    "The old house stood at the end of a long gravel road, its windows dark, its porch sagging under years of "
    "rain. Nobody had lived there since the flood, and the town preferred it that way.",
]


def validate(code):
    """Return None if OK, else an error string. Checks syntax, imports, banned names, score()."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError: {e}"
    has_score = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    return f"Import not allowed: {a.name}. Allowed: {ALLOWED_IMPORTS}"
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                return f"Import not allowed: {node.module}. Allowed: {ALLOWED_IMPORTS}"
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            return f"Name not allowed: {node.id}"
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return f"Dunder attribute not allowed: {node.attr}"
        elif isinstance(node, ast.FunctionDef) and node.name == "score":
            has_score = True
    return None if has_score else "Code must define a function named score(text)"


_RUNNER = """
import sys, json
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (MEM_MB * 1024 * 1024,) * 2)
except Exception:
    pass
req = json.loads(sys.stdin.read())
ns = {}
exec(req["code"], ns)
out = []
for t in req["texts"]:
    try:
        out.append({"ok": True, "v": float(ns["score"](t))})
    except Exception as e:
        out.append({"ok": False, "err": type(e).__name__ + ": " + str(e)})
print("@@RESULT@@" + json.dumps(out))
""".replace("MEM_MB", str(MEM_MB))


def run(code, texts):
    """Execute score() on each text. Returns (values|None, error|None).
    values are finite floats; any failure returns an error string for the retry loop."""
    err = validate(code)
    if err:
        return None, err
    try:
        p = subprocess.run([sys.executable, "-I", "-c", _RUNNER],
                           input=json.dumps({"code": code, "texts": texts}),
                           capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return None, f"Timeout: exceeded {TIMEOUT_S}s"
    if p.returncode != 0 or "@@RESULT@@" not in p.stdout:
        return None, "Execution failed: " + (p.stderr.strip().splitlines() or ["unknown error"])[-1]
    res = json.loads(p.stdout.split("@@RESULT@@")[-1])
    vals = []
    for i, r in enumerate(res):
        if not r["ok"]:
            return None, f"Error on sample {i}: {r['err']}"
        if not math.isfinite(r["v"]):
            return None, f"Non-finite value on sample {i}: {r['v']}"
        vals.append(r["v"])
    return vals, None
