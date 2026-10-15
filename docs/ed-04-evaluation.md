# ED-04 Retrieval Evaluation

## Reproducible command

Run from the repository root. The script prepends this work tree's `src`
directory, so an unrelated installed `edurage` package cannot affect results:

```powershell
python -m scripts.evaluate_retrieval --mode both
```

The golden set is in `tests/fixtures/retrieval_golden.py`. It contains eight
questions and deterministic pages covering a numeric table, short lines, a
figure caption, native text, OCR-only text, and mixed text/OCR pages. Chunks
are produced by `structured_chunk_pages`; retrieval then uses the real keyword,
fusion, and deterministic reranking code. The fixture source is only an
offline replacement for vector/Qdrant I/O and never returns a page based on
the question.

## Metrics and policy

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

The current fixture has no empty-result query, so the empty citation policy is
covered by the metric implementation but not represented in the aggregate.

## Baseline and after

The baseline uses the same vector fixture and local matching, but passes only
the vector top-5 candidates to the keyword retriever. The after run adds the
bounded independent payload candidate source:

| Run | Recall@5 | MRR | Citation page accuracy | Fragment rate | Median chunk length |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline, vector candidates only | 0.5000 | 0.4167 | 0.1250 | 0.5000 | 19 |
| After, independent keyword candidates | 1.0000 | 0.8333 | 0.2500 | 0.5000 | 19 |

These values were produced on October 15, 2026 with the command above. The
result is deterministic and does not require Docker, Qdrant, OCR, embeddings,
or an external API.

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
