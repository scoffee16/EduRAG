"""Deterministic retrieval-evaluation pages; no external documents are required."""

from __future__ import annotations

from typing import Any

from edurage.ingest.structured_chunker import structured_chunk_pages

COURSE_CODE = "CS-GOLDEN"

_PAGES = [
    {
        "document_id": "doc-native",
        "filename": "native.pdf",
        "file_type": "pdf",
        "page": 1,
        "text": "表1 微地址控制字矩阵\nADD\t1010\tPC\t1\nSUB\t1011\tDR\t0",
        "text_sources": ["text"],
    },
    {
        "document_id": "doc-native",
        "filename": "native.pdf",
        "file_type": "pdf",
        "page": 2,
        "text": "PC -> MAR",
        "text_sources": ["text"],
    },
    {
        "document_id": "doc-native",
        "filename": "native.pdf",
        "file_type": "pdf",
        "page": 3,
        "text": "图1 ADD 指令微地址序列：取指、译码、执行。",
        "text_sources": ["text"],
    },
    {
        "document_id": "doc-native",
        "filename": "native.pdf",
        "file_type": "pdf",
        "page": 4,
        "text": "原生文字：ADD 指令产生控制信号并访问微地址。",
        "text_sources": ["text"],
    },
    {
        "document_id": "doc-ocr",
        "filename": "scan.pdf",
        "file_type": "pdf",
        "page": 5,
        "text": "[OCR]\nA D D 指令\n微 地 址 1010\n控制 信号",
        "text_sources": ["ocr"],
        "ocr_confidence": 0.91,
    },
    {
        "document_id": "doc-ocr",
        "filename": "scan.pdf",
        "file_type": "pdf",
        "page": 6,
        "text": "扫描页摘要：数据通路与寄存器。",
        "text_sources": ["ocr"],
        "ocr_confidence": 0.88,
    },
    {
        "document_id": "doc-ocr",
        "filename": "scan.pdf",
        "file_type": "pdf",
        "page": 7,
        "text": "图2 控制信号时序图。",
        "text_sources": ["ocr"],
        "ocr_confidence": 0.87,
    },
    {
        "document_id": "doc-ocr",
        "filename": "scan.pdf",
        "file_type": "pdf",
        "page": 8,
        "text": "OCR 表格：DR 读取数据，PC 保存地址。",
        "text_sources": ["text", "ocr"],
        "ocr_confidence": 0.86,
    },
]

GOLDEN_QUESTIONS: tuple[dict[str, Any], ...] = (
    {"id": "matrix", "question": "ADD 微地址矩阵中的控制信号是什么？", "relevant": [("doc-native", 1)]},
    {"id": "short-line", "question": "PC 到 MAR 的传送是什么？", "relevant": [("doc-native", 2)]},
    {"id": "figure-caption", "question": "ADD 指令微地址序列是什么？", "relevant": [("doc-native", 3)]},
    {"id": "native", "question": "ADD 指令访问微地址时产生什么控制信号？", "relevant": [("doc-native", 4)]},
    {"id": "ocr-space", "question": "ADD 指令的微地址序列是什么？", "relevant": [("doc-ocr", 5)]},
    {"id": "ocr-summary", "question": "扫描页的数据通路和寄存器是什么？", "relevant": [("doc-ocr", 6)]},
    {"id": "ocr-figure", "question": "控制信号时序图在哪一页？", "relevant": [("doc-ocr", 7)]},
    {"id": "mixed-source", "question": "DR 读取数据、PC 保存地址的 OCR 表格在哪？", "relevant": [("doc-ocr", 8)]},
)


def golden_chunks() -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for page in _PAGES:
        for chunk in structured_chunk_pages([page], chunk_size=500, overlap=80):
            payload = {
                "course_code": COURSE_CODE,
                "document_id": page["document_id"],
                "filename": page["filename"],
                "file_type": page["file_type"],
                **chunk,
                "page_used_ocr": "ocr" in page.get("text_sources", []),
            }
            chunks.append({"score": 0.0, "payload": payload})
    return chunks
