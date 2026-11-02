# Context Management (P1-3.11)

This note describes the context-management mechanisms EduRAG actually
implements today, what is deliberately not implemented, and how the behaviour
is measured. EduRAG is a single-turn RAG API: there is no session, no
conversation history, and no long-term memory, so "context" here means the
evidence that is injected into one answer prompt.

## What is implemented

### 1. Retrieval injection (not full-corpus stuffing)

The prompt only receives the top `top_k` (default 5) fused and reranked
chunks, never the raw candidate pool (20 vector + up to 20 keyword
candidates). The model never sees the rest of the courseware, so the prompt
size is bounded by the evidence, not by the corpus. The retrieval fan-out is
still visible in `timings` (`candidate_k`, `vector_candidates`,
`keyword_candidates`, `fused_hits`, `returned_hits`).

### 2. Evidence character budget

`EDURAGE_CONTEXT_MAX_CHARS` (default `4000`) caps the total size of the
formatted evidence block in one prompt. `select_hits_within_budget` in
`src/edurage/rag/prompt.py` applies the budget as a **relevance prefix**:

- hits are already in relevance order, so evidence is added while the
  formatted block fits;
- the first block that would overflow stops the selection — a smaller
  lower-ranked chunk is not allowed to jump over a larger higher-ranked one;
- at least one hit is always kept, even if a single chunk already exceeds the
  budget, so a grounded answer still has something to cite;
- the selector returns `(selected_hits, dropped_hits, used_chars)`; the
  service stores `context_chars` and `dropped_hits` in `timings` and the
  dropped count is visible in `GET /api/v1/history`.

Why a prefix rather than a knapsack: prompt citation indices (`[片段 1]`,
`[片段 2]`, …) are assigned in order, and citation checking in the prompt
rules depends on that order matching the retrieval ranking. Filling the
budget out of order would silently re-rank evidence and make the citation
numbers harder to verify. The trade-off is that a very long first chunk can
push everything else out; the budget still guarantees one citable chunk.

The budget exists because chunk sizes are not uniform: structured table/code
chunks and VLM figure descriptions can be much longer than a body-text
window, and five such chunks can otherwise push a single prompt past the
model's cost/latency comfort zone.

### 3. Prompt-level grounding rules

The system prompt constrains the model to the injected snippets: it must not
invent pages, must cite only pages that appear in the snippets, must say when
the evidence is insufficient, and must label any model-knowledge supplement
with a fixed Markdown block quote. Source layering is deterministic in the
service, not left to the model.

### 4. Structured request slots

The request has a small structured scope rather than free-text context:
`course_code` (retrieval filter) and `document_ids` (1-50 document scope,
resolved into a Qdrant payload filter). This is the only "structured slot"
the current API has; there is no extracted-slot object passed between turns.

## What is deliberately not implemented

- **Conversation trimming** — no multi-turn API, so there is no history to
  trim. Adding it would require a session store and a policy for recent-N
  turns versus summary.
- **History summarization** — no long history exists to summarize.
- **Memory retrieval/injection** — no long-term memory subsystem; the
  interview-documented architecture (extract facts → vector store → top-k
  recall → inject → maintain) is not part of this codebase, and the answer
  should say so rather than imply it exists.
- **Token-budget splitting per source** — the budget covers the evidence
  block only; there is no separate cap for history or tool output because
  those inputs do not exist here.

If multi-turn were added, the design would be: keep the last N turns plus
their citations, summarize earlier turns into a bounded state, inject only
retrieved evidence relevant to the current question, and keep a per-section
token budget (history / evidence / instructions) so no single section can
starve the others.

## How it is measured and tested

- Live sample (5 chunks, `context_chars=1461`, `dropped_hits=0`, budget
  4000): the budget did not trigger. It triggers on longer table/figure
  chunks or after raising `top_k`.
- `tests/test_timings.py::test_select_hits_within_budget_is_a_relevance_prefix`
  covers the empty-hit, degenerate-budget, exact-fit, and overflow cases.
- `timings.context_chars` and `timings.dropped_hits` are returned by both the
  JSON and streaming endpoints and persisted in `query_history.timings`, so
  the effect of changing the budget is observable without extra logging.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `EDURAGE_CONTEXT_MAX_CHARS` | `4000` | Max characters of formatted evidence per prompt; `0` still keeps the single highest-ranked hit |
| `EDURAGE_TOP_K` | `5` | Number of evidence chunks requested from retrieval |
| `EDURAGE_CANDIDATE_K` | `20` | Fusion candidate pool size before truncation |
| `EDURAGE_CHUNK_SIZE` / `EDURAGE_CHUNK_OVERLAP` | `500` / `80` | Chunk size that determines how many chunks fit the budget |
