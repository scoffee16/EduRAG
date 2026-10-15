import pytest

from edurage.ingest.ocr import (
    OcrPageResult,
    TesseractOCRProvider,
    build_ocr_provider,
    check_ocr_availability,
    requested_languages,
    should_ocr_page,
)


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


def test_provider_keeps_configured_tesseract_command() -> None:
    provider = TesseractOCRProvider(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

    assert provider.tesseract_cmd == r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def test_provider_defaults_to_path_lookup() -> None:
    assert TesseractOCRProvider().tesseract_cmd == "tesseract"
    assert TesseractOCRProvider("   ").tesseract_cmd == "tesseract"


def test_build_ocr_provider_passes_tesseract_command() -> None:
    provider = build_ocr_provider(True, "tesseract", tesseract_cmd="/usr/bin/tesseract")

    assert isinstance(provider, TesseractOCRProvider)
    assert provider.tesseract_cmd == "/usr/bin/tesseract"


def test_build_ocr_provider_returns_none_when_disabled() -> None:
    assert build_ocr_provider(False, "tesseract") is None


def test_build_ocr_provider_rejects_unknown_engine() -> None:
    with pytest.raises(ValueError, match="Unsupported OCR engine"):
        build_ocr_provider(True, "paddleocr")


def test_requested_languages_splits_tesseract_expression() -> None:
    assert requested_languages("chi_sim+eng") == ["chi_sim", "eng"]
    assert requested_languages(" eng ") == ["eng"]
    assert requested_languages("") == []


def test_check_ocr_availability_reports_disabled_without_probing() -> None:
    diagnostics = check_ocr_availability(enabled=False, engine="tesseract")

    assert diagnostics.enabled is False
    assert diagnostics.available is False
    assert diagnostics.error is None


def test_check_ocr_availability_rejects_unknown_engine() -> None:
    diagnostics = check_ocr_availability(enabled=True, engine="paddleocr")

    assert diagnostics.available is False
    assert diagnostics.error == "Unsupported OCR engine: paddleocr"
