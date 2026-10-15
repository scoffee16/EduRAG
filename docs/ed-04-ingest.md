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

Every emitted chunk has a positive 1-based page, a document-wide continuous
zero-based `chunk_index`, and length at most `chunk_size`. Windows within a
packed block share the requested character overlap. Independent blocks,
sections, and pages do not gain artificial overlap. Windowing stops once
the end is reached, avoiding a final window containing only repeated
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
all three filename entrypoints, and compensation.

Required checks:

```powershell
python -m ruff check .
$env:TEMP = Join-Path $PWD ".tmp"
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
python -m pytest -q --basetemp .pytest-tmp
docker compose config --quiet
git diff --check
```

The old index requires re-ingestion from the original documents to replace
fragmented chunks and correct source/filename metadata. Existing entries
are not migrated in place. Coordinate replacement with the owning agent;
this task does not remove historical documents, collections, or volumes,
and does not start or rebuild shared Docker services. The real PDF was
measured locally only.
