from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pymupdf

from edurage.ingest.embedder import HashingEmbedder
from edurage.ingest.indexer import IngestIndexer


class _Vectors:
    def __init__(self) -> None:
        self.points: list[Mapping[str, Any]] = []

    def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        pass

    def upsert(self, collection_name: str, points: Sequence[Mapping[str, Any]]) -> None:
        self.points.extend(points)

    def delete(self, collection_name: str, point_ids: Sequence[str]) -> None:
        pass


class _Repository:
    def __init__(self) -> None:
        self.chunks: list[Mapping[str, Any]] = []

    def insert_document(self, document: Mapping[str, Any]) -> None:
        pass

    def insert_chunks(self, chunks: Sequence[Mapping[str, Any]]) -> None:
        self.chunks.extend(chunks)

    def set_document_status(self, document_id: str, status: str) -> None:
        pass

    def delete_document(self, document_id: str) -> None:
        pass


class _Objects:
    def put(self, key: str, body: bytes, content_type: str) -> None:
        pass

    def delete(self, key: str) -> None:
        pass


def test_indexer_writes_structured_metadata_to_vector_and_db(tmp_path: Path) -> None:
    source = tmp_path / "metadata.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "3.1 实验步骤\n\n地址\t指令\n00H\tLDA")
    document.save(source)
    document.close()

    vectors = _Vectors()
    repository = _Repository()
    indexer = IngestIndexer(
        embedder=HashingEmbedder(),
        vector_store=vectors,
        repository=repository,
        object_store=_Objects(),
    )

    indexer.ingest_pdf(source, "CS-META")

    assert vectors.points
    payload = vectors.points[0]["payload"]
    metadata = repository.chunks[0]["metadata"]
    for record in (payload, metadata):
        assert record["page"] == 1
        assert record["file_type"] == "pdf"
        assert "block_type" in record
        assert "section" in record
        assert "text_sources" in record
        assert "ocr_confidence" in record
