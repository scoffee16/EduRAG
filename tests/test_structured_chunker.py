from edurage.ingest.structured_chunker import structured_chunk_pages


def test_preserves_titles_paragraphs_and_sections() -> None:
    chunks = structured_chunk_pages(
        [
            {
                "page": 2,
                "source_type": "pdf",
                "text": "3.1 实验步骤\n\n先连接电源。\n再检查微地址序列。",
            }
        ]
    )

    assert len(chunks) == 1
    assert chunks[0]["section"] == "3.1 实验步骤"
    assert "先连接电源" in chunks[0]["text"]


def test_keeps_table_rows_in_order() -> None:
    chunks = structured_chunk_pages(
        [{"page": 1, "source_type": "pptx", "text": "地址\t指令\n00H\tLDA\n01H\tSTA"}]
    )

    assert len(chunks) == 1
    assert chunks[0]["block_type"] == "table"
    assert chunks[0]["text"].splitlines() == ["地址\t指令", "00H\tLDA", "01H\tSTA"]


def test_long_block_uses_sliding_window_only_within_page() -> None:
    chunks = structured_chunk_pages(
        [
            {"page": 1, "source_type": "pdf", "text": "a" * 501},
            {"page": 2, "source_type": "pdf", "text": "b"},
        ]
    )

    assert [len(chunk["text"]) for chunk in chunks] == [500, 81, 1]
    assert chunks[0]["text"][-80:] == chunks[1]["text"][:80]
    assert [chunk["page"] for chunk in chunks] == [1, 1, 2]
    assert [chunk["chunk_index"] for chunk in chunks] == [0, 1, 2]


def test_ocr_metadata_is_preserved_without_duplicate_text() -> None:
    chunks = structured_chunk_pages(
        [
            {
                "page": 4,
                "source_type": "pdf",
                "text": "微地址 00H -> 01H",
                "text_sources": ["ocr"],
                "ocr_confidence": 0.87,
            }
        ]
    )

    assert len(chunks) == 1
    assert chunks[0]["modality"] == "ocr"
    assert chunks[0]["block_type"] == "paragraph"
    assert chunks[0]["text_sources"] == ["ocr"]
    assert chunks[0]["ocr_confidence"] == 0.87
    assert chunks[0]["text"] == "微地址 00H -> 01H"


def test_pdf_and_pptx_use_the_same_page_metadata_shape() -> None:
    pdf = structured_chunk_pages(
        [{"page": 3, "source_type": "pdf", "text": "PDF page"}]
    )[0]
    pptx = structured_chunk_pages(
        [{"page": 3, "source_type": "pptx", "text": "PPTX slide"}]
    )[0]

    assert pdf["page"] == pptx["page"] == 3
    assert set(pdf) == set(pptx)


def test_adjacent_short_rows_pack_without_crossing_pages() -> None:
    chunks = structured_chunk_pages(
        [
            {"page": 1, "text": "A\n1\nB\n2\nC\n3", "text_sources": ["text"]},
            {"page": 2, "text": "next page", "text_sources": ["text"]},
        ],
        chunk_size=20,
        overlap=4,
    )

    assert len(chunks) == 2
    assert chunks[0]["page"] == 1
    assert "A\n1\nB\n2" in chunks[0]["text"]
    assert [chunk["chunk_index"] for chunk in chunks] == [0, 1]


def test_mixed_source_chunk_keeps_ocr_marker_out_of_text() -> None:
    chunks = structured_chunk_pages(
        [
            {
                "page": 1,
                "text": "text line\n\n[OCR]\nocr line",
                "text_sources": ["text", "ocr"],
                "page_used_ocr": True,
            }
        ],
        chunk_size=100,
    )

    assert len(chunks) == 1
    assert chunks[0]["modality"] == "mixed"
    assert chunks[0]["text_sources"] == ["text", "ocr"]
    assert "[OCR]" not in chunks[0]["text"]
    assert chunks[0]["page_used_ocr"] is True


def test_caption_is_structural_metadata_not_modality() -> None:
    chunk = structured_chunk_pages(
        [{"page": 1, "text": "图 1 系统结构\n说明文字", "text_sources": ["ocr"]}]
    )[0]

    assert chunk["block_type"] == "caption"
    assert chunk["modality"] == "ocr"
