---
title: "Evaluating a Clinical RAG System Against Records That Actually Exist"
published: false
tags: rag, evaluation, testing, llm
series: "Grounded RAG over FHIR"
---

The first version of my evaluation set had 50 questions and scored beautifully. It also measured nothing, because every question referenced a patient like this:

```json
"patient_ref": "Patient/{diabetic_patient_1}"
```

A placeholder that was never filled in. Retrieval scoped to a patient that does not exist returns nothing, so every question was scored against an empty context, and the scoring logic was lenient enough that this produced numbers instead of errors.

Rebuilding that set against the actual corpus is what turned the harness from decoration into the thing that catches regressions.

## Four metrics, each answering a different question

An end-to-end quality score tells you something is wrong. It does not tell you where. So the harness measures four things separately, and the separation is the entire value.

```python
# eval/evaluate.py
@dataclass
class EvalResult:
    id: str
    category: str
    cohort: str
    question: str
    retrieval_recall: float
    citation_accuracy: float
    answer_contains: float
    confidence: str
    latency_ms: int
```

**Retrieval recall** asks whether the resource types the answer needs were actually retrieved. If a medication question retrieves no `MedicationRequest` resources, nothing downstream can succeed, and no amount of prompt work will help.

**Citation accuracy** asks whether the ids the model cited resolve to resources that were retrieved. It catches fabricated citations, which is a different failure from a fabricated answer.

**Answer-keyword coverage** asks whether the expected content appears in the text. It is the crudest of the four and I discuss its limits below.

**Latency** separates retrieval cost from generation cost. My mean is 14.7 seconds, and knowing that patient-scoped retrieval accounts for 5 to 24 milliseconds of it means I know exactly where optimisation would and would not pay.

Three of these are checkable without an LLM judge, which keeps the harness cheap and deterministic.

## Grounding the questions in a real corpus

The fix for the placeholder problem is not just filling in real ids. It is making the placeholder failure impossible to repeat:

```python
# eval/evaluate.py
# Retrieval is patient-scoped, so an unresolved placeholder would
# silently match nothing and score every question as a miss.
if not question["patient_ref"].startswith("Patient/") or "{" in question["patient_ref"]:
    raise ValueError(f"{question_id} needs a real patient_ref, got {question['patient_ref']!r}")
```

Loud failure at load time, before a single API call. The same validator checks for required fields and duplicate ids.

Each question's expectations then come from the patient's actual records, not from what a diabetes question ought to look like:

```json
{
  "id": "DX-001",
  "question": "What type of diabetes does this patient have, and when was it diagnosed?",
  "patient_ref": "Patient/e7b54eb8-5d9c-5d7a-0003-a39b8c7b3f81",
  "category": "diagnosis",
  "expected_resource_types": ["Condition"],
  "expected_codes": [
    { "system": "SNOMED", "code": "44054006", "display": "Diabetes mellitus type 2" }
  ],
  "expected_answer_contains": ["type 2", "date"],
  "cohort": "diabetes"
}
```

That SNOMED code is in that patient's record. I checked. Writing 52 of these is tedious and it is the single highest-value thing in the evaluation setup, because an expectation that does not match reality either fails permanently (and gets ignored) or passes vacuously (and measures nothing).

## One question, end to end

Abstract metrics are hard to argue with. Here is question `XRS-001` all the way
through, which is the fastest way to see what each number actually measures.

The question, as it sits in `eval/questions.json`:

```json
{
  "id": "XRS-001",
  "question": "Which allergies are documented for this patient, and what reaction did each cause?",
  "patient_ref": "Patient/064e883f-d41c-5fa5-b6f6-664fdbfb9ca8",
  "category": "cross_resource",
  "expected_resource_types": ["AllergyIntolerance"],
  "expected_codes": [{ "system": "SNOMED", "code": "735971005", "display": "Fish" }],
  "expected_answer_contains": ["fish", "wheat", "reaction|dyspnea|eruption"],
  "cohort": "pediatric_atopic"
}
```

The harness embeds it, retrieves scoped to that patient, resolves references,
builds context, generates, and maps citations:

