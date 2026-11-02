# ED-04 Evaluation: Retrieval and Answer Faithfulness

This document covers three evaluation layers:

1. `scripts/evaluate_retrieval.py` — offline, deterministic fixture that isolates
   the keyword/fusion/reranking logic.
2. `scripts/evaluate_courseware.py` — the real annotated corpus, evaluated
   against the live Qdrant collection with real embeddings.
3. `scripts/evaluate_answers.py` — generation-layer faithfulness and citation
   coverage on top of the same live retrieval stack.

## Reproducible commands

Offline fusion fixture (no Docker, Qdrant, embedding or LLM calls). Run from the
repository root; the script prepends this work tree's `src` directory, so an
unrelated installed `edurage` package cannot affect results:

```powershell
python -m scripts.evaluate_retrieval --mode both
```

Live corpus retrieval (host-run; `.env` points at Docker-internal hostnames, so
override the endpoints for a process on the host):

```powershell
$env:PYTHONPATH='src'
$env:PYTHONIOENCODING='utf-8'
$env:EDURAGE_QDRANT_URL='http://127.0.0.1:6333'
$env:EDURAGE_POSTGRES_DSN='postgresql+psycopg://edurage:edurage@127.0.0.1:5432/edurage'
$env:EDURAGE_MINIO_ENDPOINT='127.0.0.1:9000'
python -m scripts.evaluate_courseware --mode both --limit 40
```

Live answer faithfulness and citation coverage (answer model and judge model
default to `deepseek-chat`; 20 questions by default):

```powershell
python -m scripts.evaluate_answers --limit 20 --judge-model deepseek-chat
```

Both live scripts write a JSON artifact under `.tmp/` and print a Markdown
table; `--top-k` and `--output` are also available. The live scripts share the
metric helpers in `src/edurage/eval/retrieval_metrics.py`, which reproduce the
page-level formulas below exactly; the offline script predates that module and
keeps its inline implementation so its deterministic output is unchanged.

## Offline fusion fixture

The golden set is in `tests/fixtures/retrieval_golden.py`. It contains eight
questions and deterministic pages covering a numeric table, short lines, a
figure caption, native text, OCR-only text, and mixed text/OCR pages. Chunks
are produced by `structured_chunk_pages`; retrieval then uses the real keyword,
fusion, and deterministic reranking code. The fixture source is only an
offline replacement for vector/Qdrant I/O and never returns a page based on
the question.

## Metrics and policy

Retrieval metrics, shared by the offline fixture and the live corpus script:

- Page Recall@5 is the mean, over questions, of
  `|unique returned (document_id, page) intersect relevant pages| /
  |relevant pages|`.
- MRR is the mean reciprocal rank of the first relevant returned page.
  Questions with no relevant hit contribute `0`.
- Citation page accuracy is relevant unique citation pages divided by unique
  returned citation pages. Empty retrieval has accuracy `1.0` because there
  are no incorrect citations; an empty result for a question with relevant
  pages still contributes zero recall and zero MRR.
- Duplicate chunks on one document page count once for page metrics. The
  `(document_id, page)` key means the same page number in different documents
  remains distinct.
- Fragment rate is the fraction of chunks whose text length is less than 20
  characters.
- Median chunk length is the median character length of fixture chunks.

The live corpus has no empty-retrieval result: every question returns pages,
so the empty-retrieval convention of citation page accuracy is exercised only
by unit tests, exactly as in the fixture.

## Baseline and after (offline fixture)

The baseline uses the same vector fixture and local matching, but passes only
the vector top-5 candidates to the keyword retriever. The after run adds the
bounded independent payload candidate source:

| Run | Recall@5 | MRR | Citation page accuracy | Fragment rate | Median chunk length |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline, vector candidates only | 0.6250 | 0.5313 | 0.1250 | 0.3750 | 23.5 |
| After, independent keyword candidates | 1.0000 | 0.9063 | 0.2000 | 0.3750 | 23.5 |

These values were produced on October 22, 2026 with the command above. The
result is deterministic and does not require Docker, Qdrant, OCR, embeddings,
or an external API.

## Real courseware corpus

`tests/fixtures/courseware_golden.py` annotates 40 questions over six real
documents already indexed in the live `edurage_chunks` collection. The corpus
is courseware for the algorithms course (dynamic programming, greedy
algorithms) plus one recurrent-neural-network slide deck; the two course codes
are kept per question because the collection uses `course_code="1"` for the
PDFs and `course_code="2"` for the RNN slides.

| Document | Course code | Indexed pages | Indexed chunks | Questions |
| --- | --- | ---: | ---: | ---: |
| 算法设计与分析_第3章_动态规划1-发布版.pdf | 1 | 75 | 86 | 7 |
| 算法设计与分析_第3章_动态规划2-发布版.pdf | 1 | 38 | 67 | 7 |
| 算法设计与分析_第3章_动态规划3-发布版 - 副本.pdf | 1 | 39 | 50 | 7 |
| 算法设计与分析_第3章_动态规划4-发布版.pdf | 1 | 51 | 66 | 6 |
| 算法设计与分析_第4章_贪心算法1-发布版.pdf | 1 | 41 | 42 | 6 |
| 04-循环神经网络.pptx | 2 | 49 | 63 | 7 |

