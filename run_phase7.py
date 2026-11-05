"""Phase 7 live check: baseline reacts to a vague answer by generating functions every turn."""
import attribute_table as AT
import baseline as B
import corpus as C
import registry as R
import softness as S

sess = B.BaselineSession(S.LLM(), R.Registry(), table=AT.AttributeTable(C.demo_corpus(60)))
print("ASSISTANT:", sess.start())
a = "I like essays that feel original."
print("USER     :", a)
r = sess.submit_answer(a)
print(f"-> action={r['action']} cards={[f.name for f in r['new_functions']]} failures={r['failures']}")
for f in r["new_functions"]:
    print("   ", f.name, "| samples:", [round(v, 1) for v in f.sample_values], "| warnings:", f.warnings)
    sess.review(f.id, "accept")
print("ASSISTANT:", sess.next_question())
