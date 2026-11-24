"""Luồng truy xuất hoàn chỉnh dùng chung cho API, CLI, đánh giá và bước sinh câu trả lời.

câu hỏi -> Query Router (3.2) -> mở rộng thuật ngữ -> embedding -> Hybrid Search RRF (3.1)
        -> Cross-encoder rerank (3.3) -> Top N đoạn luật
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import psycopg

from app.pipeline.embedding import Embedder
from app.retrieval.decompose import sub_questions
from app.retrieval.expansion import expand_query
from app.retrieval.hybrid import FusedHit, SearchWeights, hybrid_search
from app.retrieval.rerank import Reranker, rerank
from app.retrieval.router import RetrievalPlan, core_question, route


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
    subs = sub_questions(query) if plan.mode != "compare" else [query]
    if len(subs) > 1 and reranker is not None:
        return _retrieve_parts(
            conn, query, subs, embedder, reranker, candidates=candidates, top_n=top_n,
            plan=plan, weights=weights,
        )  # fmt: skip
    # Router phân tích câu gốc; tìm kiếm và rerank dùng câu đã nối thuật ngữ pháp lý
    # (đo trên eval/retrieval_smoke.py: MRR 0,77 với câu gốc -> 0,87 với câu mở rộng)
    # Câu so sánh: tìm theo nội dung chính, bỏ các cụm "so sánh ... cũ và mới"
    expanded = expand_query(core_question(query) if plan.mode == "compare" else query)
    vector = embedder.encode([expanded])[0]
    result = hybrid_search(
        conn,
        expanded,
        vector,
        top_k=candidates if reranker else top_n,
        plan=plan,
        weights=weights,
    )
    hits = result.hits
    if plan.mode == "compare":
        # Lượt thứ hai chỉ trong quy định đang có hiệu lực: nếu chỉ tìm chung, đoạn luật cũ thường
        # khớp mạnh hơn và đẩy đoạn tương ứng của luật mới ra khỏi danh sách ứng viên.
        current = RetrievalPlan(referenced=list(plan.referenced), reasons=list(plan.reasons))
        newer = hybrid_search(
            conn, expanded, vector, top_k=candidates, plan=current, weights=weights
        ).hits
        seen = {h.chunk_id for h in hits}
        hits = hits + [h for h in newer if h.chunk_id not in seen]
    if reranker is not None:
        hits = rerank(expanded, hits, reranker, top_n=len(hits))
    if plan.mode == "compare":
        hits = balance_old_and_new(hits, top_n)
    return Retrieval(query, expanded, result.plan, hits[:top_n], reranker is not None)


def is_in_force(hit: FusedHit) -> bool:
    """Đoạn đang có hiệu lực: văn bản còn hiệu lực và Điều/Khoản chưa bị bãi bỏ, thay nội dung."""
    return hit.status in ("ACTIVE", "AMENDED") and not hit.superseded_by


def balance_old_and_new(hits: list[FusedHit], top_n: int) -> list[FusedHit]:
    """Câu hỏi so sánh cần cả quy định hiện hành lẫn quy định cũ trong ngữ cảnh.

    Giữ tối thiểu ⌈top_n/2⌉ đoạn mỗi nhóm (nếu có), phần còn lại theo thứ hạng, rồi trả về theo
    thứ hạng ban đầu. Nếu chỉ lấy theo điểm, Top 5 có thể toàn quy định cũ và LLM không có gì để
    so sánh.
    """
    quota = -(-top_n // 2)
    new = [h for h in hits if is_in_force(h)][:quota]
    old = [h for h in hits if not is_in_force(h)][:quota]
    chosen = {id(h) for h in new + old}
    for h in hits:
        if len(chosen) >= top_n:
            break
        chosen.add(id(h))
    picked = [h for h in hits if id(h) in chosen]
    return picked[:top_n]


def _retrieve_parts(
    conn: psycopg.Connection,
    query: str,
    subs: list[str],
    embedder: Embedder,
    reranker: Reranker,
    *,
    candidates: int,
    top_n: int,
    plan: RetrievalPlan,
    weights: SearchWeights | None,
) -> Retrieval:
    """Câu hỏi nhiều ý: truy xuất + rerank riêng từng câu hỏi con, mỗi ý giữ tối thiểu
    ⌊top_n / số ý⌋ chỗ trong Top N, phần còn lại theo điểm rerank."""
    ranked: list[list[FusedHit]] = []
    expanded_parts = []
    for sub in subs:
        expanded = expand_query(sub)
        expanded_parts.append(expanded)
        vector = embedder.encode([expanded])[0]
        hits = hybrid_search(
            conn, expanded, vector, top_k=candidates, plan=plan, weights=weights
        ).hits
        ranked.append(rerank(expanded, hits, reranker, top_n=len(hits)))
    quota = max(1, top_n // len(subs))
    chosen: dict[str, FusedHit] = {}
    for hits in ranked:
        for h in [h for h in hits if h.chunk_id not in chosen][:quota]:
            chosen[h.chunk_id] = h
    rest = sorted((h for hits in ranked for h in hits), key=lambda h: -(h.rerank_score or 0))
    for h in rest:
        if len(chosen) >= top_n:
            break
        chosen.setdefault(h.chunk_id, h)
    picked = sorted(chosen.values(), key=lambda h: -(h.rerank_score or 0))[:top_n]
    return Retrieval(query, " | ".join(expanded_parts), plan, picked, True)
