---
title: "One Client, Four LLM Providers, No Framework"
published: false
tags: llm, python, architecture, api
series: "Grounded RAG over FHIR"
---

My system talks to Claude, the Gemini Developer API, Vertex AI Express Mode, and a local Ollama instance. Switching between them is one environment variable.

The abstraction that makes that work is 164 lines of `httpx` and one dataclass. There is no LangChain, no LiteLLM, no provider registry. I want to explain why that was the right call at this size, and where I would stop making it.

## What the abstraction actually has to cover

The scope question comes first, because it determines everything else. My application makes exactly one kind of LLM call: a system prompt containing retrieved FHIR context, a user message containing the question, one turn, no tools, no streaming, no conversation history.

That is the entire surface area. Under those constraints, a provider abstraction is a function with two string parameters and a normalised return type:

```python
# src/generation/llm_client.py
@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int


async def generate(self, system_prompt: str, user_message: str) -> LLMResponse:
    """Send prompt to LLM and return response."""
    if self.provider == "claude":
        return await self._generate_claude(system_prompt, user_message)
    if self.provider == "gemini":
        return await self._generate_gemini(system_prompt, user_message)
    if self.provider == "vertex":
        return await self._generate_vertex(system_prompt, user_message)
    return await self._generate_ollama(system_prompt, user_message)
```

Token counts are in the return type deliberately. They are the only reliable way to know what a request cost and how full the context is getting, and a provider abstraction that discards them makes cost invisible at exactly the point where it is measurable.

## Where the providers genuinely disagree

The differences are smaller than the ecosystem suggests, and they are concentrated in three places.

**System prompts.** Anthropic takes a top-level `system` parameter. Gemini takes `systemInstruction`. Ollama's generate endpoint has no concept of one, so it gets concatenated. Vertex AI Express Mode is the odd one out and gets its own section below.

**Usage accounting.** `input_tokens`/`output_tokens` on Anthropic, `promptTokenCount`/`candidatesTokenCount` inside `usageMetadata` on Google, `prompt_eval_count`/`eval_count` on Ollama. Same concept, three names, all needing a default because any of them can be absent.

**Response shape.** Anthropic returns content blocks that need filtering by type. Google returns candidates containing parts that need joining. Ollama returns a string.

Here is the Anthropic path in full, which is the shortest:

```python
# src/generation/llm_client.py
async def _generate_claude(self, system_prompt: str, user_message: str) -> LLMResponse:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=self.api_key)
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    content = "".join(
        block.text for block in response.content if getattr(block, "type", "text") == "text"
    )
    usage = response.usage
    return LLMResponse(
        content=content,
        model=response.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
```

The import is inside the function on purpose. The `anthropic` package is only needed when that provider is selected, so someone running entirely on Ollama does not need it installed.

## Vertex Express Mode accepts only two roles

The one genuine surprise. Gemini through the Developer API accepts `systemInstruction`. The same model through Vertex AI Express Mode does not, and it accepts only `user` and `model` message roles. Send a system role and it rejects the request.

So the system prompt gets folded into the user turn:

```python
# src/generation/llm_client.py
if provider == "vertex":
    # Vertex AI Express Mode accepts only user and model message roles.
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": f"{system_prompt}\n\n{user_message}"}]}
        ],
        "generationConfig": _google_generation_config(),
    }
    url = ("https://aiplatform.googleapis.com/v1/publishers/google/models/"
           f"{self.gemini_model}:generateContent")
else:
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": _google_generation_config(),
    }
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{self.gemini_model}:generateContent")
```

Two paths, one shared response parser below them, and a shared generation config so the thinking-budget settings cannot diverge between them. That config exists because of a bug worth its own article: Gemini charges internal reasoning against `maxOutputTokens`, and unbounded it consumed 85% of the budget and truncated answers mid-citation.

The relevant point for this article is that I found and fixed that in about an hour, because the request payload was right there in my code and I could print the response body without going through a wrapper.

## The case against a framework here

A framework earns its place by amortising complexity across many uses. Mine has one use.

What I would have gained: pre-written provider adapters, retry logic, and a standard interface.

What I would have paid, concretely:

A dependency that moves faster than my application does. Frameworks in this space have breaking changes on a cadence that has nothing to do with my release schedule, and I would be tracking them for four functions I already wrote.

Debugging through indirection. When Vertex rejected my system role, the failure was a 400 with a terse message. Finding it in my own code took reading twenty lines. Finding it inside a framework means reading the adapter, working out which abstraction layer transformed my input, and determining whether the framework's version of "system prompt" maps to what Vertex means.

Provider-specific features behind a lowest-common-denominator interface. `thinkingConfig` is Google-specific. A generic interface either does not expose it, or exposes it through an escape hatch that is uglier than just writing the request.

And the honest one: the abstraction I would have imported is not smaller than the one I wrote. Four functions, one dataclass, one dispatch. There is no complexity here to hide.

## Where I would change my mind

Four triggers, and I do not think any of them is far-fetched.

**Streaming.** Token-by-token output means handling three different streaming protocols with three different chunk formats and three different ways of signalling completion. That is real, fiddly work with real edge cases, and it is exactly the kind of thing worth importing.

**Tool use.** Function-calling schemas differ substantially between providers, and normalising them is a genuine abstraction problem rather than a naming problem.

**Multi-turn conversation.** Message history, role handling, and context window management across providers with different limits.

**Retries and fallback.** Rate limits, transient failures, and failing over between providers mid-request. There is well-tested code for this and my version would be worse.

Notice what those have in common: each one is a place where the providers differ *structurally*, not just in field names. My current abstraction works because the differences it spans are cosmetic. When they stop being cosmetic, hand-rolling stops being cheap.

## The heuristic

Write the direct version first and see how big it is. If it is under 200 lines and the differences between backends are naming rather than structure, you have learned that the abstraction is small and you now own it. If it sprawls, you have learned something real about the problem and you will import a framework knowing exactly what you need from it.

The failure mode I was avoiding is reaching for a framework to handle complexity that turns out not to exist, and then debugging through it for the next year.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
