---
title: "Insufficient Data Is a Feature: Designing Refusal Into a Clinical RAG System"
published: false
tags: rag, llm, healthcare, ai
series: "Grounded RAG over FHIR"
---

Ask my system for a six-year-old's most recent HbA1c and it says:

> Insufficient data in the available FHIR resources to answer this question.

That patient has 226 observations in the index. None of them is a glucose result, because he is a child with atopic dermatitis and asthma, and nobody has ever ordered one. The refusal is the correct answer, and it took more engineering than any of the answers did.

## Why a plausible number is the worst output

Consider what a fabricated response looks like:

> The patient's most recent HbA1c was 5.4% on 2025-03-14, within the normal range.

Nothing in that sentence is marked as invented. It has a value, a date, and an interpretation. It reads exactly like the true answers the system produces for patients who do have glucose results. A reader has no way to tell the difference without going back to the source record, which is precisely the work the system exists to save.

That asymmetry is what makes clinical RAG different from most RAG. A wrong answer about a refund policy costs an email. A wrong answer that reads like a lab value enters someone's understanding of a patient.

So the design target was never "answer more questions". It was: make every claim checkable, and make the system decline when it cannot make one.

## The prompt is a contract

The prompt states the rules explicitly, including the exact refusal string:

```
You are a clinical data assistant. Answer questions using ONLY the FHIR
resources provided below.

Rules:
1. Base your answer exclusively on the provided FHIR context.
2. Cite specific resource IDs using [ResourceType/id] format
   (e.g., [MedicationRequest/abc-456]).
3. If the provided context does not contain enough information to answer, say:
   "Insufficient data in the available FHIR resources to answer this question."
4. Never fabricate clinical information, medications, diagnoses, or dates.
5. When multiple resources are relevant, synthesize them into a coherent answer.
6. Include relevant dates and coded values when available.
```

Two deliberate choices here.

The citation format is machine-parseable. `[ResourceType/id]` is not a stylistic preference, it is a format I can regex out of the response and check. A prompt asking for "citations" in prose would produce something a human can follow and a program cannot verify.

The refusal string is specified verbatim rather than left to the model. That makes refusals detectable programmatically and consistent across providers, and it removes the failure mode where a model hedges into a soft non-answer ("the record does not appear to clearly indicate") that is neither an answer nor a clean refusal.

## Asking is not getting

A prompt is a request. The model can ignore it, and more interestingly, it can *comply in form while failing in substance*: emit a well-formatted citation pointing at a resource id that was never retrieved.

So every citation gets checked:

```python
# src/generation/citation_mapper.py
CITATION_PATTERN = re.compile(r"\[([A-Za-z][A-Za-z0-9]*)/([^\]\s]+)\]")

def map_citations(llm_response, query, available_resources):
    matches = CITATION_PATTERN.findall(llm_response)
    resources = {
        (r.resource_type.lower(), r.resource_id.split("/", 1)[-1].lower()): r
        for r in available_resources
    }
    citations, seen_ids, valid_count = [], set(), 0
    for resource_type, resource_id in matches:
        resource = resources.get((resource_type.lower(), resource_id.lower()))
        if resource is None:
            continue
        valid_count += 1
        ...
```

The lookup key is `(type, id)` lowercased, so a model that writes `[observation/ABC]` instead of `[Observation/abc]` is still matched. Case pedantry would produce false negatives and tell me nothing useful.

A cited id that is not in `available_resources` does not become a citation. It is not silently dropped either. It counts against the grounding verdict.

## Three states, not two

```python
# src/generation/citation_mapper.py
if not matches or valid_count == 0:
    confidence = "ungrounded"
elif valid_count == len(matches):
    confidence = "grounded"
else:
    confidence = "partially_grounded"
```

**Grounded** means every citation resolves to a retrieved resource. **Partially grounded** means some resolved and some did not, which is the state that should worry you most: the answer is mixing verified claims with unverified ones, and the prose gives no indication which is which. **Ungrounded** means no valid citations at all.

A correct refusal lands in `ungrounded`, which is initially counterintuitive. It is right, though. Both a refusal and a fabrication are answers with no evidence behind them, and the distinction between them is semantic, not structural. The verdict describes the evidence, and the user reads the text.

The three states go out through the API and reach the interface:

```javascript
// src/frontend/app.js
get confidenceLabel() {
  return {
    grounded: "Grounded",
    partially_grounded: "Partially grounded",
    ungrounded: "Ungrounded",
  }[this.confidence] || "Evidence status unknown";
}
```

Surfacing that is a product decision as much as a technical one. It is tempting to hide it, because "partially grounded" looks like an admission of weakness. Hiding it means the interface presents verified and unverified answers identically, which is the exact failure the system was built to prevent.

## Negative controls belong in the evaluation set

If refusal is a feature, it needs to be tested like one. Five of my 52 evaluation questions are negative controls: questions whose correct answer is a refusal.

They ask the pediatric patient for an HbA1c, for spirometry results, for a hospitalization history. The record has none of those. A system that answers them is broken in a way no amount of good performance elsewhere compensates for.

Scoring them needed two special rules, and both are the kind of thing that is obvious in hindsight and easy to get wrong.

```python
# eval/evaluate.py
def _retrieval_recall(question, resources) -> float:
    expected = set(question["expected_resource_types"])
    if not expected:
        # Negative questions name no expected types: the record genuinely has
        # no such data. Patient-scoped retrieval still returns that patient's
        # other resources, so recall is not a meaningful signal here and these
        # questions are scored on answer_contains instead.
        return 1.0
```

And citation accuracy excludes them entirely:

```python
# eval/evaluate.py
# A correct negative answer cites nothing, so scoring it 0.0 would punish
# the behaviour the negative questions exist to confirm.
citable = [r for r in results if r.category != "negative"]
```

Without that second rule, every correct refusal drags citation accuracy down, and the metric rewards a system that guesses. A metric that punishes the behaviour you are trying to produce is worse than no metric.

## Where the design is still weak

Two honest gaps.

Grounding verifies that a cited resource *was retrieved*. It does not verify that the resource *supports the claim*. A model could cite a real HbA1c observation while misstating its value, and the citation mapper would report `grounded`. Catching that needs claim-level entailment checking against the resource text, which I have not built.

And two of my seven ungrounded evaluation results are false alarms: correct, well-supported answers where the model wrote resource ids without brackets. The verification is strict about format, so a formatting slip presents identically to a fabrication. A more forgiving parser would fix the false alarms and weaken the check. I would rather have the false alarms, but it is a real cost and I do not think it is obviously the right call.

## The takeaway

If you are putting an LLM in front of data where being wrong is expensive, build the verification layer before you tune the prompt. The prompt asks for good behaviour; only verification tells you whether you got it.

And put the verdict in front of the user. A system that says "I checked this and it holds up" is more useful than a system that is right slightly more often and never tells you which times.

The next article in this series is about a case where the grounding verdict was correct and the diagnosis was still wrong: answers that came back truncated mid-citation and got scored as ungrounded, because the model had spent its entire output budget thinking.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
