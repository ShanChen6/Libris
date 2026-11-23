"""POST /search – Hybrid Search có lọc hiệu lực (Task 3.1, 3.2)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.pipeline.embedding import Embedder, get_embedder
from app.retrieval.expansion import expand_query
from app.retrieval.hybrid import SearchWeights, hybrid_search
from app.retrieval.router import route

router = APIRouter(tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=20, ge=1, le=100)
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


class SearchResponse(BaseModel):
    query: str
    expanded_query: str
    plan: PlanOut
    hits: list[HitOut]


SettingsDep = Annotated[Settings, Depends(get_settings)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]


@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest, settings: SettingsDep, embedder: EmbedderDep) -> SearchResponse:
    plan = route(req.query)
    if req.as_of:
        plan.mode, plan.period = "point_in_time", (req.as_of, req.as_of)
        plan.reasons.append(f"Theo yêu cầu: văn bản có hiệu lực tại {req.as_of.isoformat()}")
    if req.include_expired is not None:
        statuses = {"ACTIVE", "AMENDED"} | ({"EXPIRED"} if req.include_expired else set())
        plan.statuses = tuple(s for s in ("ACTIVE", "AMENDED", "EXPIRED") if s in statuses)
        plan.reasons.append(f"Theo yêu cầu: include_expired={req.include_expired}")

    # Router phân tích câu gốc; tìm kiếm dùng câu đã nối thêm thuật ngữ pháp lý
    expanded = expand_query(req.query)
    query_vector = embedder.encode([expanded])[0]
    with psycopg.connect(settings.database_url) as conn:
        result = hybrid_search(
            conn, expanded, query_vector, top_k=req.top_k, plan=plan, weights=req.weights
        )
    return SearchResponse(
        query=req.query,
        expanded_query=expanded,
        plan=PlanOut(
            mode=result.plan.mode,
            statuses=list(result.plan.statuses),
            period=result.plan.period,
            referenced=result.plan.referenced,
            reasons=result.plan.reasons,
        ),
        hits=[HitOut(citation=h.citation, **vars(h)) for h in result.hits],
    )
