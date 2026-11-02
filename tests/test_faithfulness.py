"""Offline tests for the claim-level faithfulness evaluation primitives.

The LLM judge is always injected with a fake client, so no test touches the
network or a real API key.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from edurage.eval.faithfulness import (
    JUDGE_JSON_SCHEMA_HINT,
    LLMClaimJudge,
    build_judge_prompt,
    compute_claim_metrics,
    extract_json_object,
    judge_answer,
    normalize_assessment,
    response_text,
)
from edurage.rag.prompt import NO_EVIDENCE_ANSWER


class FakeJudge:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def assess(
        self,
        *,
        question: str,
        answer: str,
        fragments: list[dict[str, Any]] | tuple[Any, ...],
        citations: list[dict[str, Any]] | tuple[Any, ...],
        reference_facts: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "question": question,
                "answer": answer,
                "fragments": list(fragments),
                "citations": list(citations),
                "reference_facts": tuple(reference_facts),
            }
        )
        return self.payload


class FakeCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeChatClient:
    def __init__(self, content: str) -> None:
        self.completions = FakeCompletions(content)
        self.chat = SimpleNamespace(completions=self.completions)


def _fragment(page: int) -> dict[str, Any]:
    return {"payload": {"document_id": "doc", "page": page, "snippet": f"page {page} text"}}


def _citation(page: int) -> dict[str, Any]:
    return {"document_id": "doc", "page": page, "filename": "f.pdf", "snippet": "cited text"}


def test_extract_json_object_tolerates_fences_and_prose() -> None:
    payload = {"claims": [{"claim": "x", "supported": True}]}
    assert extract_json_object(json.dumps(payload)) == payload

    fenced = "Here is the assessment:\n```json\n" + json.dumps(payload) + "\n```\nDone."
    assert extract_json_object(fenced, required_keys=("claims",)) == payload

    noisy = "note {not json} then " + json.dumps(payload)
    assert extract_json_object(noisy, required_keys=("claims",)) == payload


def test_extract_json_object_rejects_missing_json() -> None:
    with pytest.raises(ValueError, match="judge response"):
        extract_json_object("")
    with pytest.raises(ValueError, match="judge response"):
        extract_json_object("the judge refused to answer")


def test_response_text_handles_mapping_and_object_responses() -> None:
    mapping = {"choices": [{"message": {"content": "hello"}}]}
    assert response_text(mapping) == "hello"
    obj = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))])
    assert response_text(obj) == "hi"
    assert response_text({}) == ""


def test_normalize_assessment_clamps_and_drops_invalid_claims() -> None:
    payload = {
        "claims": [
            {
                "claim": "supported claim",
                "supported": True,
                "supporting_fragment_indices": [1, 5, 0],
                "cited_citation_indices": [2, 9],
                "citation_supported": True,
            },
            {"claim": "  ", "supported": True},
            "not a mapping",
        ],
        "covered_reference_fact_indices": [1, 4, 0],
    }

    assessment = normalize_assessment(
        payload,
        fragment_count=2,
        citation_count=2,
        reference_fact_count=3,
    )

    assert len(assessment["claims"]) == 1
    claim = assessment["claims"][0]
    assert claim["supporting_fragment_indices"] == (1,)
    assert claim["cited_citation_indices"] == (2,)
    assert claim["citation_supported"] is True
    assert assessment["covered_reference_fact_indices"] == (1,)


def test_compute_claim_metrics_supported_and_cited_fractions() -> None:
    claims = [
        {
            "supported": True,
            "cited_citation_indices": (1,),
            "citation_supported": True,
        },
        {"supported": True, "cited_citation_indices": (), "citation_supported": False},
        {"supported": False, "cited_citation_indices": (2,), "citation_supported": True},
    ]

    metrics = compute_claim_metrics(
        claims,
        reference_fact_count=4,
        covered_reference_fact_indices=[1, 3],
    )

    assert metrics["total_claims"] == 3
    assert metrics["supported_claims"] == 2
    assert metrics["cited_supported_claims"] == 1
    assert metrics["faithfulness"] == pytest.approx(2 / 3)
    assert metrics["citation_coverage"] == pytest.approx(1 / 3)
    assert metrics["reference_fact_coverage"] == pytest.approx(0.5)


def test_compute_claim_metrics_vacuous_and_empty_policies() -> None:
    vacuous = compute_claim_metrics([], vacuous=True)
    assert vacuous["faithfulness"] == 1.0
    assert vacuous["citation_coverage"] == 1.0

    unanswered = compute_claim_metrics([])
    assert unanswered["faithfulness"] == 0.0
    assert unanswered["citation_coverage"] == 0.0


def test_build_judge_prompt_numbers_every_evidence_kind() -> None:
    prompt = build_judge_prompt(
        question="问题？",
        answer="答案。",
        fragments=[_fragment(3), _fragment(7)],
        citations=[_citation(3)],
        reference_facts=("fact one", "fact two", "fact three"),
    )

    assert "问题？" in prompt
    assert "答案。" in prompt
    assert "[fragment 1]" in prompt and "[fragment 2]" in prompt
    assert "[citation 1]" in prompt
    assert "[fact 3]" in prompt
    assert JUDGE_JSON_SCHEMA_HINT in prompt
    assert "temperature" not in prompt  # judge controls sampling, not the prompt


def test_judge_answer_normalizes_claims_and_marks_refusals_vacuous() -> None:
    judge = FakeJudge(
        {
            "claims": [
                {
                    "claim": "O(nlogn)",
                    "supported": True,
                    "supporting_fragment_indices": [1, 99],
                    "cited_citation_indices": [1],
                    "citation_supported": True,
                }
            ],
            "covered_reference_fact_indices": [1],
        }
    )

    result = judge_answer(
        judge,
        question="复杂度？",
        answer="O(nlogn)。",
        fragments=[_fragment(3)],
        citations=[_citation(3)],
        reference_facts=("fact",),
    )

    assert result["vacuous"] is False
    assert result["claims"][0]["supporting_fragment_indices"] == (1,)
    assert result["metrics"]["faithfulness"] == 1.0
    assert result["metrics"]["citation_coverage"] == 1.0
    assert result["metrics"]["reference_fact_coverage"] == 1.0

    refusal = judge_answer(
        FakeJudge({"claims": []}),
        question="复杂问题？",
        answer=NO_EVIDENCE_ANSWER,
        fragments=[],
        citations=[],
    )
    assert refusal["vacuous"] is True
    assert refusal["metrics"]["faithfulness"] == 1.0


def test_llm_claim_judge_uses_temperature_zero_and_parses_fenced_json() -> None:
    payload = {"claims": [{"claim": "supported", "supported": True}]}
    content = "评估如下：\n```json\n" + json.dumps(payload) + "\n```"
    client = FakeChatClient(content)
    judge = LLMClaimJudge(
        client=client,
        settings=SimpleNamespace(llm_model="fake-model"),
        model="judge-model",
    )

    result = judge.assess(
        question="问题？",
        answer="答案。",
        fragments=[_fragment(3)],
        citations=[_citation(3)],
    )

    assert result == payload
    call = client.completions.calls[0]
    assert call["model"] == "judge-model"
    assert call["temperature"] == 0.0
    assert call["messages"][0]["role"] == "system"
    assert "evaluation judge" in call["messages"][0]["content"]
