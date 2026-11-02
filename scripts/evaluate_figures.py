"""Run the deterministic ED-04 VLM figure golden evaluation.

The evaluation is fully offline: the fixture PDF is generated with pymupdf and a
fake describer supplies fixed Chinese figure descriptions.  Both the baseline
(text-only ingestion) and the after (VLM figure chunks) paths are scored with the
same deterministic vector/keyword retrieval stack.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# Keep the command reproducible without requiring an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edurage.ingest.embedder import HashingEmbedder
from edurage.ingest.pdf_parser import parse_pdf
from edurage.ingest.structured_chunker import structured_chunk_pages
from edurage.rag.hybrid_retriever import HybridRetriever, LocalKeywordRetriever
from tests.fixtures.figure_golden import (
    COURSE_CODE,
    DOCUMENT_ID,
    FIGURE_QUESTIONS,
    FILENAME,
    FakeFigureDescriber,
    make_figure_pdf,
)

TOP_K = 5
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


class FixtureVectorRetriever:
    """Deterministic HashingEmbedder cosine retriever over fixture chunks."""

    def __init__(self, chunks: Sequence[Mapping[str, Any]]) -> None:
        self.chunks = [dict(chunk) for chunk in chunks]
        self.embedder = HashingEmbedder()
        self.vectors = [
            self.embedder.embed_query(str(chunk["payload"].get("text", "")))
            for chunk in self.chunks
        ]

    def retrieve(self, question: str, **kwargs: Any) -> list[dict[str, Any]]:
        top_k = kwargs.get("top_k") or len(self.chunks)
        query_vector = self.embedder.embed_query(question)
        ranked = [
            {"score": _cosine(query_vector, vector), "payload": dict(chunk["payload"])}
            for chunk, vector in zip(self.chunks, self.vectors)
        ]
        ranked.sort(key=lambda hit: -float(hit["score"]))
        return ranked[:top_k]


class FixtureKeywordSource:
    """Expose every fixture chunk to the local keyword retriever."""

    def __init__(self, chunks: Sequence[Mapping[str, Any]]) -> None:
        self.chunks = [dict(chunk) for chunk in chunks]
        self.truncated = False

    def retrieve(self, **kwargs: Any) -> list[dict[str, Any]]:
        del kwargs
        return [{"score": 0.0, "payload": dict(chunk["payload"])} for chunk in self.chunks]


def _chunks(pages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for chunk in structured_chunk_pages(pages, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
        payload = {
            "course_code": COURSE_CODE,
            "document_id": DOCUMENT_ID,
            "filename": FILENAME,
            "file_type": "pdf",
            **chunk,
        }
        chunks.append({"score": 0.0, "payload": payload})
    return chunks


def evaluate(*, with_figures: bool) -> dict[str, Any]:
    """Score figure-question retrieval with or without VLM figure chunks."""

    with tempfile.TemporaryDirectory() as directory:
        pdf_path = make_figure_pdf(Path(directory) / FILENAME)
        describer = FakeFigureDescriber() if with_figures else None
        pages = parse_pdf(pdf_path, figure_describer=describer)
    chunks = _chunks(pages)
    vector = FixtureVectorRetriever(chunks)
    keyword = LocalKeywordRetriever(
        FixtureKeywordSource(chunks),
        scan_limit=len(chunks) + 1,
    )
    retriever = HybridRetriever(vector, keyword, candidate_k=len(chunks))

    recalls: list[float] = []
    accuracies: list[float] = []
    rows: list[dict[str, Any]] = []
    for item in FIGURE_QUESTIONS:
        hits = retriever.retrieve(item["question"], course_code=COURSE_CODE, top_k=TOP_K)
        figure_hits = [
            hit["payload"] for hit in hits if hit["payload"].get("block_type") == "figure"
        ]
        first_figure_page = figure_hits[0].get("page") if figure_hits else None
        recalls.append(
            1.0 if any(payload.get("page") == item["page"] for payload in figure_hits) else 0.0
        )
        accuracies.append(1.0 if first_figure_page == item["page"] else 0.0)
        rows.append(
            {
                "id": item["id"],
                "page": item["page"],
                "first_figure_page": first_figure_page,
                "recall_at_5": recalls[-1],
                "page_accuracy": accuracies[-1],
                "returned": [
                    {
                        "page": hit["payload"].get("page"),
                        "block_type": hit["payload"].get("block_type"),
                        "modality": hit["payload"].get("modality"),
                    }
                    for hit in hits
                ],
            }
        )
    figure_chunks = [chunk for chunk in chunks if chunk["payload"].get("block_type") == "figure"]
    return {
        "with_figures": with_figures,
        "metrics": {
            "total_chunks": len(chunks),
            "figure_chunk_count": len(figure_chunks),
            "figure_recall_at_5": sum(recalls) / len(recalls),
            "figure_page_accuracy": sum(accuracies) / len(accuracies),
        },
        "questions": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("baseline", "after", "both"), default="both")
    args = parser.parse_args()
    reports: dict[str, Any] = {}
    if args.mode in ("baseline", "both"):
        reports["baseline"] = evaluate(with_figures=False)
    if args.mode in ("after", "both"):
        reports["after"] = evaluate(with_figures=True)
    print(json.dumps(reports, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
