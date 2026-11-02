# ED-04-01 Ingestion Quality

## Local Measurement

Measured on 2026-10-15. This is a **local parsing measurement**
(本地解析测量), with no real-document writes to PostgreSQL, Qdrant, or
MinIO. The existing index has not been refreshed.

Both runs used the same 39-page local PDF, verified by a matching SHA-256,
and the same selective OCR settings. The document, filename, extracted text,
and identifying fingerprint are intentionally omitted from this repository.
Aggregate baseline results were saved locally before editing the chunker.
The baseline chunker from commit `a5c70257d33abf35f4ec74326707c9a913dd9827`
was also replayed against the current parser's compatible `text` field.

| Metric | Before | After |
| --- | ---: | ---: |
| Pages | 39 | 39 |
| Chunks | 304 | 67 |
| Chunks with `len(text) < 20` | 168 | 1 |
| Fragment rate | 55.26% | 1.49% |
| Median `len(text)` | 15 | 249 |
| Maximum `len(text)` | 500 | 500 |
| Page 13 chunks | 43 | 1 |
| Pages contributing OCR text | 21 | 21 |
| Pages reporting OCR errors | 0 | 0 |

The fragment-rate denominator includes all nonempty emitted chunks. Length
is Python `len(chunk["text"])`, including internal whitespace and overlap;
it is not a token or Chinese-character count. Page 13 uses 1-based PDF page
numbers. Both targets, fragment rate below 10% and at most 10 chunks on
page 13, were met.

Fixed settings: `chunk_size=500`, `chunk_overlap=80`, OCR enabled,
`ocr_engine=tesseract`, `ocr_dpi=180`, `ocr_min_text_chars=80`,
`ocr_min_image_ratio=0.35`, `ocr_language=chi_sim+eng`. Both runs used
the same installed Tesseract 5.5.3.20260724 executable with `chi_sim` and
`eng` language data. The OCR trigger, rendering DPI, provider, recognition
algorithm, and cloud models were not changed. An OCR-disabled exploratory
run produced 250 chunks, 147 short chunks (58.8%), median 13, and 43 on
page 13; it is excluded from the before/after comparison.

## Effective Paths

Production ingestion follows `IngestIndexer` -> `parse_document` ->
`parse_pdf`/`parse_pptx` -> `structured_chunk_pages` -> configured embedder
and persistence adapters.

`scripts/ingest_local_document.py` uses `preview_document` ->
`parse_document` -> `structured_chunk_pages` -> `HashingEmbedder`.
`scripts/ingest_local_pdf.py` delegates to the same `preview_document`.
The old `chunk_pages` character-window helper is not used by these paths.

When `parse_document` receives neither Settings nor a provider, it now
loads the application Settings and builds the configured provider when
OCR is enabled. This fixes both existing dry-run CLIs within the ingestion
module, without changing the scripts or Settings definitions. Explicit
Settings remain authoritative; provider-only calls retain their existing
OCR opt-in behavior. `parse_pdf` itself still requires an explicitly
supplied provider to perform OCR. Dry-run uses the actual configured
selective OCR path, then local hashing embeddings; it does not persist.

## Chunking Behavior

Short adjacent lines, extracted cells, titles with their body, and captions
with nearby explanation are packed on the same page before applying the
unchanged size limit. Blank lines and changes in line classification no
longer force individual short chunks. A substantial existing block or a
new named section can retain a structural boundary.

Uppercase register names and isolated numbers are not treated as titles.
No numeric lines, short identifiers, potential page numbers, or potential
headers are deleted: without layout evidence, such lines can be meaningful
table values. Tabular extraction order, including empty PPTX columns, is
preserved. Flattened PDF cells retain extraction order; the chunker does
not infer a missing two-dimensional table layout.

Every emitted text or OCR chunk has a positive 1-based page, a
document-wide continuous zero-based `chunk_index`, and length at most
`chunk_size`. Figure chunks (see VLM Figure Understanding) are atomic
descriptions rather than character windows, so they are exempt from the
`chunk_size` limit and are bounded by the VLM output limit instead. Windows
within a packed block share the requested character overlap. Independent
blocks, sections, and pages do not gain artificial overlap. Windowing stops
once the end is reached, avoiding a final window containing only repeated
overlap. With very small overlap, the preceding window can end earlier
to avoid a tiny final tail. A genuinely short standalone page or section
is retained even when shorter than 20 characters.