Annotation policy:

- Gold pages are pages whose indexed chunk payload text actually contains the
  answer. Every candidate page was read back from the live Qdrant payloads
  before being annotated; the page text was not inferred from the PDF or from
  the question.
- Each question carries the document id, `course_code`, one gold page, a
  content type, and short `reference_facts` bullet facts for the generation
  evaluation. Questions are natural Chinese and remain answerable from the
  annotated page alone.
- Pages whose OCR text was too garbled to support a clean question were
  skipped; one question planned for a garbled complexity slide was moved to
  the clean memoized-matrix-chain page. No content was invented: all 126
  reference facts are restatements of indexed page text.
- Content-type mix: definition 6, equation 7, algorithm steps 6, complexity 7,
  numeric example 4, table 4, comparison 2, figure caption 3, API 1.

The collection also holds 116 payload points across 58 two-page
integration-test documents (`course_code` `CS-INTEGRATION`; 56 of them are
`qdrant-integration.pdf`). They are excluded per question by the `course_code`
filter that both the vector and the keyword paths apply.

## Real-corpus retrieval results

Command: `python -m scripts.evaluate_courseware --mode both --limit 40`, run on
November 2, 2026 against the live collection (real `text-embedding-v3`
embeddings, 5 pages per question, page-level dedupe).

| Run | N | Recall@5 | MRR | Citation page accuracy | Questions missing a gold page |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline, vector candidates only | 40 | 0.9750 | 0.7238 | 0.1975 | 1 |
| hybrid, independent keyword candidates | 40 | 0.7500 | 0.6521 | 0.1513 | 10 |

Unlike the deterministic fixture, the hybrid retriever is **worse** than the
vector-only baseline on the real corpus. This is a measured result, not a
regression in the metric code: both runs use the same questions, filters and
metric helpers, and the hybrid run only adds the bounded independent keyword
candidate source, weighted RRF (0.6 vector / 0.4 keyword, `rrf_k=60`,
`candidate_k=20`) and the deterministic reranker. The single baseline miss is
`dp4-q05` (OPTIMAL-BST complexity, gold page 40: the vector ranking prefers
related pages, including pages from other documents, over page 40).

The hybrid run misses ten questions, produced on the same 40 questions:
`dp1-q05`, `dp2-q01`, `dp2-q03`, `dp2-q04`, `dp3-q01`, `dp4-q04`, `dp4-q05`,
`dp4-q06`, `greedy-q04`, `greedy-q05`. Most of them are near misses on
adjacent content pages rather than annotation errors, but page-level Recall@5
counts them as misses.

Likely causes, in the order they appear in the code:

- The keyword scorer is presence-based: it extracts 2-4 character CJK n-grams
  and ASCII identifiers from the question, then scores a page by how many terms
  it contains (`0.1 * matched_terms + 0.2 * exact_identifiers`). Chinese
  questions about common courseware words match many pages, so keyword ranks
  are noisy.
- The fused rank mixes those noisy keyword ranks with the vector ranks. A page
  that the vector path ranked low but that matches generic question terms can
  outrank a semantically strong vector hit.
- The deterministic reranker adds `0.025` per matched exact identifier and
  another `0.025` per additional matched term. These bonuses are large relative
  to the RRF scores. OCR math pages render formulas with Unicode mathematical
  italic characters (for example `𝑚[𝑖,𝑗]`), which the ASCII identifier
  matcher does not see, so an identifier bonus can promote a clean-text page
  that merely repeats formula fragments over the mathematically correct page.

The honest conclusion for ED-04 is that the keyword/fusion path wins on the
small deterministic fixture but loses page recall on real OCR courseware. The
current production default is still the hybrid retriever; tuning the weights,
gating keyword candidates to vector candidates, or making identifier matching
Unicode-aware are follow-ups, not changes made for this document.

## Generation-layer evaluation

`scripts/evaluate_answers.py` mirrors the production service wiring: it builds
`RAGService` (retriever + hybrid + answerer), retrieves the top-5 chunks once
per question through the hybrid retriever, and then asks the answer model to
answer from exactly those chunks. The retrieved hits are passed to the judge
as `[fragment i]` and the returned citation list as `[citation i]`, matching
the numbering in `src/edurage/rag/prompt.py`. The LLM judge is called with
`temperature=0.0` and must return one JSON object:

```json
{
  "claims": [
    {
      "claim": "...",
      "supported": true,
      "supporting_fragment_indices": [1],
      "cited_citation_indices": [1],
      "citation_supported": true,
      "reason": "..."
    }
  ],
  "covered_reference_fact_indices": [1]
}
```

