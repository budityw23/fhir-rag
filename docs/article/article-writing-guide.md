# Article Writing Guide: dev.to

Author: Budi Widhiyanto
Profile: https://dev.to/budiwidhiyanto

This guide defines the writing style for articles in the "Grounded RAG over FHIR" series and future dev.to technical articles. It is based on analysis of published articles and natural writing patterns observed in comments, conversations, and professional communication.

---

## Voice identity

The author is an Indonesian senior software engineer with 8+ years of production experience in healthcare data systems. English is a second language, used professionally every day. The writing should sound like a competent engineer explaining a decision to a peer, not like a copywriter crafting an essay.

The target voice is: clear, direct, technically confident, and honest about trade-offs. Not literary. Not performative. The reader should trust the author because of what he knows, not how he phrases it.

### What the voice sounds like

- "I chose pgvector because the system already needs relational filters and joins. A separate vector store would mean a second system to keep in sync."
- "The lexical arm returned zero rows on every realistic question. I did not notice for weeks because the vector arm carried the fusion by itself."
- "This is not fixed properly. Diversity-aware retrieval is still unimplemented."

### What the voice does NOT sound like

- "That second half turned out to be the interesting part." (literary setup)
- "There's more scar tissue on this query than any other part of the system." (native-speaker idiom)
- "Asking is not the same as getting." (rhetorical inversion)
- "Sarah's phone buzzed at 2:43 AM." (fictional scenario opening)
- "Let's dive into..." / "In this article, we'll walk through..." (filler transitions)

---

## Article structure

### Opening (first 3-5 sentences)

Start with the problem or the thing you built. No fictional scenarios. No "imagine you are..." No "in this article I will discuss..." The reader should know what this article is about by the second sentence.

Good opening patterns:
- State what you built and the constraint that shaped it
- State the problem you hit and why it was not obvious
- State the decision and the reason in the same sentence

Example:
> "The hybrid search had two retrieval arms, vector and full-text, fused with Reciprocal Rank Fusion. For weeks the lexical arm returned zero rows on every realistic question, and end-to-end answers still looked correct."

### Section flow

Each article follows one of these shapes:

**Decision article**: Problem > What I chose > Why > How it works (with code) > What it costs > What I would do differently

**Debugging article**: Symptom > What I expected > What actually happened > The measurement that found it > The fix > The lesson

**Introduction article**: What it does > Why it exists > The pipeline (with code) > What it scores > What it gets wrong > What comes next

### Section headings

Use `##` for main sections. Use prose headings, not numbered lists ("Why refusal is the requirement" not "1. Refusal"). The heading should tell the reader what the section argues, not just what topic it covers.

### Closing

End with one of:
- What comes next in the series, naming the specific topic
- The honest limitation you have not solved yet
- A concrete takeaway the reader can use

Do NOT end with:
- "Thanks for reading"
- "I hope this was helpful"
- "Drop your thoughts in the comments"
- A generic summary of what the article covered

### Author bio

Keep it to 1-2 lines at the bottom. Include the project repo link. Same bio across the series for consistency.

Standard format:
> *I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github link].*

---

## Language rules

### Grammar and syntax

- Write in first person singular ("I built", "I chose") when describing your own decisions
- Use "we" only when genuinely referring to a team effort
- Prefer active voice: "The query returned zero rows" not "Zero rows were returned by the query"
- Keep sentences short to medium. Mix a short declarative sentence after a longer explanatory one
- No semicolons for stylistic effect. Use periods instead
- No em dashes. Use commas, periods, or parentheses
- No Oxford comma is fine. Either way is fine, but be consistent within one article

### Words and phrases to avoid

These are native-speaker patterns that make AI-assisted writing detectable:

| Avoid | Use instead |
|---|---|
| "It turns out that..." | State the finding directly |
| "The interesting part is..." | Just say the thing |
| "Here's the thing:" | Remove. Start the sentence |
| "Under the hood" | "Internally" or just describe it |
| "More scar tissue than..." | "This part had the most bugs" |
| "I lost an afternoon to that" | "That took several hours to debug" |
| "Asking is not the same as getting" | "The prompt asks for citations, but the model does not always follow the format" |
| "That said," | "But" or start new sentence |
| "Spoiler alert:" | Remove |
| "Let's dive into..." | Remove. Just start the section |
| "In this article, we'll..." | Remove. Just start |
| "Think of it like..." | Only use if the analogy is technical, not literary |
| "Game-changer" | Describe the specific improvement |
| "Not pretty" / "nightmare" | Describe the actual consequence |
| "Here's why it works:" | Remove. List the reasons |
| "Without further ado" | Remove |

### Transitions between sections

Do not use literary transitions. Use functional ones or just start the new topic with a clear first sentence:

- "The next layer is retrieval."
- "After ingestion, each resource is stored with its metadata."
- "This decision had a cost."
- Or just start: "Retrieval runs two arms over that table."

Do NOT use:
- "Now that we understand X, let's explore Y"
- "But wait, there's more"
- "So" as a paragraph opener (reads as casual native English)
- "With that in mind,"

---

## Code blocks

### When to include code

- Include code when the article is arguing about an engineering decision. The code is the evidence.
- Each code block should be 10-40 lines. If longer, split it and narrate between blocks.
- Include the file path as a comment on the first line: `# src/retrieval/hybrid_search.py`

### How to introduce code

One sentence before the code block saying what it does and why it matters. Then the code. Then one sentence after explaining the key line or the non-obvious part.

Do NOT:
- Put a heading and then immediately a code block with no prose
- Explain every line of the code (the reader is an engineer)
- Use "Let's take a look at the code:" as introduction

### Output and data

When showing query results, evaluation scores, or measurements, use a markdown table. Keep it compact. Let the numbers speak.

---

## Formatting

- Use `##` for sections, `###` for subsections. Never `#` (that is the title)
- Bold only for key terms on first introduction, not for emphasis
- Inline code for function names (`extract_codes`), file names (`hybrid_search.py`), config values, and technical terms
- No bullet-point-heavy articles. Prefer prose with code. Use bullets only for short lists of concrete items (dependencies, config options, steps to run)
- Keep paragraphs to 3-5 sentences maximum
- One-sentence paragraphs are fine for a key point, but do not overuse them

---

## dev.to specifics

### Frontmatter

```yaml
---
title: "Descriptive title here"
published: false
tags: fhir, rag, postgres, healthcare
series: "Grounded RAG over FHIR"
---
```

- Tags: max 4. Always include `fhir` and `rag` for this series. Add topic-specific tags.
- Series name keeps all articles connected.
- Set `published: false` in drafts.

### Cover image

Generate separately (DALL-E or similar). Dark background, consistent color palette across the series.

### Cross-linking

- Every article after #1 should link back to the introduction article
- Reference 1-2 previous articles when the topic builds on them
- Use relative anchor text: "as described in the retrieval article" not "as described in Article 6"

---

## Quality checklist before publishing

Read the draft and check:

1. Can a reader tell what this article is about by the second sentence?
2. Does every code block have a file path comment and at least one sentence of context?
3. Are there any fictional scenarios or "imagine you are..." constructions?
4. Are there any phrases from the "avoid" list?
5. Does the article end with something concrete (a next step, an open problem, a takeaway)?
6. Is there a section that honestly names a limitation or trade-off?
7. No em dashes anywhere?
8. Does the voice sound like the author explaining a decision to a peer, or like a copywriter explaining a product?
9. Would the author's dev.to comment section voice match the article voice?
10. Is every opinion backed by a reason or a measurement?