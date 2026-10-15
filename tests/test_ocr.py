from edurage.ingest.ocr import OcrPageResult, should_ocr_page


def test_text_rich_page_does_not_trigger_ocr() -> None:
    assert not should_ocr_page("x" * 120, 0.0)


def test_short_or_image_heavy_page_triggers_ocr() -> None:
    assert should_ocr_page("", 0.0)
    assert should_ocr_page("short text", 0.5)
    assert should_ocr_page("x" * 100, 0.5)


def test_fake_ocr_result_preserves_page_and_source() -> None:
    result = OcrPageResult(page=7, text="微地址 101", confidence=0.92)

    assert result.page == 7
    assert result.source == "ocr"
    assert result.text == "微地址 101"