```python
# eval/evaluate.py
embedding = embedder.embed_query(query)
# Scope retrieval to the question's patient. Without this a question about
# one record is answered from all 78 patients in the corpus.
primary = await hybrid_search(
    pool, embedding, query_text=query,
    patient_ref=question["patient_ref"], top_k=settings.top_k,
)
supplementary = await resolve_references(pool, primary, max_hops=settings.max_reference_hops)
resources = primary + supplementary
```

Retrieval returns 25 primary resources, seven of them `AllergyIntolerance`. The
model produces an answer shaped like this:

```
This patient has seven documented allergies. Fish allergy caused dyspnea
and an eruption of skin [AllergyIntolerance/3f1a-...]. Wheat allergy caused
dyspnea [AllergyIntolerance/9c22-...]. ...
```

Now each metric against that.

**Retrieval recall.** Expected types are `{AllergyIntolerance}`, and the
retrieved set contains that type, so the intersection is complete: `1.0`. Note
this is a *type-level* check. It confirms the right kind of record was
retrieved. It does not confirm all seven were.

**Citation accuracy.** Seven citations, all seven resolving, `7/7 = 1.0`:

```python
# eval/evaluate.py
def _citation_accuracy(response: str, resources: list) -> float:
    matches = CITATION_PATTERN.findall(response)
    if not matches:
        return 0.0
    available = {
        (r.resource_type.lower(), r.resource_id.split("/", 1)[-1].lower())
        for r in resources
    }
    valid = sum((t.lower(), i.lower()) in available for t, i in matches)
    return valid / len(matches)
```

**Answer-keyword coverage.** Three expectations. "fish" appears, "wheat"
appears, and `"reaction|dyspnea|eruption"` is a pipe alternative satisfied by
any of the three. Score `3/3 = 1.0`.

**Confidence.** All citations valid, so `grounded`. **Latency**, about 12
seconds, essentially all generation.

The value of walking one through by hand is seeing where the metrics would
*not* have caught a failure. If the model had named three of the seven
allergies, retrieval recall would still be `1.0` (the type was retrieved),
citation accuracy would still be `1.0` (three real ids), and only
`answer_contains` would notice, and only if the missing allergens happened to
be in my expectation list. Set completeness is the weakest axis in this harness,
and it is the axis clinical questions most often depend on.

## The negative case, end to end

`NEG-001` asks the same pediatric patient for an HbA1c:

```json
{
  "id": "NEG-001",
  "question": "What is this patient's most recent HbA1c result?",
  "patient_ref": "Patient/064e883f-d41c-5fa5-b6f6-664fdbfb9ca8",
  "category": "negative",
  "expected_resource_types": [],
  "expected_codes": [],
  "expected_answer_contains": ["insufficient data"],
  "cohort": "pediatric_atopic"
}
```

Retrieval still returns 25 resources, because it is patient-scoped and this
child has 226 observations. They are respiratory rates, head circumferences, and
BMI percentiles. None is a glucose result. The model answers:

```
Insufficient data in the available FHIR resources to answer this question.
```

Which scores: retrieval recall `1.0` by the empty-expectations rule, citation
accuracy excluded from the aggregate, `answer_contains` `1.0`, and confidence
`ungrounded`.

That last one is worth sitting with. The correct answer to a negative question
is classified `ungrounded`, and that is right, because a refusal genuinely has
no evidence behind it. The verdict describes the evidence, not the correctness.
Conflating the two would have forced a choice between marking correct refusals
as grounded, which is meaningless, or marking them as failures, which is worse.

## Two cohorts, on purpose

The project is diabetes-focused, so the obvious move is 52 diabetes questions. That would have told me nothing about whether the system generalises, because a system tuned on one disease can pass by pattern-matching.

So the set covers two deliberately dissimilar cohorts:

| Cohort | Patients | Exercises |
| --- | --- | --- |
| `diabetes` | three adults with type 2 diabetes, retinopathy, nephropathy, cardiac disease, amputation history | HbA1c trends, insulin and metformin, complication chains, retinal screening |
| `pediatric_atopic` | one child with the atopic march and no glucose data at all | allergy reactions, asthma regimen, growth percentiles, immunizations |

