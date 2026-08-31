---
title: "What Software Engineers Get Wrong About Clinical Data"
published: false
tags: healthcare, fhir, data, ai
series: "Grounded RAG over FHIR"
---

An engineer joining a healthcare project asks a reasonable question early on: "so where is the table of the patient's current diagnoses?"

There is no such table. There is a history of assertions that people made at particular moments, each with its own status, its own author, and its own degree of certainty, and "current diagnoses" is a view you compute from those assertions with rules that are themselves clinical judgments.

That gap between what engineers expect and what clinical data is causes more failed healthcare software than any technical problem. Here is the version I wish someone had given me, informed by eight years around clinical systems and by building a RAG pipeline on top of them.

## A record is a history of assertions, not a current state

The instinct from application development is that a database holds the current state of the world. A user row is what the user is now. Updates overwrite.

Clinical records do not work that way. A record is an accumulating log of things that were observed, asserted, ordered, or done, each anchored in time. Nothing is overwritten, because the fact that someone believed something on a particular date is itself clinically and legally significant.

So a patient does not "have" hypertension in the sense that a row says so. There is a `Condition` resource asserting hypertension, recorded on a date, by someone, with a status. There may be another one asserting it was resolved. There may be two, entered at different visits, that mean the same thing.

### What that looks like in one patient

Take one of the patients in my corpus. A query for their conditions returns
rows like this, and the shape of the result is the lesson:

```
Condition: Prediabetes (SNOMED: 714628002).          Onset: 2013-04-02.  active
Condition: Diabetes mellitus type 2 (SNOMED: 44054006). Onset: 2016-09-18. active
Condition: Diabetic retinopathy (SNOMED: 4855003).   Onset: 2021-01-11.  active
Condition: Medication review due (SNOMED: 314529007). Onset: 2021-01-11. active
Condition: Medication review due (SNOMED: 314529007). Onset: 2021-07-14. active
```

An engineer looking for "the current diagnoses" wants the first three and not
the last two. But nothing in the data marks that distinction. All five are
`Condition`, all five are `active`, and the last two outnumber the first three
by a factor of ten across the full record.

More importantly, prediabetes is still listed as active alongside type 2
diabetes, which is clinically incoherent as a current-state description and
completely correct as a record of assertions. Somebody asserted prediabetes in
2013. Nobody ever went back to resolve it. That is normal, and any code that
treats the problem list as current state will report a patient who has both
prediabetes and diabetes simultaneously.

This is why my chunking keeps one resource per chunk with its date attached,
and why citations name a specific resource rather than a summarised conclusion.
The resource is the assertion. Aggregating away from it loses the provenance
that makes the data trustworthy, and it invents a current state that the record
never claimed.

## Two status fields, and both matter

The clearest concrete example. FHIR's `Condition` has both `clinicalStatus` and `verificationStatus`, and engineers routinely use one and ignore the other.

`clinicalStatus` is about the condition: active, recurrence, remission, resolved.

`verificationStatus` is about the assertion: unconfirmed, provisional, differential, confirmed, refuted, entered-in-error.

They are orthogonal, and the combinations are meaningful. A condition can be clinically active and merely provisional, which is a working hypothesis that has not been confirmed. It can be confirmed and resolved. And `entered-in-error` means someone recorded it by mistake and it should be treated as never having existed, which is a state most data models have no concept of at all.

Filter on `clinicalStatus = 'active'` alone and you will include provisional diagnoses and refuted ones as though they were established fact.

My renderer keeps both in the text so the model can see them:

```python
# src/ingestion/text_renderer.py
def _status(resource: dict, *fields: str) -> str | None:
    for field in fields:
        value = resource.get(field)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            codings = value.get("coding", [])
            if isinstance(codings, list) and codings:
                coding = codings[0]
                if isinstance(coding, dict):
                    return str(coding.get("display") or coding.get("code") or "") or None
    return None
```

Called as `_status(resource, "clinicalStatus", "verificationStatus")`. I am honest that this takes the first available rather than rendering both, which is a simplification I would revisit for anything beyond a demo. It is exactly the kind of shortcut that seems harmless and quietly discards a distinction clinicians rely on.

## Missing is not negative

The one that causes real harm.

