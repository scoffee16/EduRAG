from edurage.rag.prompt import MODEL_KNOWLEDGE_SOURCE_NOTICE, NO_EVIDENCE_ANSWER
from edurage.rag.service import answer_question


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []
        self.scopes = []

    def retrieve(self, question, *, course_code, top_k, **kwargs):
        self.calls.append((question, course_code, top_k))
        self.scopes.append(kwargs.get("document_ids"))
        return self.hits


class FakeLLM:
    settings = type("Settings", (), {"llm_model": "deepseek-chat"})()

    def __init__(self):
        self.calls = []
        self.general_calls = []

    def answer(self, question, hits):
        self.calls.append((question, hits))
        return "答案来自检索片段。"

    def answer_from_general(self, question):
        self.general_calls.append(question)
        return "通用知识回答。"


def test_service_falls_back_to_model_knowledge_without_hits() -> None:
    retriever = FakeRetriever([])
    llm = FakeLLM()

    result = answer_question("问题", "comp-org", 4, retriever=retriever, llm=llm)

    assert result["answer"] == MODEL_KNOWLEDGE_SOURCE_NOTICE + "通用知识回答。"
    assert result["answer"].startswith("> 知识来源：模型通用知识")
    assert result["knowledge_sources"] == ["model_knowledge"]
    assert result["citations"] == []
    assert result["web_results"] == []
    assert result["model"] == "deepseek-chat"
    assert llm.calls == []
    assert llm.general_calls == ["问题"]
    assert retriever.scopes == [None]


def test_service_keeps_no_evidence_answer_when_general_answer_is_empty() -> None:
    llm = FakeLLM()
    llm.answer_from_general = lambda question: ""

    result = answer_question("问题", retriever=FakeRetriever([]), llm=llm)

    assert result["answer"] == NO_EVIDENCE_ANSWER
    assert result["knowledge_sources"] == []


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
                "file_type": "pdf",
            },
        }
    ]
    retriever = FakeRetriever(hits)
    llm = FakeLLM()

    result = answer_question("问题", course_code="comp-org", top_k=2, retriever=retriever, llm=llm)

    assert result["answer"] == "答案来自检索片段。"
    assert result["knowledge_sources"] == ["course_materials"]
    assert result["web_results"] == []
    assert result["citations"] == [
        {
            "document_id": "doc-9",
            "filename": "实验指导书.pdf",
            "page": 12,
            "snippet": "证据",
            "score": 0.88,
            "modality": "text",
            "file_type": "pdf",
        }
    ]
    assert retriever.calls == [("问题", "comp-org", 2)]
    assert retriever.scopes == [None]
    assert llm.calls == [("问题", hits)]
    assert llm.general_calls == []


def test_service_forwards_document_ids_scope_to_retriever() -> None:
    hits = [
        {
            "score": 0.9,
            "payload": {"document_id": "doc-a", "text": "ADD 控制信号"},
        }
    ]
    retriever = FakeRetriever(hits)
    llm = FakeLLM()

    result = answer_question(
        "问题",
        course_code="CS-DEMO",
        document_ids=[" doc-a ", "doc-b", "doc-a"],
        retriever=retriever,
        llm=llm,
    )

    assert result["knowledge_sources"] == ["course_materials"]
    assert retriever.scopes == [["doc-a", "doc-b"]]
    assert llm.calls == [("问题", hits)]


def test_service_normalizes_legacy_document_id_into_document_scope() -> None:
    retriever = FakeRetriever([])

    answer_question(
        "问题",
        course_code="CS-DEMO",
        document_id=" doc-1 ",
        retriever=retriever,
        llm=FakeLLM(),
    )

    assert retriever.scopes == [["doc-1"]]


def test_service_prefers_document_ids_over_legacy_document_id() -> None:
    retriever = FakeRetriever([])

    answer_question(
        "问题",
        course_code="CS-DEMO",
        document_id="legacy",
        document_ids=["doc-a", "doc-b"],
        retriever=retriever,
        llm=FakeLLM(),
    )

    assert retriever.scopes == [["doc-a", "doc-b"]]
