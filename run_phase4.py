"""Phase 4 scripted live run: scripted user answers, auto-accept cards, print the policy trace."""
import registry as R
import session as SE
import softness as S

ANSWERS = [
    "I like essays that are original.",                              # vague -> clarify
    "I mean the thesis should be one no other essay in the set makes",
    "Actually just: the essay has at least three cited statistics",  # precise -> generate
    "no",                                                            # decline suggestion
]

llm = S.LLM()
sess = SE.Session(llm, R.Registry(), log=SE.EventLog("phase4_log.jsonl"))
q = sess.start()
for a in ANSWERS:
    print(f"\nQ [{sess.history.turns[-1].qtype}]: {q}\nA: {a}")
    if sess.history.turns[-1].qtype == "suggest" and a.strip().lower() in {"no", "skip"}:
        sess.history.answer_last(a)
        sess.awaiting_answer = False
        q = sess.new_topic()
        continue
    r = sess.submit_answer(a)
    print(f"   softness={r['score']} -> {r['action']}")
    for f in r["new_functions"]:
        print(f"   card: {f.name} | values {f.sample_values}")
        sess.review(f.id, "accept")
    q = sess.next_question()
print(f"\nFinal Q [{sess.history.turns[-1].qtype}]: {q}")