In most datasets, absence means the thing did not happen. In clinical records, absence means it was not *recorded*, and there are many reasons for that besides absence.

The test was not ordered. It was ordered elsewhere and the result never made it into this system. It was documented in a scanned PDF nobody parsed. The patient was seen at another institution entirely. Someone forgot.

So "there is no diabetes diagnosis in this record" does not mean "this patient does not have diabetes". It means this record does not say so. Any system that reports the first as the second is producing a clinical claim it has no basis for.

This is a large part of why my system refuses rather than negates:

```
3. If the provided context does not contain enough information to answer, say:
   "Insufficient data in the available FHIR resources to answer this question."
```

Note the wording. Not "the patient does not have X". Not "no results found". Insufficient data *in the available resources*. The scope of the claim is the record, not the patient, and keeping those separate is the difference between an honest system and a dangerous one.

### The worked version

My evaluation set contains a question that exists purely to test this. `NEG-001`
asks a six-year-old for his most recent HbA1c. He has 226 observations in the
index. None of them is a glucose result, because nobody has ever had a reason to
order one.

Retrieval, being patient-scoped, still returns 25 resources. They are
respiratory rates, head circumferences, and BMI percentiles. The model sees a
full context window of real clinical data, none of which answers the question,
and produces:

```
Insufficient data in the available FHIR resources to answer this question.
```

Compare that to the three answers it could have given instead. "This patient
does not have diabetes" is a clinical claim the record cannot support. "No
results found" is a database status message dressed as a clinical statement. A
fabricated value of 5.4% is the catastrophic case.

Only the actual answer scopes its claim correctly: it says something about the
resources, not about the child. That distinction is one line of prompt and it is
the difference between a tool that assists someone reading a chart and a tool
that makes assertions it has no standing to make.

There is a related trap in evaluation. My negative-control questions ask a pediatric patient for an HbA1c, and the correct answer is a refusal. Scoring that as a failure would have trained me toward a system that guesses:

```python
# eval/evaluate.py
# A correct negative answer cites nothing, so scoring it 0.0 would punish
# the behaviour the negative questions exist to confirm.
citable = [r for r in results if r.category != "negative"]
```

## Coded does not mean comparable

Engineers see terminology codes and reasonably conclude the interoperability problem is solved. SNOMED CT for conditions, LOINC for labs, RxNorm for medications, all standard, all globally unique.

The codes are excellent. The practice around them is messier than the standard suggests.

Multiple codes describe the same clinical concept at different levels of specificity, and different institutions choose differently. The same lab test can have different LOINC codes depending on specimen type and method, which is correct and precise and also means naive equality matching misses records that a clinician would consider equivalent.

Many systems carry local codes alongside standard ones, so a resource may have three codings in its array where only one is a terminology you recognise. And the `display` string is a convenience field, not an identifier: it can be absent, localised, or simply wrong relative to the code it accompanies.

I extract every coding I find rather than assuming a canonical one:

```python
# src/ingestion/chunker.py
def extract_codes(resource_json: dict) -> list[dict]:
    """Extract all coded values (SNOMED, LOINC, RxNorm) from a resource."""
```

And I embed the display text alongside the code, so retrieval can match either. Neither alone is sufficient.

The related trap is abbreviations. Clinicians write "HbA1c". The record says "Hemoglobin A1c". Those share no tokens, so a lexical match fails and an embedding match is weaker than you would hope:

```python
# src/ingestion/embedder.py
_QUERY_EXPANSIONS = {
    "hba1c": "hemoglobin a1c",
    "hb a1c": "hemoglobin a1c",
}
```

Crude, and effective for the highest-value cases. Clinical vocabulary has a long tail of these, and no amount of embedding quality substitutes for knowing that the abbreviation and the formal name are the same thing.

## Time is not a timestamp

There are at least four dates attached to any clinical event: when it happened, when it was recorded, when it was reported, and when the record was last modified. They can differ by days.

FHIR reflects that with different field names per resource type: `effectiveDateTime` on observations, `onsetDateTime` on conditions, `recordedDate` on allergies, `authoredOn` on medication requests. That is not inconsistency, it is precision about which of the four you are getting.

Onset in particular is often approximate or absent. A patient reports having had asthma "since childhood". A condition is recorded at the visit where it was noticed, not when it began. Treating `onsetDateTime` as the date the disease started is a category error, and it makes temporal reasoning ("what came first") much less reliable than it looks.

