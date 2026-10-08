from edurage.rag.service import answer_question


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def retrieve(self, question, *, course_code, top_k):
        self.calls.append((question, course_code, top_k))
        return self.hits


class FakeLLM:
    settings = type("Settings", (), {"llm_model": "deepseek-chat"})()

    def __init__(self):
        self.calls = []

    def answer(self, question, hits):
        self.calls.append((question, hits))
        return "答案来自检索片段。"


def test_service_returns_refusal_without_hits() -> None:
    retriever = FakeRetriever([])
    llm = FakeLLM()

    result = answer_question("问题", "comp-org", 4, retriever=retriever, llm=llm)

    assert result["answer"] == "根据现有资料无法确定"
    assert result["citations"] == []
    assert result["model"] == "deepseek-chat"
    assert llm.calls == []


def test_service_injects_retriever_and_llm_and_preserves_citation_fields() -> None:
    hits = [
        {
            "score": 0.88,
            "payload": {
                "document_id": "doc-9",
                "filename": "实验指导书.pdf",
                "page": 12,
                "snippet": "证据",
                "modality": "text",
            },
        }
    ]
    retriever = FakeRetriever(hits)
    llm = FakeLLM()

    result = answer_question("问题", course_code="comp-org", top_k=2, retriever=retriever, llm=llm)

    assert result["answer"] == "答案来自检索片段。"
    assert result["citations"] == [
        {
            "document_id": "doc-9",
            "filename": "实验指导书.pdf",
            "page": 12,
            "snippet": "证据",
            "score": 0.88,
            "modality": "text",
        }
    ]
    assert retriever.calls == [("问题", "comp-org", 2)]
    assert llm.calls == [("问题", hits)]