The pediatric patient does double duty. He tests entirely different resource types (`AllergyIntolerance`, `Immunization`, growth percentile observations), and because he has no glucose data at all, he supplies honest negative controls. Asking for his HbA1c must return a refusal, not an invented value.

The `by_cohort` breakdown then makes generalisation visible rather than assumed:

```python
# eval/evaluate.py
"by_category": _breakdown(results, lambda r: r.category),
"by_cohort": _breakdown(results, lambda r: r.cohort),
```

## Ten categories, chosen to fail differently

The 52 questions are spread across ten categories, and the split is not
cosmetic. Each category stresses a different part of the pipeline, so a
breakdown by category localises a regression without reading individual rows.

| Category | n | What it stresses |
| --- | --- | --- |
| `medications` | 7 | Set completeness across many similar resources |
| `diagnosis` | 6 | Condition retrieval and status interpretation |
| `hba1c_monitoring` | 6 | Abbreviation expansion, numeric extraction |
| `cross_resource` | 6 | Reference resolution, joining two resource types |
| `complications` | 5 | Multi-condition reasoning over a disease chain |
| `vitals_labs` | 5 | Observation retrieval among 41,837 of them |
| `temporal` | 5 | Date extraction and ordering |
| `negative` | 5 | Refusal behaviour |
| `care_plan` | 4 | CarePlan rendering, activity extraction |
| `preventive` | 3 | Procedure and Immunization retrieval |

The temporal questions are the ones I would write first if starting again,
because they are the cheapest way to catch renderer date bugs:

```json
{
  "id": "TMP-001",
  "question": "Trace the atopic march for this patient: order eczema, food allergy, allergic rhinitis and asthma by onset date.",
  "expected_resource_types": ["Condition", "AllergyIntolerance"],
  "expected_answer_contains": ["chronological events with dates"],
  "cohort": "pediatric_atopic"
}
```

`"chronological events with dates"` is shorthand, expanded by the matcher into
"at least two ISO dates appear in the answer". Writing expectations as shorthand
rather than as literal strings is what makes a set of 52 maintainable, and it is
also where the harness grew its own bugs.

## Negative questions need different scoring, not zero scores

This is where naive metrics actively mislead, and it took two separate fixes.

A negative question lists no expected resource types, because the record has none. But retrieval is patient-scoped, so it still returns that patient's other resources. Recall is not a meaningful signal:

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
    found = {resource.resource_type for resource in resources}
    return len(expected & found) / len(expected)
```

Worse, a correct refusal cites nothing, so citation accuracy would score it 0.0:

```python
# eval/evaluate.py
# A correct negative answer cites nothing, so scoring it 0.0 would punish
# the behaviour the negative questions exist to confirm.
citable = [r for r in results if r.category != "negative"]
```

Without that exclusion, the metric rewards a system that guesses over one that refuses. **A metric that punishes the behaviour you are trying to produce is worse than having no metric**, because you will optimise against it without noticing.

## Keyword matching, and being honest about it

`answer_contains` is the weakest metric and I want to be direct about why I kept it.

Expectations are literal phrases with pipe alternatives, plus a set of shorthand patterns:

```python
# eval/evaluate.py
def _matches_expectation(answer: str, expectation: str) -> bool:
    """Match literal phrases plus the compact alternatives used in questions.json."""
    answer_lower = answer.lower()
    alternatives = [part.strip() for part in expectation.split("|") if part.strip()]
    if any(part.lower() in answer_lower for part in alternatives):
        return True
    if expectation == "duration or date":
        return bool(re.search(_DATE + r"|\b\d+\s+(?:year|month|day)s?\b", answer_lower))
    if expectation == "date" or expectation.endswith("date"):
        return bool(re.search(_DATE, answer))
    ...
