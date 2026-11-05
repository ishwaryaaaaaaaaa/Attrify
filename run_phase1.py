"""Phase 1 live check: softness of obvious cases + a converging and a reversal dialogue.

Usage (from attrify/):  python run_phase1.py [--runs 3]
Needs OPENAI_API_KEY (and optionally ATTRIFY_BASE_URL / ATTRIFY_*_MODEL).
Writes results to phase1_results.json.
"""
import argparse
import json

import softness as S

DESCRIPTIONS = [
    # expected low softness
    "the essay uses correct verb forms",
    "the essay has an introduction, a body and a conclusion",
    "the essay is at least 500 words long",
    # expected high softness
    "the argument is convincing",
    "the essay is original",
    "the essay is interesting",
]

DIALOGUES = {
    "converging": [
        "I care about originality",
        "I mean ideas I haven't seen in other essays, not style",
        "Specifically, a thesis that no other essay in the corpus makes",
    ],
    "reversal": [
        "The essay must contain at least three citations",
        "Scratch that, I just want it to feel well-supported",
    ],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    llm = S.LLM()
    out = {"descriptions": [], "dialogues": {}}

    print("== single descriptions ==")
    for d in DESCRIPTIONS:
        r = S.softness([d], llm, runs=a.runs)
        print(f"{r['score']:>3} {r['run_scores']}  {S.policy(r['score']):<22} {d}")
        out["descriptions"].append({"text": d, **r})

    print("\n== dialogues (score after each user turn) ==")
    for name, msgs in DIALOGUES.items():
        rows = []
        for i in range(1, len(msgs) + 1):
            r = S.softness(msgs[:i], llm, runs=a.runs)
            print(f"{name:<11} turn {i}: {r['score']:>3}  spec: {r['specification']}")
            rows.append({"turn": i, **r})
        out["dialogues"][name] = rows

    with open("phase1_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
