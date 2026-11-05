"""Phase 3 live check: dialogue -> Function Agent -> sandbox-validated functions."""
import function_agent as F
import registry as R
import sandbox
import softness as S

QA = ("Q: What makes an argumentative essay good in your view?\n"
      "A: I like essays that back up each claim with evidence, like statistics or concrete examples.\n"
      "Q: Do you mean numbers specifically, or any kind of supporting example?\n"
      "A: Either is fine, but I want to see it, not just the word 'evidence'.")

llm = S.LLM()
reg = R.Registry()
funcs, failures = F.generate_functions(QA, reg, llm)
print("allowed imports:", sandbox.ALLOWED_IMPORTS)
for f in funcs:
    print(f"\n[{f.id}] {f.name}\n  {f.description}\n  sample values: {f.sample_values}\n{f.code}")
print("\nfailures:", failures)
reg.save("phase3_registry.json")
