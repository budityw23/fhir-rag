You are doing a voice revision pass on a draft article. The structure, code blocks, and technical content stay exactly as they are. You are only revising the prose to match the author's actual writing voice.

## Step 1: Read the draft

Read the article draft at: docs/article/article-01-introduction.md (or wherever the draft is stored)

## Step 2: Read the author's published writing for voice reference

Fetch these published articles to learn how the author actually writes. Read them carefully for sentence rhythm, paragraph length, how transitions work, how opinions are stated, and how technical explanations are introduced:

- https://dev.to/budiwidhiyanto (profile page, scan recent titles)
- https://dev.to/budiwidhiyanto/how-we-cut-gcp-daily-costs-by-79-in-6-weeks-on-a-federated-health-data-platform-54gh
- https://dev.to/budiwidhiyanto/maternity-hl7-to-fhir-pipeline-bridging-legacy-hospital-messages-to-modern-healthcare-apis-m1o
- https://dev.to/budiwidhiyanto/one-pipeline-two-continents-adding-eu-fhir-profiles-to-an-australian-healthcare-integration-43ek

## Step 3: Identify the voice gap

Before making any changes, write a short analysis (for yourself, not in the output file) of:
- What the published articles sound like (sentence patterns, transitions, how opinions are framed)
- What the draft sounds like that does not match
- Specific phrases or patterns in the draft that feel "too native"

## Step 4: Revise

Apply these rules to every paragraph of prose. Do not touch code blocks, the YAML frontmatter, or the evaluation table.

### Remove native-speaker idioms and rhetorical flourishes
The author is Indonesian with strong technical English. His real writing is direct and competent, not literary. Replace:
- Clever setups ("That second half turned out to be the interesting part") with direct statements
- Metaphors and idioms ("more scar tissue on it than any other part of the system", "I lost an afternoon to that one") with plain descriptions of what happened
- Rhetorical inversions ("Asking is not the same as getting") with straightforward transitions
- Aphoristic conclusions ("a system description that lists only successes is not useful") with concrete statements

The author does use first person and does state opinions. That stays. The difference is: he says "I chose X because Y" not "X, it turned out, was the move that changed everything."

### Match his sentence rhythm
His published articles mix:
- Short declarative sentences for key points ("The pipeline has seven stages." "This is a generated column.")
- Longer sentences for technical explanation, but still with simple clause structure
- Occasional one-sentence paragraphs for emphasis, but not as a stylistic pattern

He does NOT do:
- Uniform medium-length polished cadence
- Sentences that delay the main point for dramatic effect
- Parallel structure for rhetorical effect ("It decides the chunk boundary. It decides what goes in the prompt. It decides what the API returns.")

### Transitions
His real transitions are functional, not literary:
- "The next part is..." / "After ingestion, retrieval works like this..."
- Jumping straight into a new topic with a clear first sentence
- He does not use "So" as a paragraph opener (which reads as casual native English)

### Keep what already works
- First person voice ("I built", "I chose")
- Honest about trade-offs and open problems
- Code blocks with file path comments
- The evaluation table
- No em dashes (verify none were introduced)
- Section structure and headings

### Things to verify
- No em dashes anywhere (use commas, periods, or parentheses)
- No semicolons used for stylistic effect (he rarely uses them)
- No "scar tissue", "under the hood", "the interesting part", "it turns out", "the short version is", "here is the thing" or similar native filler
- No trailing rhetorical questions
- The bio at the bottom should stay as-is

## Step 5: Output

Write the revised article to the same file, replacing the draft. Do not add commentary or notes inside the file. After writing, show a diff summary of what changed and why.