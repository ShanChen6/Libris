"""POST /answer – trả lời câu hỏi pháp luật có trích dẫn đã xác minh (Task 3.4)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.search import EmbedderDep, HitOut, PlanOut, RerankerDep, SettingsDep
from app.generation.answer import answer_question
from app.generation.llm import LLMClient, LLMError, get_llm
from app.retrieval.service import make_plan

router = APIRouter(tags=["answer"])
LLMDep = Annotated[LLMClient, Depends(get_llm)]


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    include_expired: bool | None = None
    as_of: date | None = None


class CitationOut(BaseModel):
    label: str  # nguyên văn thẻ trong câu trả lời
    start: int  # vị trí thẻ trong `answer`
    end: int
    chunk_id: str
    document_number: str
    document_title: str
    status: str
    article: str | None
    clause: str | None
    point: str | None
    # Vị trí đoạn luật trong nguyên văn văn bản – để bôi vàng (Task 4.3)
    char_start: int
    char_end: int
    superseded_by: list[str]


class AnswerResponse(BaseModel):
    question: str
    answer: str
    refused: bool
    refusal_reason: str | None
    citations: list[CitationOut]
    warnings: list[str]
    plan: PlanOut
    sources: list[HitOut]  # các đoạn luật đã đưa cho LLM
    model: str | None
    usage: dict[str, int]
    timings: dict[str, float]


@router.post("/answer", response_model=AnswerResponse)
def answer(
    req: AnswerRequest,
    settings: SettingsDep,
    embedder: EmbedderDep,
    reranker: RerankerDep,
    llm: LLMDep,
) -> AnswerResponse:
    plan = make_plan(req.question, include_expired=req.include_expired, as_of=req.as_of)
    try:
        with psycopg.connect(settings.database_url) as conn:
            res = answer_question(
                conn,
                req.question,
                embedder=embedder,
                reranker=reranker,
                llm=llm,
                plan=plan,
                candidates=settings.rerank_candidates,
                top_n=settings.rerank_top_n,
                min_rerank_score=settings.answer_min_rerank_score,
            )
    except LLMError as exc:
        raise HTTPException(
            status_code=503, detail=f"Dịch vụ LLM tạm thời không khả dụng: {exc}"
        ) from exc
    return AnswerResponse(
        question=res.question,
        answer=res.answer,
        refused=res.refused,
        refusal_reason=res.refusal_reason,
        citations=[
            CitationOut(
                label=c.label,
                start=c.start,
                end=c.end,
                chunk_id=c.hit.chunk_id,
                document_number=c.hit.document_number,
                document_title=c.hit.document_title,
                status=c.hit.status,
                article=c.hit.article,
                clause=c.hit.clause,
                point=c.hit.point,
                char_start=c.hit.char_start,
                char_end=c.hit.char_end,
                superseded_by=c.hit.superseded_by,
            )
            for c in res.citations
            if c.hit is not None
        ],
        warnings=res.warnings,
        plan=PlanOut(
            mode=res.plan.mode,
            statuses=list(res.plan.statuses),
            period=res.plan.period,
            referenced=res.plan.referenced,
            reasons=res.plan.reasons,
        ),
        sources=[HitOut(citation=h.citation, **vars(h)) for h in res.hits],
        model=res.model,
        usage=res.usage,
        timings=res.timings,
    )