```

It is a proxy. An answer can contain "type 2" and a date and still be wrong. It cannot distinguish a correct answer from a plausible one that happens to use the right vocabulary.

What it is good for is regressions. When a change drops keyword coverage in the `medications` category from 0.95 to 0.79, something specific broke, and I can go find it. That is worth a lot, and it costs no API calls beyond the ones already being made.

One bug in this code is worth flagging because it is the kind that silently zeroes a whole metric:

```python
# Rendered resources carry full ISO timestamps ("2025-04-06T12:39:43+07:00"),
# so a trailing \b after the day fails against the "T" and every date-shaped
# expectation scored zero.
_DATE = r"\b\d{4}-\d{2}-\d{2}"
```

A trailing word boundary after the day. `\b` between `6` and `T` does not match, because both are word characters. Every date expectation across the whole set scored zero, and the aggregate just looked like the system was weak on dates.

**Test your test harness.** `tests/test_evaluate.py` exists for exactly this
reason, and its cases are the bugs I actually hit rather than hypothetical ones:

```python
# tests/test_evaluate.py
def test_date_expectation_matches_a_full_iso_timestamp():
    # Rendered resources carry "2025-04-06T12:39:43+07:00"; a trailing word
    # boundary after the day fails against the "T" and scored every temporal
    # question zero.
    assert _matches_expectation("Onset 2025-04-06T12:39:43+07:00.", "date")


def test_chronological_expectation_needs_two_timestamps():
    one = "Diagnosed 2020-11-06T12:39:43+07:00."
    two = one + " Then 2025-02-01T12:39:43+07:00."
    assert not _matches_expectation(one, "chronological events with dates")
    assert _matches_expectation(two, "chronological events with dates")
```

The second one is a guard against the opposite failure: an expectation that is
too easy to satisfy. "Chronological events with dates" should not pass on an
answer containing one date, because ordering requires at least two, and a
matcher that accepts one would quietly mark every temporal question correct.

There is also a test that the dataset itself is still grounded, which runs with
the ordinary unit tests rather than only when the full evaluation is run:

```python
# tests/test_evaluate.py
def test_dataset_questions_reference_real_patients():
    for question in load_questions():
        assert question["patient_ref"].startswith("Patient/")
        assert "{" not in question["patient_ref"]
        assert question["cohort"] in {"diabetes", "pediatric_atopic"}
```

That is the placeholder bug from the opening, converted into something that
cannot come back.

## Reading a report

The baseline, on 78 patients with `TOP_K=25` and `gemini-2.5-flash`:

| Metric | Score |
| --- | --- |
| Retrieval recall | 0.971 |
| Citation accuracy | 0.957 |
| Answer-keyword coverage | 0.952 |
| Grounded / partial / ungrounded | 45 / 0 / 7 |
| Latency (mean / max) | 14.7 s / 27.3 s |

The aggregate is not the interesting part. The breakdown is.

`medications` sits at 0.79 keyword coverage because a simvastatin prescription was not retrieved. `preventive` sits at 0.67 across only three questions, so it is noisy but worth watching. `cross_resource` recall of 0.83 reflects questions expecting two resource types where only one was retrieved, which points at retrieval rather than generation.

Zero partially grounded results is the number I am happiest about, because that state is the dangerous one: an answer mixing verified and unverified claims with no way to tell them apart in the prose.

Of the seven ungrounded, five are the negative controls behaving correctly and two are answers that wrote resource ids without brackets. None is a retrieval failure. Knowing that required looking at all seven individually, which is the actual work.

## What I would add

An **LLM judge** for semantic correctness, to catch what keyword matching cannot. I would run it alongside the cheap metrics rather than replacing them, because deterministic metrics that run in seconds have a different job from a judge that costs money and varies between runs.

**Retrieval-only evaluation** that skips generation entirely. Most of my defects were retrieval defects, and 14.7 seconds per question is almost all generation. A retrieval-only pass over the same 52 questions would run in under a second and catch the majority of regressions.

**Rank-aware recall.** Right now recall asks whether the expected type appeared anywhere in the top 25. Whether it was rank 1 or rank 24 matters, and I do not measure it.

## The takeaway

Build the harness before you tune, and ground it in your actual data. An evaluation set written from what questions *ought* to look like is a fiction that produces numbers, and numbers are more dangerous than no measurement at all, because they feel like evidence.

Then check the metric definitions against the behaviour you actually want. Mine would have penalised correct refusals, which is the one behaviour the whole system exists to produce.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
