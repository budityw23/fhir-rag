---
title: "Gemini's Thinking Tokens Ate 85% of My Output Budget"
published: false
tags: llm, gemini, debugging, ai
series: "Grounded RAG over FHIR"
---

The answer stopped after 182 characters, mid-word. My grounding checker reported it as ungrounded with zero citations, which was technically correct, because the truncation had landed inside a `[Observation/1a4d-` citation marker and the closing bracket never arrived.

The HTTP status was 200. Nothing in my pipeline logged a problem.

## The wrong diagnosis first

My first theory was that the model was being asked to enumerate too much. The question wanted a list of medications with dates and dosages, and the answer was cut off partway through the list. Enumeration is long, `maxOutputTokens` was 2048, so presumably the list simply did not fit.

I wrote that up in my debugging notes and moved on. It was wrong, and it was wrong in an instructive way: the explanation was plausible enough that I never looked at the response body.

When I finally did, the actual cause was sitting in fields I had never read:

```json
{
  "finishReason": "MAX_TOKENS",
  "thoughtsTokenCount": 1742,
  "candidatesTokenCount": 302
}
```

Of a 2048-token budget, 1,742 tokens went to internal reasoning and 302 to visible text. Eighty-five percent of what I was paying for produced nothing I could see.

## maxOutputTokens is a shared budget

`gemini-2.5-flash` is a thinking model. It reasons internally before producing an answer, and those reasoning tokens are billed as output and **counted against `maxOutputTokens`**.

That is the whole bug. I had read `maxOutputTokens: 2048` as "the answer may be up to 2048 tokens". It actually means "reasoning plus answer may total 2048 tokens", and reasoning goes first. For an extraction task over a context block of 25 clinical resources, the model finds plenty to think about, and it thinks until the budget is nearly gone.

The same applies to Claude's extended thinking and to OpenAI's reasoning models. Each has its own parameter names and its own accounting, and in every case the mental model of "output limit means answer limit" is wrong.

## Measuring instead of guessing

Three configurations, same prompt, same context:

| Config | finishReason | thinking | output | chars |
| --- | --- | --- | --- | --- |
| 2048, unbounded thinking | MAX_TOKENS | 1964 | 80 | 382 |
| 2048, thinkingBudget 0 | STOP | 0 | 1675 | 6824 |
| 4096, thinkingBudget 512 | STOP | 448 | 2122 | 8436 |

Row two is the interesting one. Turning thinking off entirely, at the *same* 2048 budget, produced a complete answer twenty times longer. The budget was never the constraint on the answer. Thinking was.

Row three is what I shipped. More headroom plus a bounded thinking budget gives the model room to reason on multi-hop questions while guaranteeing the answer has somewhere to go.

And note the thinking column: with an explicit budget of 512 it used 448 tokens. Unbounded, it used 1,964. **A bounded budget produced better answers using fewer thinking tokens**, which is not the tradeoff I expected. Left unconstrained on a task that does not need deep reasoning, the model expands to fill whatever space it is given.

## The fix

```python
# src/generation/llm_client.py
# Gemini 2.5 counts internal reasoning against maxOutputTokens. At the previous
# 2048 cap, thinking consumed ~1750 tokens and answers were cut off mid-citation
# with finishReason=MAX_TOKENS. A bounded thinking budget plus more headroom
# keeps multi-hop reasoning available while guaranteeing room for the answer.
GOOGLE_MAX_OUTPUT_TOKENS = 4096
GOOGLE_THINKING_BUDGET = 512


def _google_generation_config() -> dict:
    """Generation config shared by the Gemini and Vertex request paths."""
    return {
        "maxOutputTokens": GOOGLE_MAX_OUTPUT_TOKENS,
        "thinkingConfig": {"thinkingBudget": GOOGLE_THINKING_BUDGET},
    }
```

Shared between the Gemini Developer API path and the Vertex path, because they take the same config and diverging would guarantee that one of them drifts.

Across a 17-question regression set, truncations went from several to zero.

## The check that should have existed from day one

The deeper problem was not the token budget. It was that a silent failure had no way to become loud. So `finishReason` is now something I read:

```python
# src/generation/llm_client.py
if candidates and candidates[0].get("finishReason") == "MAX_TOKENS":
    # Otherwise the answer is returned cut off mid-sentence and the
    # citation mapper reports it as ungrounded for the wrong reason.
    logger.warning(
        "%s response hit maxOutputTokens (thinking=%s, output=%s); answer truncated",
        provider,
        usage.get("thoughtsTokenCount", 0),
        usage.get("candidatesTokenCount", 0),
    )
```

Eight lines. Had they been there originally, the misdiagnosis would have lasted about thirty seconds.

`finishReason` is a value with meaning, not metadata. `STOP` means the model finished. `MAX_TOKENS` means it ran out of room and what you have is a fragment. The same distinction exists as `stop_reason` on Anthropic's API and `finish_reason` on OpenAI's, and in all three the truncated case arrives as a successful response.

## The generalisable version

**An HTTP 200 is not evidence of a complete answer.** It is evidence that a request was processed. Whether the result is usable is in the body, in a field you have to choose to read.

This is a specific instance of a pattern that shows up everywhere in this project: jobs that report attempted work rather than committed work, retrieval arms that return zero rows without erroring, upserts that report success while discarding every value. The pipeline says "success" and the state says otherwise, and the only defence is checking the state.

For LLM calls specifically, three things are worth asserting on every response: the finish reason is the one you expect, the output token count is nonzero, and if you are on a thinking model, the reasoning tokens are not consuming your budget.

If you are running a thinking model for extraction, structured output, or anything else where the answer format matters more than the reasoning depth, bound the thinking budget explicitly. The default is not tuned for your task, and its failure mode is a truncated answer that looks like a model quality problem.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
