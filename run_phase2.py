"""Phase 2 live check: opening -> clarify -> open-ended -> suggest. Needs API env vars."""
import question_agent as Q
import softness as S

llm = S.LLM()
h = Q.History()
h.add("open_ended", Q.opening("argumentative"))
h.answer_last("I like essays where the author makes an original point nobody else would think of.")
print("OPENING :", h.turns[0].question)
print("\nCLARIFY :", Q.clarify(h, llm, function_titles=["novel thesis uniqueness"]))
print("\nOPEN    :", Q.open_ended(h, llm, cluster_essays=[
    (12, 0, "Schools should start later because teenagers sleep less..."),
    (47, 0, "Social media harms attention spans, studies show...")]))
print("\nSUGGEST :", Q.suggest())