## Source Metadata

| Field | Meaning |
| --- | --- |
| `modality` | Actual content source in this window: `text`, `ocr`, or `mixed` when both contribute. |
| `page_used_ocr` | Whether the parser called `provider.recognize` on this page; true even for empty, duplicate, or failed OCR output. Rendering failure before the provider call leaves it false. |
| `text_sources` | Ordered unique extraction sources contributing non-whitespace characters to this chunk, including overlap. |
| `block_type` | Content structure in the window: `title`, `paragraph`, `table`, `caption`, or `code`; OCR is not a structure. |
| `section` | The relevant detected or supplied section, retained with the content; a separate page starts a new local section context. |
| `source` | Persisted file origin (`pdf` or `pptx`), from the chunk's `source_type`. |
| `ocr_confidence` | Original page OCR confidence, retained on all page chunks, including text-only chunks; it does not imply those chunks came from OCR. |
| `ocr_error` | Original page OCR error, retained even when text-layer content is usable. |

PDF parsing keeps the existing `text` representation, including the legacy
`[OCR]` separator for combined output. Additive `text_segments` records
carry `{text, source}` provenance without that separator. Chunking uses
these records when present, supports legacy `[OCR]` boundaries when absent,
and never embeds that separator as content. Legacy records declaring both
sources without a boundary are conservatively `mixed`.

An OCR attempt that produces only duplicate text can therefore yield
`page_used_ocr=true`, `modality=text`, and `text_sources=["text"]`.
The indexer's `ocr_pages` count now counts provider calls, including such
attempts, rather than only pages whose OCR text survives deduplication.
Both PostgreSQL chunk metadata and Qdrant payload retain the source fields;
modality remains in the existing dedicated chunk/payload field.

## VLM Figure Understanding

Image-heavy pages that previously indexed only their captions now get an
optional, independent figure chunk. The feature is opt-in and off by
default: with `vlm_enabled=false` the parser, chunker, and indexer output is
byte-identical to the text/OCR path described above.

### Trigger Rules

For each PDF page, `parse_pdf` evaluates figures only when a describer was
supplied. A page is eligible when all of the following hold:

- raster images occupy at least `vlm_figure_min_image_ratio` of the page
  area (computed by `page_image_area_ratio`, the same helper used by OCR);
- the stripped page text is at most `vlm_figure_max_text_chars`
  characters, so text-heavy pages keep their text-only representation;
- at least one image rectangle survives clipping to the page bounds;
- a surviving rectangle covers at least half the area of the page's
  largest image rectangle (`MIN_RELATIVE_FIGURE_AREA`), so the repeated
  template banners, logos, and icons that slide decks stamp on every page
  are never rendered or described.

At most `vlm_max_images_per_page` image rectangles are rendered, ordered by
area (largest first), de-duplicated by image content hash, and clipped to
the page. Each rectangle is rendered to PNG with the long side capped at
1600 px (render scale at most 2x), so vision payloads stay bounded. Text
extraction and OCR behavior are unchanged; figures are additive page
records. Long text pages and pages with only small decorations are skipped
by the thresholds above.

### Prompt And Output

The describer uses an OpenAI-compatible vision endpoint configured by
`vlm_base_url`, `vlm_api_key`, and `vlm_model` (default
`qwen-vl-max`). The message carries the PNG as a base64 data URI plus a
Chinese system prompt that instructs the model to describe only visible
content, to write `无法识别` instead of guessing, and to emit structure:
mind maps as an indented root -> child list, flowcharts as `A -> B` node
chains, tables as headers plus rows, and coordinate charts with axis
meanings. Output is capped by `MAX_DESCRIPTION_TOKENS` (400 tokens).
Descriptions that are blank or only `无法识别` are dropped rather than
indexed, and a rendered region may still be described by a later page
ingestion because the cache is keyed by image content, not by page number.

### Content-Addressed Cache

Descriptions are cached under `vlm_cache_dir` as `{sha256}.json` files,
keyed by the exact rendered PNG bytes. Cache writes are atomic
(`mkstemp` + `os.replace`). Unreadable, corrupt, or empty entries are
ignored and replaced on the next successful call, and cache I/O failures
are logged without failing ingestion. Re-ingesting the same document
therefore does not pay for the same image twice, even across processes.

