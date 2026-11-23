"""POST /search – Hybrid Search có lọc hiệu lực + rerank (Task 3.1, 3.2, 3.3)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.pipeline.embedding import Embedder, get_embedder
from app.retrieval.hybrid import SearchWeights
from app.retrieval.rerank import Reranker, get_reranker
from app.retrieval.service import make_plan, retrieve

router = APIRouter(tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    # Số đoạn trả về. Mặc định: RERANK_TOP_N (5) khi rerank, 20 khi không rerank
    top_n: int | None = Field(default=None, ge=1, le=100)
    rerank: bool = True
    # Số ứng viên Hybrid Search đưa vào reranker. Mặc định: RERANK_CANDIDATES
    candidates: int | None = Field(default=None, ge=1, le=100)
    # Ghi đè Query Router khi cần (VD: giao diện có nút "xem cả văn bản đã hết hiệu lực")
    include_expired: bool | None = None
    as_of: date | None = None
    weights: SearchWeights | None = None


class PlanOut(BaseModel):
    mode: Literal["current", "compare", "point_in_time"]
    statuses: list[str]
    period: tuple[date, date] | None
    referenced: list[str]
    reasons: list[str]


class HitOut(BaseModel):
    chunk_id: str
    citation: str
    document_number: str
    document_title: str
    status: str
    effective_date: date | None
    expiry_date: date | None
    replaced_by: list[str]
    superseded_by: list[str]
    article: str | None
    clause: str | None
    point: str | None
    context_prefix: str
    content: str
    char_start: int
    char_end: int
    score: float
    vec_rank: int | None
    kw_rank: int | None
    ref_rank: int | None
    rerank_score: float | None  # độ liên quan [0, 1] do cross-encoder chấm
    hybrid_rank: int | None  # thứ hạng trước khi rerank
    document_id: str | None = None


class SearchResponse(BaseModel):
    query: str
    expanded_query: str
    reranked: bool
    plan: PlanOut
    hits: list[HitOut]


SettingsDep = Annotated[Settings, Depends(get_settings)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
RerankerDep = Annotated[Reranker, Depends(get_reranker)]


@router.post("/search", response_model=SearchResponse)
def search(
    req: SearchRequest, settings: SettingsDep, embedder: EmbedderDep, reranker: RerankerDep
) -> SearchResponse:
    plan = make_plan(req.query, include_expired=req.include_expired, as_of=req.as_of)
    top_n = req.top_n or (settings.rerank_top_n if req.rerank else 20)
    with psycopg.connect(settings.database_url) as conn:
        result = retrieve(
            conn,
            req.query,
            embedder,
            reranker if req.rerank else None,
            candidates=max(req.candidates or settings.rerank_candidates, top_n),
            top_n=top_n,
            plan=plan,
            weights=req.weights,
        )
    return SearchResponse(
        query=result.query,
        expanded_query=result.expanded_query,
        reranked=result.reranked,
        plan=PlanOut(
            mode=result.plan.mode,
            statuses=list(result.plan.statuses),
            period=result.plan.period,
            referenced=result.plan.referenced,
            reasons=result.plan.reasons,
        ),
        hits=[HitOut(citation=h.citation, **vars(h)) for h in result.hits],
    )
