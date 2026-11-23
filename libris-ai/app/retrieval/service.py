"""Luồng truy xuất hoàn chỉnh dùng chung cho API, CLI, đánh giá và bước sinh câu trả lời.

câu hỏi -> Query Router (3.2) -> mở rộng thuật ngữ -> embedding -> Hybrid Search RRF (3.1)
        -> Cross-encoder rerank (3.3) -> Top N đoạn luật
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import psycopg

from app.pipeline.embedding import Embedder
from app.retrieval.expansion import expand_query
from app.retrieval.hybrid import FusedHit, SearchWeights, hybrid_search
from app.retrieval.rerank import Reranker, rerank
from app.retrieval.router import RetrievalPlan, route


@dataclass
class Retrieval:
    query: str
    expanded_query: str
    plan: RetrievalPlan
    hits: list[FusedHit]
    reranked: bool


def make_plan(
    query: str, *, include_expired: bool | None = None, as_of: date | None = None
) -> RetrievalPlan:
    """Kế hoạch của Router, có thể ghi đè từ giao diện (xem cả văn bản hết hiệu lực / theo ngày)."""
    plan = route(query)
    if as_of:
        plan.mode, plan.period = "point_in_time", (as_of, as_of)
        plan.reasons.append(f"Theo yêu cầu: văn bản có hiệu lực tại {as_of.isoformat()}")
    if include_expired is not None:
        wanted = {"ACTIVE", "AMENDED"} | ({"EXPIRED"} if include_expired else set())
        plan.statuses = tuple(s for s in ("ACTIVE", "AMENDED", "EXPIRED") if s in wanted)
        if include_expired and plan.mode == "current":
            plan.mode = "compare"
        plan.reasons.append(f"Theo yêu cầu: include_expired={include_expired}")
    return plan


def retrieve(
    conn: psycopg.Connection,
    query: str,
    embedder: Embedder,
    reranker: Reranker | None,
    *,
    candidates: int = 20,
    top_n: int = 5,
    plan: RetrievalPlan | None = None,
    weights: SearchWeights | None = None,
) -> Retrieval:
    plan = plan or route(query)
    # Router phân tích câu gốc; tìm kiếm và rerank dùng câu đã nối thuật ngữ pháp lý
    # (đo trên eval/retrieval_smoke.py: MRR 0,77 với câu gốc -> 0,87 với câu mở rộng)
    expanded = expand_query(query)
    result = hybrid_search(
        conn,
        expanded,
        embedder.encode([expanded])[0],
        top_k=candidates if reranker else top_n,
        plan=plan,
        weights=weights,
    )
    hits = result.hits
    if reranker is not None:
        hits = rerank(expanded, hits, reranker, top_n=top_n)
    return Retrieval(query, expanded, result.plan, hits[:top_n], reranker is not None)