Metric definitions (implemented in `src/edurage/eval/faithfulness.py`; the JSON
parser tolerates Markdown fences and short prose around the object):

- An answer is decomposed by the judge into atomic factual claims. For each
  claim the judge decides whether the retrieved fragments support it, which
  fragments support it, which citation indices the answer attached to it, and
  whether at least one cited chunk actually supports it.
- **Faithfulness** = supported claims / total claims for one answer, averaged
  over questions. A model claim that is true in general but absent from the
  retrieved context counts as unsupported (groundedness, not truthfulness).
- **Citation coverage** = claims that are supported by the fragments **and**
  reference at least one citation index **and** whose cited chunk supports the
  claim, divided by total claims, averaged over questions. It measures whether
  the answer points at evidence for its supported claims, not just whether an
  answer happens to include a citation somewhere.
- Reference-fact coverage = `covered_reference_fact_indices` count / number of
  annotated `reference_facts`, averaged over questions. It is an auxiliary
  annotation-based check; it is not part of the primary faithfulness metric.
- If an answer is the no-evidence refusal
  (`根据现有资料无法确定`) the per-answer faithfulness and citation coverage are
  defined as `1.0` vacuously (there are no unsupported claims). A non-refusal
  answer with zero extractable claims scores `0.0`. No refusals occurred in the
  measured run.
- Aggregation is the mean of per-question ratios (macro average), matching the
  retrieval metric aggregation; the artifact also records raw total and
  supported claim counts.

Command: `python -m scripts.evaluate_answers --limit 20
--judge-model deepseek-chat`, run on November 2, 2026 with answer model
`deepseek-chat`, judge model `deepseek-chat`, judge temperature `0.0`, top-k 5.

| Run | N | Claims | Faithfulness | Citation coverage | Ref-fact coverage | Citation page accuracy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| hybrid retrieval + DeepSeek answer/judge | 20 | 189 | 0.8533 | 0.7204 | 0.8333 | 0.1525 |

Raw counts behind the macro averages: 160 of 189 claims are supported
(84.7%); 133 of 189 supported claims both carry a citation index and are backed
by the cited chunk (70.4%). Retrieval on the same 20 questions: Recall@5 0.75,
MRR 0.6042; 15 of 20 answers cite the annotated gold page at least once.
Citation page accuracy is low (0.1525) because each answer attaches about four
to five citation pages and only one of them is the annotated gold page; this
uses the strict page-level convention above, so additional correct pages that
are simply not annotated reduce it.

The unsupported claims fall into three recurring classes, visible in the
artifact `.tmp/evaluate_answers.json`:

- General-knowledge additions that the fragments do not state (for example
  mentioning Boyer-Moore voting for majority element, or memoised versus
  bottom-up implementations when the page does not say so).
- Derived computations the model performed itself (for example expanding a
  matrix-chain cost table step by step when the page only shows the total).
- Answers to questions whose gold page was not retrieved, where the model
  filled gaps from model knowledge.

## Limitations

- Gold pages are page-level. A relevant chunk on an adjacent page of the same
  document is still a miss and still zero recall, and repeated formulas on
  consecutive slides make this common in lecture PDFs.
- The 40 questions were authored while reading the indexed chunk text, not the
  original PDFs. That guarantees answerability from the index, but it may
  over-represent text that chunking preserved well and under-represent
  figure-only content.
- OCR noise is real in this corpus: page text contains broken formulas and
  Unicode mathematical italics. Complex pages were sometimes avoided during
  annotation, so the corpus over-samples clean pages.
- The generation evaluation uses one LLM judge (`deepseek-chat`,
  `temperature=0.0`) with no human audit of the 189 claims. Judge variance and
  the judge sharing a model family with the answerer are unmeasured risks; the
  claim-level report in the JSON artifact supports spot-checking.
- The generation sample is 20 questions, so per-question ratios move the
  aggregate by about five points. The 40-question retrieval run is the more
  stable number.
- The live numbers depend on the host stack: Qdrant collection contents,
  `text-embedding-v3` embedding server, and the DeepSeek API. The offline
  fixture remains the reproducible CI gate; the live scripts are evidence
  artifacts, and their run timestamps are recorded in the JSON.

## Independent keyword scan

`build_hybrid_retriever(vector_retriever, settings)` installs
`QdrantKeywordCandidateSource` when the vector retriever exposes a Qdrant-like
client with `scroll`. It reads payloads only (`with_vectors=False`), applies
`course_code` and `document_id` filters in the Qdrant request, and stops at
`keyword_scan_limit` (default-compatible fallback: 2000). The source exposes
`truncated`, and emits a warning when the limit is reached. The source is
injectable, so offline fakes can exercise the same path.

The default `HybridRetriever(vector_retriever)` construction remains backward
compatible and vector-candidate-only. The factory is the explicit composition
entry point for ED-04-04.
