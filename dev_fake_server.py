"""Run the real server with a scripted fake LLM and a scripted softness score (no API key, no cost).

    python dev_fake_server.py            # http://localhost:8001

Use it to try the UI end to end: real FastAPI routes, real sandbox, real PCA/DBSCAN, and the REAL softness
maths (Vendi score) on scripted readings, so the Pipeline Inspector shows genuine matrices and eigenvalues.
Only the language model and the embedder are fake: the readings cycle from very open to very pinned down.
Never use it to judge answer quality.
"""
import itertools
import json
import sys

import uvicorn

import softness as S

LIB = [
    ("Thesis claim words", "Counts claim words such as should, must and believe.",
     ["Lower-case the essay.", "Count words from a claim-word list.", "Return the count."],
     "import re\nCLAIM = {'should','must','believe','need','ought'}\ndef score(text):\n    w = re.findall(r'[a-z]+', text.lower())\n    return float(sum(1 for x in w if x in CLAIM))\n"),
    ("Statistics mentioned", "Counts digit runs such as years and percentages.",
     ["Find every run of digits.", "Return how many were found."],
     "import re\ndef score(text):\n    return float(len(re.findall(r'\\d+', text)))\n"),
    ("Sentence length variance", "Variance of sentence lengths in words.",
     ["Split into sentences.", "Count words in each.", "Return the variance."],
     "import re\ndef score(text):\n    s = [len(x.split()) for x in re.split(r'[.!?]+', text) if x.strip()]\n    if not s:\n        return 0.0\n    m = sum(s)/len(s)\n    return float(sum((v-m)**2 for v in s)/len(s))\n"),
    ("First person rate", "Share of words that are first-person pronouns.",
     ["Tokenise.", "Count i, me, my, we, our.", "Divide by the word count."],
     "import re\ndef score(text):\n    w = re.findall(r'[a-z]+', text.lower())\n    return float(sum(1 for x in w if x in {'i','me','my','we','our'}))/len(w) if w else 0.0\n"),
    ("Essay length in words", "Total number of words.", ["Split on whitespace.", "Return the count."],
     "def score(text):\n    return float(len(text.split()))\n"),
    ("Hedging words", "Counts hedges such as many, some and maybe.",
     ["Lower-case.", "Count words from a hedge list."],
     "import re\ndef score(text):\n    return float(len(re.findall(r'\\b(many|some|maybe|perhaps|often)\\b', text.lower())))\n"),
    ("Narrative references", "Counts story words like remembered, rain, road.",
     ["Lower-case.", "Count words from a story-word list."],
     "import re\ndef score(text):\n    return float(len(re.findall(r'\\b(remembered|rain|road|dog|funeral|window)\\b', text.lower())))\n"),
    ("Question marks", "Counts question marks.", ["Count the ? characters."],
     "def score(text):\n    return float(text.count('?'))\n"),
]


BASE = ["thesis clarity", "evidence density", "counterargument use", "formal tone", "essay length",
        "vocabulary range", "paragraph structure", "citation count", "opening hook", "closing strength"]
FAMILIES = [10, 6, 2, 8, 3, 5]          # distinct ideas among the 10 readings: more families = softer
_calls = itertools.count()


def fake_readings():
    f = FAMILIES[(next(_calls) // 3) % len(FAMILIES)]
    out = []
    for i in range(10):
        label = BASE[i % f] + (f" variant {i // f + 1}" if i >= f else "")
        out.append({"attribute_label": label, "full_description": f"Score essays by {label}, as one decision procedure."})
    return json.dumps(out)


class FakeLLM:
    def __init__(self):
        self.k = 0

    def __call__(self, system, user, model, temp):
        if "scoring functions" in system:
            chunk = LIB[self.k:self.k + 2]
            self.k += 2
            return json.dumps([{"name": n, "description": d, "steps": s, "code": c} for n, d, s, c in chunk])
        if "consolidated specification" in system:
            return json.dumps({"specification": "The user wants: " + user.split("Message 1")[-1][:140].replace(chr(10), " ")})
        if "READINGS" in system:
            return fake_readings()
        return "Could you say more about what you mean by that?"


def fake_embed(labels):
    """Cheap hashed character-trigram vectors so the 'looks similar to' check does not load MiniLM."""
    import numpy as np
    out = np.zeros((len(labels), 64))
    for i, lab in enumerate(labels):
        s = lab.lower()
        for j in range(len(s) - 2):
            out[i, hash(s[j:j + 3]) % 64] += 1
    return out / (np.linalg.norm(out, axis=1, keepdims=True) + 1e-9)


S.LLM = FakeLLM
S.embed = fake_embed

if __name__ == "__main__":
    import server  # noqa: E402  (imported after patching so the routes see the fakes)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    uvicorn.run(server.app, port=port)
