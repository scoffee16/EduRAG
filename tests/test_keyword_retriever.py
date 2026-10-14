from edurage.rag.hybrid_retriever import LocalKeywordRetriever
from edurage.rag.keyword_retriever import extract_terms, keyword_score


def test_extracts_identifiers_and_chinese_phrases_without_character_tokens() -> None:
    terms = extract_terms("ADD 指令的微地址序列涉及 PC、DR 和 SE 控制信号")

    assert {"ADD", "PC", "DR", "SE", "微地址", "控制信号"} <= set(terms)
    assert "微" not in terms
    assert "地" not in terms


def test_keyword_score_explains_identifier_and_phrase_matches() -> None:
    score = keyword_score(
        ["ADD", "PC", "微地址"],
        {"text": "ADD 指令通过 PC 获取微地址"},
    )

    assert score == 0.7


def test_local_keyword_retriever_filters_scope_and_ignores_nonmatches() -> None:
    candidates = [
        {
            "score": 0.9,
            "payload": {
                "course_code": "CS-A",
                "document_id": "doc-1",
                "text": "普通内容",
            },
        },
        {
            "score": 0.2,
            "payload": {
                "course_code": "CS-A",
                "document_id": "doc-1",
                "text": "ADD 控制信号",
                "page": 8,
            },
        },
        {
            "score": 1.0,
            "payload": {
                "course_code": "CS-B",
                "document_id": "doc-1",
                "text": "ADD 控制信号",
            },
        },
    ]

    hits = LocalKeywordRetriever().retrieve(
        "ADD 控制信号",
        course_code="CS-A",
        document_id="doc-1",
        candidates=candidates,
    )

    assert len(hits) == 1
    assert hits[0]["payload"]["page"] == 8
    assert hits[0]["keyword_score"] > 0
