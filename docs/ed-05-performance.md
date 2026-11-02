# ED-05 Retrieval and Generation Performance

This document records how EduRAG measures query latency, where each timing
stage is instrumented, and the numbers produced by the P0-3.1 performance
work. All figures below were measured on the development machine on
2026-11-02; they are a baseline, not an SLA.

## Where the timings come from

Query latency is split into stages by the code that actually performs the
work. The resulting `timings` object is returned by both `POST /api/v1/query`
and the `done` event of `POST /api/v1/query/stream`, and is persisted in
`query_history.timings`.

| Stage | Field | Instrumented in |
| --- | --- | --- |
| Query embedding | `query_embedding_ms` | `src/edurage/rag/retriever.py` (`Retriever.retrieve`) |
| Qdrant vector search | `vector_search_ms` | `src/edurage/rag/retriever.py` (`Retriever.retrieve`) |
| Keyword candidate scan | `keyword_scan_ms` | `src/edurage/rag/hybrid_retriever.py` (`QdrantKeywordCandidateSource.retrieve`) |
| Keyword scoring | `keyword_search_ms` | `src/edurage/rag/hybrid_retriever.py` (`LocalKeywordRetriever.retrieve`) |
| Weighted RRF fusion | `fusion_ms` | `src/edurage/rag/hybrid_retriever.py` (`HybridRetriever.retrieve`) |
| Deterministic rerank | `rerank_ms` | `src/edurage/rag/hybrid_retriever.py` (`HybridRetriever.retrieve`) |
| Whole retrieval call | `retrieve_ms` | `src/edurage/rag/service.py` (`answer_question` / `stream_answer_question`) |
| LLM generation | `llm_ms` | `src/edurage/rag/service.py` |
| Web-search fallback | `web_search_ms` | `src/edurage/rag/service.py` |
| First streamed token | `first_token_ms` | `src/edurage/rag/service.py` (measured from request start, including retrieval) |
| End-to-end | `total_ms` | `src/edurage/rag/service.py`; mirrors `latency_ms` |

The `timings` object also carries context-budget counters (`context_chars`,
`dropped_hits`) and retrieval fan-out counters (`candidate_k`,
`vector_candidates`, `keyword_candidates`, `fused_hits`, `returned_hits`,
`keyword_scan_truncated`).

## Retrieval benchmark

`scripts/benchmark_retrieval.py` sends the real question set through the
production hybrid retriever (real embedding API + live Qdrant collection) and
reports nearest-rank P50/P95 per stage.

```powershell
$env:PYTHONPATH = "src"
$env:EDURAGE_QDRANT_URL = "http://127.0.0.1:6333"
$env:EDURAGE_POSTGRES_DSN = "postgresql+psycopg://edurage:edurage@127.0.0.1:5432/edurage"
$env:EDURAGE_MINIO_ENDPOINT = "127.0.0.1:9000"
python -m scripts.benchmark_retrieval --repeats 3 --limit 8 --json .tmp/benchmark.json
```

Setup: 8 courseware questions (dynamic programming, greedy, RNN), 3 repeats
each (24 samples), `top_k=5`, `candidate_k=20`, collection
`edurage_chunks` with 490 points, one warm-up not included in the samples.

| Stage | Mean (ms) | P50 (ms) | P95 (ms) | Max (ms) |
| --- | ---: | ---: | ---: | ---: |
| `retrieve_ms` | 216.1 | 178.6 | 229.6 | 1062.2 |
| `query_embedding_ms` | 139.9 | 111.5 | 136.4 | 981.4 |
| `vector_search_ms` | 13.1 | 8.4 | 30.2 | 31.7 |
| `keyword_search_ms` | 59.2 | 55.4 | 94.4 | 100.2 |
| `fusion_ms` | 0.1 | 0.1 | 0.2 | 0.2 |
| `rerank_ms` | 3.3 | 3.0 | 5.9 | 6.6 |

The single 1-second outlier is the first embedding call of the process
(TLS/connection setup to the embedding provider); excluding that sample the
retrieval P95 stays under ~230 ms. The keyword path includes one Qdrant
`scroll` page of payload candidates (`EDURAGE_KEYWORD_SCAN_LIMIT=2000`,
`keyword_scan_truncated=false` for this collection).

## End-to-end numbers

Measured through the real API (host-run `uvicorn`, live Qdrant/PostgreSQL/
MinIO, real DeepSeek + embedding API) for the question
「动态规划算法的基本要素有哪些？」 with `course_code=1`, `top_k=5`:

| Path | Retrieval | First token | Total | Notes |
| --- | ---: | ---: | ---: | --- |
| `POST /query/stream` (SSE, warm) | 283.4 ms | 1025.4 ms | 1926.0 ms | `llm_ms=1641.8`; 5 citations; 334 answer chars |
| `POST /query` (JSON, cold embedding) | 1136.9 ms | n/a | 3159.9 ms | `query_embedding_ms=1060.6`, `llm_ms=2022.9` |
| `POST /query` (JSON, warm, earlier run) | — | n/a | ~1922.7 ms | `latency_ms` from the Docker Compose API |

For the warm SSE run the stage breakdown was: embedding 194.8 ms, Qdrant
vector search 7.4 ms, keyword scan 45.6 ms, keyword scoring 77.5 ms, fusion
0.15 ms, rerank 3.1 ms, generation 1641.8 ms.

## Reading the numbers

- Retrieval is a few hundred milliseconds: about 14.7% of the 1926 ms
  end-to-end warm run (283 / 1926).
- Generation is the bottleneck: 1641.8 ms of 1926.0 ms (~85.3%). The interview
  answer should be "检索不是瓶颈，LLM 生成才是，所以先做流式把首字等待从
  2-3 秒降到约 1 秒".
- Inside retrieval the external embedding call dominates (111-195 ms), while
  Qdrant search is single-digit-to-tens of milliseconds and fusion/rerank are
  sub-10 ms. Keyword scanning is the second-largest retrieval cost.
- `first_token_ms` includes retrieval by design (it is the user-perceived
  wait); the non-streaming JSON path has no equivalent field and reports only
  `total_ms`.

## Caveats

- Timings come from a single-host Docker Compose deployment; network variance
  to the model/embedding providers moves the numbers by tens of percent.
- First requests after process start are slower because of provider
  connection/TLS setup (see the 1062 ms outlier). Comparisons should use warm
  samples.
- P50/P95 are computed with nearest-rank over the sampled runs; the sample
  size (24) is enough for a sanity check, not for a strict latency SLO.
- `llm_ms` measures the generation phase, not time-to-first-token of the
  non-streaming path.

## Reproduce

```powershell
python -m pytest -q tests/test_benchmark.py          # percentile/summary helpers
python -m scripts.benchmark_retrieval --repeats 3    # live P50/P95 table
python -m scripts.benchmark_retrieval --mode fixture # offline pipeline self-check
```
