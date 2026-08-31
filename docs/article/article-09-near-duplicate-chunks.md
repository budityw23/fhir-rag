---
title: "Synthetic Data Lies: When 12 Identical Conditions Ate Every Retrieval Slot"
published: false
tags: rag, retrieval, synthea, debugging
series: "Grounded RAG over FHIR"
---

I asked the system what a patient's active problems were. It answered:

> This patient has one active problem: Medication review due [Condition/8a3f-...].

The patient is a six-year-old with atopic dermatitis, perennial allergic rhinitis, and childhood asthma. All three are in the database, all three are `Condition` resources, all three have `clinicalStatus: active`.

The answer was not a hallucination. It was an accurate description of what the model had been given.

## The histogram that found it in one line

The instinct when an answer under-reports is to look at the prompt. Maybe the model needs to be told to be exhaustive. Maybe the instruction to synthesise is being read as an instruction to summarise.

Before touching any of that, I looked at what was actually retrieved. Not the answer, the input:

```python
from collections import Counter
Counter(r.resource_type for r in primary)
# Counter({'Condition': 12, 'Observation': 7, 'Encounter': 4, 'CarePlan': 2})
```

Twelve `Condition` resources out of twenty-five retrieved. So conditions were not being crowded out by other types. The problem was inside the conditions.

```python
Counter(r.text_content.split("\n")[0] for r in primary if r.resource_type == "Condition")
# Counter({'Condition: Medication review due (situation) (SNOMED: 314529007).': 12})
```

All twelve were the same resource, twelve times over, with different ids.

## What Synthea does

Synthea emits one `Medication review due` Condition per visit. It is an administrative flag, not a clinical problem, and a patient with sixty encounters has sixty of them. They are `active`. They are `Condition` resources. Structurally they are indistinguishable from a diabetes diagnosis.

And critically, their rendered text is near-identical:

```
Condition: Medication review due (situation) (SNOMED: 314529007).
Status: active.
Onset: 2024-03-11T09:00:00+07:00.
Patient: Patient/8f2c-...
```

The only thing that varies is the date. Embed sixty of those and you get sixty vectors clustered so tightly they are effectively one point in the space, occupying a dense region near the concept of "an active condition".

A query like "what are this patient's active problems?" lands right on top of that cluster. Every nearest neighbour is a member of it. Top-k retrieval, working perfectly, returns twelve copies of the same thing.

## The assumption that broke

Top-k similarity retrieval carries an implicit assumption that nobody states: that the candidates are both **informative** and **distinct**. Rank by relevance, take the top k, and you get the k most relevant things.

That only holds when relevance is spread across distinct items. When a corpus contains large clusters of near-identical documents, "most relevant" and "most useful" come apart, and top-k optimises the wrong one. The twelve retrieved conditions have a combined information content of one condition, but they consume twelve slots.

Real clinical data has this problem too, just less obviously. A patient on a stable medication has a `MedicationRequest` per refill. Vitals are recorded at every visit. Any longitudinal record accumulates near-duplicates by construction.

Synthetic data makes it worse because generators produce structurally repetitive output. But it did not invent the problem, it just made it impossible to ignore.

## Why prompting cannot fix it

My first attempt was to tell the model to disregard administrative entries and report clinical conditions. It did not work, and it could not have.

Exclusion happens at generation time. Retrieval has already run. The three real conditions were never in the context window, so the model had nothing to promote once it demoted the administrative ones. The best a prompt fix can do is turn a wrong answer into a refusal.

This is a general rule with a sharp edge: **the prompt cannot recover information that retrieval discarded.** When an answer is missing facts, the question is always whether those facts were retrieved. If they were not, every minute spent on the prompt is wasted.

## The workaround, and why it is not a fix

Naming the conditions in the question works, because retrieval is driven by the query text:

```
"What chronic conditions does he have (asthma, eczema, allergic rhinitis),
 and when was each diagnosed?"
   -> grounded, 3 citations, all correct
```

Which is useful and completely unsatisfying. It requires the user to already know the answer.

I did put that insight to work in one place. The system generates per-patient example questions, and rather than offering a generic "what are the active problems?", it reads the patient's actual conditions and names them:

```python
# src/api/suggestions.py
# Naming the conditions explicitly is deliberate. A generic "active
# problems" question is answered from the retrieved chunks, and repeated
# administrative Conditions can occupy every slot; naming them retrieves
# the clinical rows instead.
if names:
    listed = ", ".join(names[:3])
    suggestions.append(
        f"What is the history of {listed} for this patient, and when was each diagnosed?"
    )
```

With a filter that drops the administrative ones from the list it builds from:

```python
ADMINISTRATIVE_CONDITIONS = ("medication review due",)
```

That is treating the symptom at the interface layer. It helps the user who clicks a suggestion, and does nothing for the user who types their own question.

## What actually resolved it, and why that was luck

The generic question answers correctly now. Not because I fixed the duplication, but because I fixed an unrelated bug in the lexical retrieval arm.

My hybrid search had a full-text arm that was returning zero rows for every question, which I wrote about earlier in this series. Once it worked, "active problems" matched the clinical conditions on term overlap ("asthma", "dermatitis", "rhinitis" appear in their text), and those rows entered the fused ranking through a path that does not care about vector clustering.

Two retrieval arms with different failure modes gave me diversity as a side effect. That is a real benefit of hybrid search worth naming. It is also not a defence I designed, and I do not trust it: a corpus whose duplicates share the query's vocabulary would defeat both arms at once.

## The fix I have not shipped

The robust answer is diversity-aware retrieval, and there are two forms of it.

**Maximal Marginal Relevance** re-ranks candidates by relevance minus similarity to what is already selected. Over-fetch, then greedily pick items that are relevant *and* different from the current set. It is well understood and it directly targets this failure.

**Collapsing by key** is cruder and, for FHIR specifically, might be better. Every chunk already stores its terminology codes, so candidates can be grouped by `(resource_type, code)` and reduced to one representative per group (most recent, say, with a count) before top-k applies:

```
Condition: Medication review due (SNOMED: 314529007). 12 occurrences, most recent 2025-11-03.
```

One slot instead of twelve, and the model gets the frequency information too, which is clinically meaningful in a way that twelve separate rows are not.

I have not implemented either. It is the largest known gap in the system and it is sitting in the README under limitations, because a system description that lists only what works is not worth much.

## The check worth stealing

Whenever an aggregation question under-reports, look at the resource-type histogram of the retrieved set before looking at anything else. Then look at the histogram of the *content* within the dominant type.

Two `Counter` calls. They separate "retrieval did not find it" from "retrieval found twelve copies of something else" from "the model failed to use what it had", and those three problems have nothing in common except the symptom.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
