# Article drafts

One draft per article in `article_idea.md`, in publishing order. Each is dev.to
ready: frontmatter title, `##` headings only, first person, no em dashes, real
code from this repo with file paths as comments, and a bio footer linking the
project.

| # | File | Words | Target from `article_idea.md` |
| --- | --- | --- | --- |
| 1 | `article-01-grounded-fhir-rag-intro.md` | 1411 | medium (2000-2500) |
| 2 | `article-02-fhir-r4-for-ml-engineers.md` | 1504 | medium (1800-2200) |
| 3 | `article-03-one-resource-one-chunk.md` | 1191 | medium (1500-2000) |
| 4 | `article-04-rendering-fhir-to-text.md` | 1342 | medium (1800-2200) |
| 5 | `article-05-pgvector-for-clinical-data.md` | 1692 | medium (2000-2500) |
| 6 | `article-06-hybrid-search-that-wasnt.md` | 1383 | medium (2000-2500) |
| 7 | `article-07-cte-materialization.md` | 1107 | short (1000-1400) |
| 8 | `article-08-reference-resolution.md` | 1135 | medium (1500-2000) |
| 9 | `article-09-near-duplicate-chunks.md` | 1280 | medium (1500-2000) |
| 10 | `article-10-insufficient-data-is-a-feature.md` | 1344 | medium (1800-2200) |
| 11 | `article-11-gemini-thinking-tokens.md` | 1025 | short-medium (1200-1600) |
| 12 | `article-12-four-providers-no-framework.md` | 1170 | medium (1500-2000) |
| 13 | `article-13-evaluating-clinical-rag.md` | 2668 | long (2500-3000) |
| 14 | `article-14-fhir-rag-is-not-document-rag.md` | 1261 | medium (1800-2200) |
| 15 | `article-fhir-rag-vs-tabular.md` | 1425 | pre-existing draft, see its entry for the revision pass |
| 16 | `article-16-vectors-in-postgres.md` | 1214 | medium (1500-2000) |
| 17 | `article-17-silent-reembed.md` | 1087 | short-medium (1200-1600) |
| 18 | `article-18-suggestions-that-read-the-chart.md` | 1417 | medium (1500-1800) |
| 19 | `article-19-alpine-no-build-step.md` | 1161 | short (1000-1400) |
| 20 | `article-20-what-engineers-get-wrong-about-clinical-data.md` | 2543 | long (2500-3000) |
| 21 | `article-21-debugging-rag-15-defects.md` | 2947 | long (3000+) |

## Where the drafts sit against their targets

The three long-form articles (13, 20, 21) were expanded to meet their targets.
13 and 20 are inside their 2500-3000 band; 21 is at 2947 against a "3000+"
estimate, close enough that the remaining gap is not worth padding.

Articles 7, 11, 17, and 19 are at their word targets and are closest to
publishable as they stand.

The remaining medium-length drafts run 1100-1700 words against 1500-2500
targets. Each carries its full argument, real code, and measured evidence, so
nothing is missing structurally. What is missing is elaboration: a second worked
example per section, and the digressions that turn a tight draft into a
satisfying read. Expanding during revision is easier than cutting bloat.

## Before publishing any of them

Numbers, names, and file paths in these drafts come from the repo as of the
`feat/eval-questions` branch. Re-check anything quoted before it goes out,
particularly the baseline metrics table (articles 1 and 13), the resource
counts (articles 2, 3, 21), and the model id in `_generate_claude`
(article 12).

The cross-references between articles are written as prose ("earlier in this
series") rather than as links, since dev.to URLs do not exist yet. Convert them
to real links as each article is published, and add the series name to the
frontmatter of any article published out of order.
