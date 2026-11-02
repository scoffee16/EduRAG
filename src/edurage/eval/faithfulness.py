"""Claim-level faithfulness and citation-coverage metrics for RAG answers.

Definitions (mirrored in ``docs/ed-04-evaluation.md``)
------------------------------------------------------
The generation-layer evaluation asks an LLM judge to split an answer into
atomic factual claims and to check every claim against the *retrieved
fragments* and the *citations returned to the user*:

* ``faithfulness`` = supported claims / total claims.  A claim is supported
  only when at least one retrieved fragment directly supports it.  Claims that
  come from the model's general knowledge are not supported by definition.
* ``citation_coverage`` = cited-and-supported claims / total claims.  A claim
  counts only when it is supported, the answer references at least one concrete
  citation index (1-based index into the returned citation list), and the judge
  confirms the cited chunk text supports the claim.  A supported claim without
  a citation does not count.
* ``reference_fact_coverage`` = covered reference facts / reference facts.  It
  is an auxiliary recall signal for the annotated bullet facts, not a
  faithfulness measure.

Vacuous-answer policy
---------------------
When the answer is the deterministic no-evidence refusal
(``NO_EVIDENCE_ANSWER``) or no claims could be extracted from an answer that
had no retrieved fragments, the answer is scored ``1.0`` for both metrics.
This matches the existing empty-retrieval convention for citation page
accuracy in ``scripts/evaluate_retrieval.py`` (empty retrieval -> 1.0).  A
normal answer without extracted claims scores ``0.0`` instead, so a judge
failure cannot silently inflate the numbers.

The judge must return JSON; markdown fences and surrounding prose are tolerated
by :func:`extract_json_object`.  The live judge always runs with
``temperature=0`` and is injected as a :class:`ClaimJudge` protocol object, so
offline tests never touch the network.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from edurage.core.config import Settings, get_settings
from edurage.llm.client import create_chat_completion, get_llm_client
from edurage.rag.prompt import NO_EVIDENCE_ANSWER

JUDGE_SYSTEM_PROMPT = (
    "You are an evaluation judge for a retrieval-augmented question answering system. "
    "Your job is to decompose an answer into atomic factual claims and to decide whether "
    "each claim is supported by the retrieved course-material fragments. "
    "Be strict and literal: only content that is explicitly present in the fragments counts "
    "as support. Do not use your own background knowledge to fill gaps. "
    "Return a single JSON object and no markdown fence and no extra prose."
)

JUDGE_JSON_SCHEMA_HINT = (
    '{"claims": [{"claim": str, "supported": bool, '
    '"supporting_fragment_indices": [int], "cited_citation_indices": [int], '
    '"citation_supported": bool, "reason": str}], '
    '"covered_reference_fact_indices": [int]}'
)

_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_DIGITS_PATTERN = re.compile(r"\d+")


def response_text(response: Any) -> str:
    """Extract the assistant message text from an OpenAI-compatible response."""

    if isinstance(response, Mapping):
        choices = response.get("choices") or []
    else:
        choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    first = choices[0]
    message = first.get("message") if isinstance(first, Mapping) else getattr(first, "message", None)
    if message is None:
        return ""
    if isinstance(message, Mapping):
        content = message.get("content")
    else:
        content = getattr(message, "content", None)
    return str(content or "")


def extract_json_object(
    text: str,
    *,
    required_keys: Sequence[str] = (),
) -> dict[str, Any]:
    """Return the first JSON object embedded in a judge response.

    The response may be pure JSON, JSON wrapped in a markdown fence, or JSON
    surrounded by prose.  Candidates are scanned in order and the first decodable
    object that contains at least one ``required_keys`` entry is returned; when
    ``required_keys`` is empty the first decodable object wins.
    """

    raw = (text or "").strip()
    if not raw:
        raise ValueError("judge response is empty")
    candidates = [raw]
    candidates.extend(match.group(1).strip() for match in _FENCE_PATTERN.finditer(raw))
    decoder = json.JSONDecoder()
    for candidate in candidates:
        index = candidate.find("{")
        while index != -1:
            try:
                payload, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and (
                not required_keys or any(key in payload for key in required_keys)
            ):
                return payload
            index = candidate.find("{", index + 1)
    raise ValueError(f"judge response does not contain the expected JSON object: {raw[:200]}")


def _coerce_int_list(value: Any) -> tuple[int, ...]:
    if value is None:
        return ()
    items: list[Any]
    if isinstance(value, bool):
        return ()
    if isinstance(value, int):
        items = [value]
    elif isinstance(value, str):
        items = [int(match) for match in _DIGITS_PATTERN.findall(value)]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = []
        for item in value:
            if isinstance(item, bool):
                continue
            if isinstance(item, int):
                items.append(item)
            elif isinstance(item, str):
                items.extend(int(match) for match in _DIGITS_PATTERN.findall(item))
    else:
        return ()
    return tuple(dict.fromkeys(items))


def _bounded_indices(value: Any, upper: int) -> tuple[int, ...]:
    return tuple(index for index in _coerce_int_list(value) if 1 <= index <= upper)


def normalize_assessment(
    payload: Mapping[str, Any],
    *,
    fragment_count: int,
    citation_count: int,
    reference_fact_count: int = 0,
) -> dict[str, Any]:
    """Coerce a raw judge payload into a validated assessment mapping."""

    claims: list[dict[str, Any]] = []
    for item in payload.get("claims") or ():
        if not isinstance(item, Mapping):
            continue
        claim_text = str(item.get("claim") or item.get("text") or "").strip()
        if not claim_text:
            continue
        supporting = _bounded_indices(
            item.get("supporting_fragment_indices", item.get("supporting_fragments")),
            fragment_count,
        )
        cited = _bounded_indices(
            item.get("cited_citation_indices", item.get("citation_indices")),
            citation_count,
        )
        citation_supported = bool(
            item.get("citation_supported", item.get("citation_support", False))
        ) and bool(cited)
        claims.append(
            {
                "claim": claim_text,
                "supported": bool(item.get("supported", False)),
                "supporting_fragment_indices": supporting,
                "cited_citation_indices": cited,
                "citation_supported": citation_supported,
                "reason": str(item.get("reason") or ""),
            }
        )
    covered = _bounded_indices(
        payload.get("covered_reference_fact_indices"), reference_fact_count
    )
    return {"claims": tuple(claims), "covered_reference_fact_indices": covered}


def compute_claim_metrics(
    claims: Sequence[Mapping[str, Any]],
    *,
    reference_fact_count: int = 0,
    covered_reference_fact_indices: Sequence[int] = (),
    vacuous: bool = False,
) -> dict[str, float]:
    """Compute faithfulness / citation coverage for one judged answer."""

    total = len(claims)
    covered = set(covered_reference_fact_indices)
    reference_fact_coverage = (
        len(covered) / reference_fact_count if reference_fact_count else 0.0
    )
    if total == 0:
        score = 1.0 if vacuous else 0.0
        return {
            "total_claims": 0,
            "supported_claims": 0,
            "cited_supported_claims": 0,
            "faithfulness": score,
            "citation_coverage": score,
            "reference_fact_coverage": reference_fact_coverage,
        }
    supported = [claim for claim in claims if claim.get("supported")]
    cited_supported = [
        claim
        for claim in supported
        if claim.get("cited_citation_indices") and claim.get("citation_supported")
    ]
    return {
        "total_claims": total,
        "supported_claims": len(supported),
        "cited_supported_claims": len(cited_supported),
        "faithfulness": len(supported) / total,
        "citation_coverage": len(cited_supported) / total,
        "reference_fact_coverage": reference_fact_coverage,
    }


def aggregate_claim_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Average per-answer claim metrics into one aggregate row."""

    count = len(rows)
    keys = ("faithfulness", "citation_coverage", "reference_fact_coverage")
    if count == 0:
        return {"n": 0, **{key: 0.0 for key in keys}}
    return {
        "n": count,
        **{key: sum(float(row.get(key, 0.0)) for row in rows) / count for key in keys},
        "total_claims": sum(int(row.get("total_claims", 0)) for row in rows),
        "supported_claims": sum(int(row.get("supported_claims", 0)) for row in rows),
    }


