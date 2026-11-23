"""Sinh câu trả lời có trích dẫn, với ba lớp chống ảo giác (Task 3.4).

1. Trước khi gọi LLM: không có đoạn luật nào, hoặc đoạn liên quan nhất có điểm rerank dưới ngưỡng
   -> từ chối ngay (không tốn lượt gọi, không cho mô hình cơ hội tự suy diễn).
2. System prompt nghiêm ngặt (``prompt.py``): chỉ dùng tài liệu, trích dẫn sau mỗi luận điểm,
   tự từ chối khi thiếu căn cứ.
3. Sau khi LLM trả lời: đối chiếu từng thẻ trích dẫn với ngữ cảnh. Câu trả lời không có trích dẫn
   hợp lệ nào bị thay bằng lời từ chối; thẻ không khớp được báo trong ``warnings``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import psycopg

from app.generation.citations import Citation, extract_citations
from app.generation.llm import Completion, LLMClient
from app.generation.prompt import REFUSAL_MARKER, build_messages
from app.pipeline.embedding import Embedder
from app.retrieval.hybrid import FusedHit
from app.retrieval.rerank import Reranker
from app.retrieval.router import RetrievalPlan
from app.retrieval.service import retrieve

RefusalReason = Literal["no_results", "low_relevance", "model_refused", "ungrounded"]

REFUSAL_TEXT = (
    "Xin lỗi, Libris chưa tìm thấy điều luật đủ căn cứ trong kho dữ liệu để trả lời câu hỏi này. "
    "Để tránh tư vấn sai, Libris không suy đoán. Bạn nên tham vấn luật sư hoặc cơ quan có thẩm "
    "quyền để được hướng dẫn cụ thể."
)


@dataclass
class AnswerResult:
    question: str
    answer: str
    refused: bool
    refusal_reason: RefusalReason | None
    plan: RetrievalPlan
    hits: list[FusedHit]  # các đoạn luật đã đưa cho LLM (sau rerank)
    citations: list[Citation] = field(default_factory=list)  # chỉ các trích dẫn hợp lệ
    warnings: list[str] = field(default_factory=list)
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)


def _refusal(
    question: str,
    reason: RefusalReason,
    plan: RetrievalPlan,
    hits: list[FusedHit],
    detail: str | None = None,
    **kw,
) -> AnswerResult:
    text = REFUSAL_TEXT + (f"\n\nLý do: {detail}" if detail else "")
    return AnswerResult(question, text, True, reason, plan, hits, **kw)


def validity_notices(citations: list[Citation]) -> list[str]:
    """Một dòng cảnh báo cho mỗi Điều/văn bản được trích dẫn nhưng không còn hiệu lực."""
    notices: list[str] = []
    seen: set[tuple[str, str | None]] = set()
    for c in citations:
        h = c.hit
        if h is None or (h.document_number, h.article) in seen:
            continue
        seen.add((h.document_number, h.article))
        where = f"{h.article} {h.document_number}" if h.article else h.document_number
        if h.status == "EXPIRED":
            msg = f"{h.document_number} đã hết hiệu lực"
            if h.expiry_date:
                msg += f" từ ngày {h.expiry_date.strftime('%d/%m/%Y')}"
            if h.replaced_by:
                msg += f" và được thay thế bởi {', '.join(h.replaced_by)}"
            notices.append(msg + ".")
        elif h.superseded_by:
            sources = sorted({x.partition(":")[2] for x in h.superseded_by})
            kinds = {x.partition(":")[0] for x in h.superseded_by}
            action = "bãi bỏ" if kinds == {"repealed"} else "bãi bỏ hoặc sửa đổi"
            notices.append(
                f"{where} (hoặc một phần) đã bị {action} bởi {', '.join(sources)}; "
                "quy định này không còn được áp dụng."
            )
    return notices


def answer_question(
    conn: psycopg.Connection,
    question: str,
    *,
    embedder: Embedder,
    reranker: Reranker | None,
    llm: LLMClient,
    plan: RetrievalPlan | None = None,
    candidates: int = 20,
    top_n: int = 5,
    min_rerank_score: float = 0.2,
    today: date | None = None,
) -> AnswerResult:
    today = today or date.today()
    timings: dict[str, float] = {}

    started = time.monotonic()
    retrieval = retrieve(
        conn, question, embedder, reranker, candidates=candidates, top_n=top_n, plan=plan
    )
    timings["retrieval"] = time.monotonic() - started
    plan, hits = retrieval.plan, retrieval.hits

    # Lớp 1: chặn trước khi gọi LLM
    if not hits:
        return _refusal(question, "no_results", plan, hits, timings=timings)
    best = max((h.rerank_score or 0.0) for h in hits) if retrieval.reranked else None
    if best is not None and best < min_rerank_score:
        return _refusal(question, "low_relevance", plan, hits, timings=timings)
    if retrieval.reranked:
        # Bỏ các đoạn gần như không liên quan để LLM không bám vào
        hits = [h for h in hits if (h.rerank_score or 0.0) >= min_rerank_score / 2]

    # Lớp 2: LLM với system prompt nghiêm ngặt
    started = time.monotonic()
    completion: Completion = llm.complete(build_messages(question, hits, plan, today))
    timings["llm"] = time.monotonic() - started
    text = completion.text.strip()
    meta = {"model": completion.model, "usage": completion.usage, "timings": timings}

    if text.upper().startswith(REFUSAL_MARKER):
        detail = text[len(REFUSAL_MARKER) :].strip(" :\n") or None
        return _refusal(question, "model_refused", plan, hits, detail, **meta)

    # Lớp 3: xác minh trích dẫn
    citations = extract_citations(text, hits)
    valid = [c for c in citations if c.valid]
    invalid = [c for c in citations if not c.valid]
    if not valid:
        return _refusal(
            question,
            "ungrounded",
            plan,
            hits,
            warnings=["Câu trả lời của mô hình không có trích dẫn hợp lệ nên đã bị loại."],
            **meta,
        )
    warnings = [f"Trích dẫn {c.label} không khớp với đoạn luật nào đã cung cấp" for c in invalid]
    # Cảnh báo hiệu lực do hệ thống tự gắn (không phụ thuộc việc LLM có nhắc hay không)
    notices = validity_notices(valid)
    if notices:
        text += "\n\n" + "\n".join(f"⚠️ {n}" for n in notices)
    if any(c.hit and c.hit.superseded_by for c in valid) and plan.mode == "current":
        warnings.append("Có trích dẫn tới Điều/Khoản đã bị bãi bỏ hoặc sửa đổi.")
    return AnswerResult(question, text, False, None, plan, hits, valid, warnings, **meta)