### Provenance And Retrieval

A described figure becomes its own chunk after the page's text chunks:

| Field | Figure chunk value |
| --- | --- |
| `block_type` | `figure` |
| `modality` | `image` |
| `text_sources` | `["vlm"]` |
| `section` | Last detected section on the page, else `""` |
| `text` | Structured Chinese description |

Figure chunks share the page number and get the normal document-wide
`chunk_index`; they are never merged into text windows. The existing
`source`, `page_used_ocr`, `ocr_confidence`, and `ocr_error` fields are
mirrored from the page, and the existing Qdrant payload / PostgreSQL chunk
metadata construction propagates `block_type`, `modality`, and
`text_sources` without schema changes. Citations can therefore identify
figure-derived context as "第 N 页的图".

### Failure Behavior And Limits

VLM parsing is best-effort. A rendering error, an API error, a timeout, or
an unusable response is logged and simply omits that figure; text/OCR
ingestion always succeeds. Known limitations:

- only raster image regions are handled; vector graphics, embedded
  charts, and text-drawn diagrams are not rendered (see *Vector Graphics
  Figures (Planned)* below);
- only PDF pages are covered; PPTX and DOCX figures are not parsed yet;
- a real OpenAI-compatible VLM endpoint and API key are required; there is
  no local fallback model;
- figure descriptions are model-generated and may be imperfect; the
  prompt asks the model to mark uncertain content as `无法识别`;
- descriptions are capped at 400 tokens (`MAX_DESCRIPTION_TOKENS`), so a
  dense figure may have its tail truncated even when the head is indexed.

### Offline Evaluation

`python -m scripts.evaluate_figures --mode both` runs a deterministic
offline evaluation over `tests/fixtures/figure_golden.py`: a generated
ten-page PDF with five figure pages (mind map, flowchart, table, coordinate
chart, mind map), three text-only pages, one long-text page with a large
image, and one small-image page. A fake describer supplies fixed Chinese
descriptions; a HashingEmbedder cosine retriever plus the local keyword
retriever are fused exactly as in production retrieval.

| Metric | Baseline (VLM off) | After (VLM on) |
| --- | ---: | ---: |
| Total chunks | 12 | 17 |
| Figure chunks | 0 | 5 |
| Figure recall@5 | 0.00 | 1.00 |
| Figure page accuracy | 0.00 | 1.00 |

Figure recall@5 counts questions whose figure page appears among the top-5
hits, and figure page accuracy counts questions whose highest-ranked figure
hit cites the correct page. The baseline cannot answer the five figure
questions from caption text alone, while the VLM path retrieves the
described figure chunks on the correct pages.

### Live Validation

The VLM path was smoke-tested against a real 75-page lecture deck
(`算法设计与分析_第3章_动态规划1-发布版.pdf`) with `qwen3-vl-plus` through
an OpenAI-compatible endpoint:

- 91 chunks were indexed, 5 of them figure chunks;
- only page 7 (multi-stage decision diagram) and page 54 (four matrix-chain
  tables) were eligible, and the repeated template banners were filtered
  out before rendering;
- a question about the edge weights of the page-7 diagram retrieved the
  figure chunk at rank 1 and the answer cited page 7.

To reproduce from the host against the Docker services, point the storage
URLs at the published ports and enable the vision endpoint:

```bash
export EDURAGE_QDRANT_URL=http://127.0.0.1:6333
export EDURAGE_POSTGRES_DSN=postgresql+psycopg://edurage:edurage@127.0.0.1:5432/edurage
export EDURAGE_MINIO_ENDPOINT=127.0.0.1:9000
export EDURAGE_VLM_ENABLED=true
export EDURAGE_VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export EDURAGE_VLM_MODEL=qwen3-vl-plus
export EDURAGE_VLM_API_KEY=your-vision-api-key
export EDURAGE_VLM_CACHE_DIR=.cache/edurage/vlm
```

then ingest with `IngestIndexer.prepare_document` + `IngestIndexer.ingest_pdf`
(or upload through the API once `vlm_enabled` is set in the service
environment). Figure chunks land in Qdrant with `block_type="figure"`,
`modality="image"`, and `text_sources=["vlm"]`.