def build_judge_prompt(
    *,
    question: str,
    answer: str,
    fragments: Sequence[Mapping[str, Any]],
    citations: Sequence[Mapping[str, Any]],
    reference_facts: Sequence[str] = (),
) -> str:
    """Render the judge user prompt for one answer.

    Fragments are numbered exactly like the answerer prompt (``[片段 i]``).
    Citations are numbered by their 1-based position in the returned citation
    list, which is the citation index used by ``citation_coverage``.
    """

    fragment_lines: list[str] = []
    for index, hit in enumerate(fragments, start=1):
        payload = hit.get("payload") or {}
        text = str(payload.get("snippet") or payload.get("text") or "").strip()
        fragment_lines.append(
            f"[fragment {index}] page={payload.get('page')} "
            f"filename={payload.get('filename')}\n{text[:900]}"
        )
    citation_lines: list[str] = []
    for index, citation in enumerate(citations, start=1):
        snippet = str(citation.get("snippet") or "").strip()
        citation_lines.append(
            f"[citation {index}] page={citation.get('page')} "
            f"filename={citation.get('filename')}\n{snippet}"
        )
    fact_lines = [f"[fact {index}] {fact}" for index, fact in enumerate(reference_facts, start=1)]
    return (
        f"Question:\n{question}\n\n"
        "Retrieved fragments (numbered, these are the only allowed evidence):\n"
        f"{chr(10).join(fragment_lines) or '(none)'}\n\n"
        "Citations returned to the user (numbered):\n"
        f"{chr(10).join(citation_lines) or '(none)'}\n\n"
        "Reference facts (numbered, used only for the auxiliary coverage field):\n"
        f"{chr(10).join(fact_lines) or '(none)'}\n\n"
        f"Answer:\n{answer}\n\n"
        "Instructions:\n"
        "1. Split the answer into atomic factual claims. Ignore greetings, headings, "
        "source notices and filler. Keep every claim short and self-contained.\n"
        "2. Set supported=true only when at least one retrieved fragment explicitly supports "
        "the claim; otherwise set supported=false.\n"
        "3. If the answer cites a page for a claim, map that page to the numbered citations "
        "and list the citation indices in cited_citation_indices (empty list when the answer "
        "cites nothing for that claim). Set citation_supported=true only when every cited "
        "citation snippet actually supports the claim; otherwise false.\n"
        "4. supporting_fragment_indices lists the fragment indices that support the claim "
        "(empty list when none do).\n"
        "5. covered_reference_fact_indices lists the reference fact indices that the answer "
        "states or correctly implies.\n"
        "6. If the answer is a no-evidence refusal, return empty claim and fact lists.\n"
        "Respond with exactly one JSON object of this shape (no markdown fence, no prose):\n"
        f"{JUDGE_JSON_SCHEMA_HINT}"
    )


