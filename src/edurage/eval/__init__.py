"""Evaluation primitives shared by the ED-04 real-corpus evaluation pipeline."""

from edurage.eval.faithfulness import (
    JUDGE_SYSTEM_PROMPT,
    ClaimJudge,
    LLMClaimJudge,
    aggregate_claim_metrics,
    build_judge_prompt,
    compute_claim_metrics,
    extract_json_object,
    judge_answer,
    normalize_assessment,
    response_text,
)
from edurage.eval.retrieval_metrics import (
    aggregate_retrieval_scores,
    page_key,
    score_retrieval_question,
)

__all__ = [
    "JUDGE_SYSTEM_PROMPT",
    "ClaimJudge",
    "LLMClaimJudge",
    "aggregate_claim_metrics",
    "aggregate_retrieval_scores",
    "build_judge_prompt",
    "compute_claim_metrics",
    "extract_json_object",
    "judge_answer",
    "normalize_assessment",
    "page_key",
    "response_text",
    "score_retrieval_question",
]