### Vector Graphics Figures (Planned)

The current gate is raster-only: `page_image_area_ratio` counts embedded
image XObjects (`page.get_images` / `get_image_rects`), so a page whose
flowchart, tree, or coordinate plot is drawn as PDF path commands reports a
ratio near zero and never reaches the describer. Real Chinese courseware
exposes this often: one greedy-algorithm page with an optimal-substructure
tree and an activity-interval chart has 79 vector drawing paths and only a
6% template raster; a dynamic-programming page renders its table as vector
cells. Table borders, formula glyphs, and slide furniture are also path
commands, which is why "just cluster every drawing" needs filtering.

Planned options, in the order they will be attempted:

1. **Path clustering + region rendering.** Collect
   `page.get_drawings()` bounding boxes, drop page-sized background
   rectangles and regions that overlap text lines, merge nearby strokes
   into connected regions, require a minimum region area and stroke
   density, then render the region with `get_pixmap(clip=...)` and reuse
   the existing describer and content-addressed cache. No new services or
   models, but the thresholds are heuristic and diagrams interleaved with
   body text can be split.
2. **Layout detection.** Render the page and run a document-layout model
   (PP-Structure, DocLayout-YOLO, MinerU, ...) to obtain figure/table
   boxes, then crop and describe them. Robust for raster and vector
   content alike and also recovers tables, at the cost of a heavy
   dependency and a GPU-friendly deployment.
3. **Whole-page vision prompt.** Send the rendered page to the vision
   model and ask for structure (optionally with bounding boxes). Cheapest
   to implement, but costs more tokens per page, mixes body text with
   figure content, and gives no region-level provenance.

The likely sequence is (1) as an opt-in path validated on the real
courseware set, with (2) added if recall is insufficient. The current
configuration stays raster-oriented; a dedicated vector-area threshold and
a vector-figure fixture would ship together with the implementation.

## Filename Contract

The following keyword-only interfaces are frozen for ED-04-04:

```python
indexer.ingest_document(path, course_code, *, original_filename=None)
indexer.ingest_pdf(path, course_code, *, original_filename=None)
indexer.ingest_pptx(path, course_code, *, original_filename=None)
```

Omitting `original_filename` keeps the path basename behavior. A supplied
name is reduced to its final component using either slash convention;
ASCII controls are removed, Windows-invalid basename characters are
replaced with underscores, and surrounding whitespace/trailing dots are
trimmed. An unusable basename raises `ValueError` before side effects.
Unicode filenames are retained.

The resulting single name is written to `Document.filename`,
PostgreSQL chunk `metadata.filename`, Qdrant `payload.filename`, and the
last segment of MinIO `object_key`. Parsing, type detection, and byte reads
continue to use the actual local path. The caller must pass the user's
original upload name when the path is temporary; no API changes are
included here.

Existing best-effort compensation still removes this ingestion's document,
vector points, and object when a downstream write fails. Offline fake
adapters exercise partial writes in collection setup, vector upsert,
document insertion, chunk insertion, and status updates.

## Validation And Integration

Offline tests use fake OCR and fake persistence adapters. They cover short
cells, empty columns, short lines, captions, title/body association,
independent sections/pages, continuous indices, long-window reconstruction,
actual source metadata, OCR failure/deduplication, both CLI entrypoints,
all three filename entrypoints, and compensation. VLM figure tests cover
cache hit/miss/corruption, the disabled path, payload shape, long-side
downscaling, threshold and image-cap behavior, tolerated describer
failures, figure chunk provenance, and indexer payload/metadata propagation.

Required checks:

```powershell
python -m ruff check .
$env:TEMP = Join-Path $PWD ".tmp"
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
python -m pytest -q --basetemp .pytest-tmp
python -m scripts.evaluate_figures --mode both
docker compose config --quiet
git diff --check
```

The old index requires re-ingestion from the original documents to replace
fragmented chunks and correct source/filename metadata. Existing entries
are not migrated in place. Coordinate replacement with the owning agent;
this task does not remove historical documents, collections, or volumes,
and does not start or rebuild shared Docker services. The real PDF was
measured locally only.