My date extraction resolves these by priority rather than by type, which is a
pragmatic choice with a cost worth naming:

```python
# src/ingestion/chunker.py
candidates = [
    resource_json.get("effectiveDateTime"),
    resource_json.get("onsetDateTime"),
    resource_json.get("recordedDate"),
    resource_json.get("authoredOn"),
    (resource_json.get("period") or {}).get("start") ...
]
```

The fields are mutually exclusive in practice, so in effect this asks "whichever
one this resource type uses". What it flattens is the semantic difference
between them. A `Condition` dated by `onsetDateTime` and one dated by
`recordedDate` end up in the same column, and a question like "in what order did
these conditions appear?" is silently mixing two different kinds of date.

For my evaluation set that is acceptable, because Synthea populates onset
consistently. On real data it would not be, and the honest fix is to store which
field the date came from alongside the date itself. I have not done it, and it
is the change I would make first if this touched real records.

## One patient is not one identifier

The last one, and it is the one that scales worst.

In application code, a user has an id. In healthcare, a person accumulates
identifiers: one per institution, plus a national identifier where one exists,
plus historical ones from systems that were replaced. FHIR models this honestly
with `Patient.identifier` as an array, and with a whole `Patient.link` mechanism
for saying that two records refer to the same person.

Which means the deduplication problem is not an edge case, it is the normal
state of affairs. A patient seen at two hospitals has two records, neither of
which is wrong, and merging them is a decision with clinical and legal weight
that a matching algorithm makes probabilistically.

My system dodges this entirely. Synthea generates one record per person, so
`patient_ref` is a clean key and patient scoping is an equality filter:

```python
# src/ingestion/fhir_parser.py
if resource_type == "Patient":
    return _resource_id(resource, resource_type)
```

That is fine for synthetic data and it is the single largest gap between my
pipeline and one that could run on real records. Patient scoping is my highest
value retrieval filter, and on real data "this patient" is not a filter, it is a
resolved identity that somebody had to compute first. Any RAG system over
clinical records inherits whatever the enterprise master patient index decided,
including its false merges.

## Synthetic data is safe, and it is not real

[Synthea](https://synthetichealth.github.io/synthea/) is the right way to develop against FHIR without patient data. It models disease progression, produces realistic resource distributions, and carries no privacy risk.

It is also not real, in specific ways that will shape your system if you do not know them.

It emits administrative records with clinical resource types, most notably one `Medication review due` Condition per visit. At one point twelve of those occupied every Condition slot in a top-25 retrieval and the answer to "what are the active problems?" came back as a single administrative entry.

It records social determinants ("Unemployed", "Limited social contact") as active Conditions, coded as findings rather than disorders. They are legitimate, and they are often the most recent conditions, which means ordering a problem list by date buries the diagnoses.

Its clinical coverage is uneven. No continuous glucose monitor history. No insulin pump model. Ask for those and you get a refusal, correctly, but the gap is in the generator and not in the world.

And most importantly: **it has no messiness**. No duplicate patients, no free-text notes with the real answer buried in them, no conflicting records from two systems, no misspellings, no missing consent. Real clinical data has all of that, and a pipeline validated only on Synthea has not been tested against the hardest part of the problem.

## What this means with an LLM on top

Put these together and the implications are specific.

The model must not be the only thing standing between retrieved data and a clinical claim, because the model will fluently produce a claim the data does not support. Verification has to be structural: parse citations, check them against what was actually retrieved, and report the result.

The system must be able to say it does not know, and the surrounding measurement must reward that rather than punish it.

Provenance has to survive the whole pipeline. Every claim should trace to a resource id, because "the system said so" is not an acceptable answer to "how do you know" in a clinical setting.

And the scope of every claim should be the record, not the patient. That distinction is the difference between a tool that assists someone reading a chart and a tool that quietly makes clinical assertions it has no standing to make.

## The takeaway

The recurring error is treating clinical data as a database of facts about a patient. It is a record of what particular people asserted at particular times, with varying confidence, in a system that captured some things and not others.

Engineers who internalise that build systems that are appropriately humble. Engineers who do not build systems that are confidently wrong, which in this domain is the only failure mode that really matters.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
