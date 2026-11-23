"""Sinh câu trả lời có trích dẫn, với ba lớp chống ảo giác (Task 3.4).

1. Trước khi gọi LLM: không có đoạn luật nào, hoặc đoạn liên quan nhất có điểm rerank dưới ngưỡng
   -> từ chối ngay (không tốn lượt gọi, không cho mô hình cơ hội tự suy diễn).
2. System prompt nghiêm ngặt (``prompt.py``): chỉ dùng tài liệu, trích dẫn sau mỗi luận điểm,
   tự từ chối khi thiếu căn cứ.
3. Sau khi LLM trả lời: đối chiếu từng thẻ trích dẫn với ngữ cảnh. Câu trả lời không có trích dẫn
   hợp lệ nào bị thay bằng lời từ chối; thẻ không khớp được báo trong ``warnings``.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import psycopg

from app.generation.citations import Citation, extract_citations
from app.generation.llm import Completion, LLMClient, LLMError
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


@dataclass
class Prepared:
    """Kết quả bước truy xuất; ``refusal`` khác None nghĩa là đã từ chối trước khi gọi LLM."""

    question: str
    plan: RetrievalPlan
    hits: list[FusedHit]
    today: date
    timings: dict[str, float]
    refusal: AnswerResult | None = None


def prepare(
    conn: psycopg.Connection,
    question: str,
    *,
    embedder: Embedder,
    reranker: Reranker | None,
    plan: RetrievalPlan | None = None,
    candidates: int = 20,
    top_n: int = 5,
    min_rerank_score: float = 0.2,
    today: date | None = None,
) -> Prepared:
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
        refusal = _refusal(question, "no_results", plan, hits, timings=timings)
        return Prepared(question, plan, hits, today, timings, refusal)
    best = max((h.rerank_score or 0.0) for h in hits) if retrieval.reranked else None
    if best is not None and best < min_rerank_score:
        refusal = _refusal(question, "low_relevance", plan, hits, timings=timings)
        return Prepared(question, plan, hits, today, timings, refusal)
    if retrieval.reranked:
        # Bỏ các đoạn gần như không liên quan để LLM không bám vào
        hits = [h for h in hits if (h.rerank_score or 0.0) >= min_rerank_score / 2]
    return Prepared(question, plan, hits, today, timings)


def messages_for(prep: Prepared) -> list:
    """Lớp 2: system prompt nghiêm ngặt + ngữ cảnh các đoạn luật."""
    return build_messages(prep.question, prep.hits, prep.plan, prep.today)


_DANGLING_RE = re.compile(r"\n\s*(?:[*•\-]|\d+\.)?\s*$")


def finalize(
    prep: Prepared,
    raw_text: str,
    model: str | None,
    usage: dict[str, int],
    finish_reason: str | None = None,
):
    """Lớp 3: nhận diện từ chối, xác minh trích dẫn, gắn cảnh báo hiệu lực."""
    question, plan, hits = prep.question, prep.plan, prep.hits
    text = raw_text.strip()
    truncated = finish_reason not in (None, "stop")
    if truncated:
        text = _DANGLING_RE.sub("", text)  # bỏ gạch đầu dòng dở dang ở cuối
    meta = {"model": model, "usage": usage, "timings": prep.timings}

    if is_refusal(text):
        detail = text[len(REFUSAL_MARKER) :].strip(" :\n") or None
        return _refusal(question, "model_refused", plan, hits, detail, **meta)

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
    if truncated:
        warnings.append(
            f"Câu trả lời có thể chưa đầy đủ: mô hình dừng sớm ({finish_reason}). "
            "Hãy xem trực tiếp các điều luật được trích dẫn."
        )
    if any(c.hit and c.hit.superseded_by for c in valid) and plan.mode == "current":
        warnings.append("Có trích dẫn tới Điều/Khoản đã bị bãi bỏ hoặc sửa đổi.")
    return AnswerResult(question, text, False, None, plan, hits, valid, warnings, **meta)


def is_refusal(text: str) -> bool:
    return text.lstrip().upper().startswith(REFUSAL_MARKER)


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
    prep = prepare(
        conn, question, embedder=embedder, reranker=reranker, plan=plan,
        candidates=candidates, top_n=top_n, min_rerank_score=min_rerank_score, today=today,
    )  # fmt: skip
    if prep.refusal:
        return prep.refusal
    started = time.monotonic()
    completion: Completion = llm.complete(messages_for(prep))
    prep.timings["llm"] = time.monotonic() - started
    return finalize(
        prep, completion.text, completion.model, completion.usage, _finish_reason_of(llm)
    )


StreamEvent = tuple[str, Any]


def stream_answer(
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
) -> Iterator[StreamEvent]:
    """Các sự kiện theo thứ tự: ``meta`` (kế hoạch + nguồn) → ``delta``* (từng mẩu chữ) →
    ``done`` (câu trả lời cuối cùng đã xác minh). Lỗi LLM: ``error``.

    Câu trả lời cuối trong ``done`` là bản chính thức: có thể khác các ``delta`` đã gửi (thêm cảnh
    báo hiệu lực, hoặc bị thay bằng lời từ chối khi không có trích dẫn hợp lệ).
    """
    prep = prepare(
        conn, question, embedder=embedder, reranker=reranker, plan=plan,
        candidates=candidates, top_n=top_n, min_rerank_score=min_rerank_score, today=today,
    )  # fmt: skip
    yield "meta", prep
    if prep.refusal:
        yield "done", prep.refusal
        return

    started = time.monotonic()
    parts: list[str] = []
    pending = ""  # giữ lại đầu câu trả lời cho tới khi biết đó có phải lời "TỪ CHỐI"
    decided = streaming = False
    try:
        for chunk in llm.stream(messages_for(prep)):
            if "first_token" not in prep.timings:
                prep.timings["first_token"] = time.monotonic() - started
            parts.append(chunk)
            if streaming:
                yield "delta", chunk
            elif not decided:
                pending += chunk
                head = pending.lstrip().upper()
                if len(head) >= len(REFUSAL_MARKER) or not REFUSAL_MARKER.startswith(head):
                    decided = True
                    # Lời từ chối: không phát ra giao diện, vẫn đọc hết để lấy lý do
                    streaming = not is_refusal(pending)
                    if streaming:
                        yield "delta", pending
    except LLMError as exc:
        yield "error", {"message": f"Dịch vụ LLM tạm thời không khả dụng: {exc}"}
        return
    if not decided and pending and not is_refusal(pending):
        yield "delta", pending  # câu trả lời ngắn hơn độ dài chữ "TỪ CHỐI"
    prep.timings["llm"] = time.monotonic() - started
    yield "done", finalize(prep, "".join(parts), _model_of(llm), {}, _finish_reason_of(llm))


def _finish_reason_of(llm: LLMClient) -> str | None:
    return getattr(llm, "last_finish_reason", None)


def _model_of(llm: LLMClient) -> str | None:
    """Mô hình đã thực sự phục vụ (có thể là mô hình dự phòng)."""
    return getattr(llm, "last_model", None)