class ClaimJudge(Protocol):
    """Injectable judge boundary used by the offline tests and the live script."""

    def assess(
        self,
        *,
        question: str,
        answer: str,
        fragments: Sequence[Mapping[str, Any]],
        citations: Sequence[Mapping[str, Any]],
        reference_facts: Sequence[str] = (),
    ) -> Mapping[str, Any]: ...


class LLMClaimJudge:
    """Live LLM judge (DeepSeek-compatible chat completion at temperature 0)."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        settings: Settings | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client if client is not None else get_llm_client(self.settings)
        self.model = model or self.settings.llm_model
        self.temperature = temperature

    def assess(
        self,
        *,
        question: str,
        answer: str,
        fragments: Sequence[Mapping[str, Any]],
        citations: Sequence[Mapping[str, Any]],
        reference_facts: Sequence[str] = (),
    ) -> dict[str, Any]:
        prompt = build_judge_prompt(
            question=question,
            answer=answer,
            fragments=fragments,
            citations=citations,
            reference_facts=reference_facts,
        )
        response = create_chat_completion(
            self.client,
            model=self.model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature,
        )
        return extract_json_object(response_text(response), required_keys=("claims",))


def judge_answer(
    judge: ClaimJudge,
    *,
    question: str,
    answer: str,
    fragments: Sequence[Mapping[str, Any]],
    citations: Sequence[Mapping[str, Any]],
    reference_facts: Sequence[str] = (),
) -> dict[str, Any]:
    """Judge one answer and compute its faithfulness / citation metrics."""

    payload = judge.assess(
        question=question,
        answer=answer,
        fragments=fragments,
        citations=citations,
        reference_facts=reference_facts,
    )
    assessment = normalize_assessment(
        payload,
        fragment_count=len(fragments),
        citation_count=len(citations),
        reference_fact_count=len(reference_facts),
    )
    claims = assessment["claims"]
    refusal = NO_EVIDENCE_ANSWER in (answer or "")
    vacuous = refusal or (not claims and not fragments)
    metrics = compute_claim_metrics(
        claims,
        reference_fact_count=len(reference_facts),
        covered_reference_fact_indices=assessment["covered_reference_fact_indices"],
        vacuous=vacuous,
    )
    return {
        "claims": [dict(claim) for claim in claims],
        "covered_reference_fact_indices": list(
            assessment["covered_reference_fact_indices"]
        ),
        "vacuous": vacuous,
        "metrics": metrics,
    }
