import fitz


def test_sample_pdf_has_three_pages_and_page_markers(sample_pdf_path) -> None:
    document = fitz.open(sample_pdf_path)

    assert document.page_count == 3
    for page_number, page in enumerate(document, start=1):
        text = page.get_text()
        assert f"EduRAG sample PDF page {page_number}." in text
        assert f"Page {page_number}" in text
    assert "deterministic sample content for testing." in document[1].get_text()
    document.close()
