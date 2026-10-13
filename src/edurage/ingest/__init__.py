"""Document ingestion pipeline components."""

from edurage.ingest.chunker import chunk_pages
from edurage.ingest.document_parser import parse_document
from edurage.ingest.embedder import Embedder, HashingEmbedder, OpenAIEmbedder
from edurage.ingest.indexer import IngestIndexer, create_default_indexer
from edurage.ingest.pdf_parser import parse_pdf
from edurage.ingest.pptx_parser import parse_pptx

__all__ = [
    "Embedder",
    "HashingEmbedder",
    "IngestIndexer",
    "OpenAIEmbedder",
    "chunk_pages",
    "create_default_indexer",
    "parse_document",
    "parse_pdf",
    "parse_pptx",
]
