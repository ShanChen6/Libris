"""POST /answer – trả lời câu hỏi pháp luật có trích dẫn đã xác minh (Task 3.4)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from datetime import date
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.search import EmbedderDep, HitOut, PlanOut, RerankerDep, SettingsDep
from app.cache.semantic import SemanticCache, corpus_version, get_cache
from app.generation.answer import AnswerResult, answer_question, stream_answer
from app.generation.llm import LLMClient, LLMError, get_llm
from app.retrieval.service import make_plan

log = logging.getLogger(__name__)
router = APIRouter(tags=["answer"])
LLMDep = Annotated[LLMClient, Depends(get_llm)]
CacheDep = Annotated[SemanticCache | None, Depends(get_cache)]


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
    document_id: str | None


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
    cached: bool = False  # lấy từ Semantic Cache (Task 5.3)


def _citations(res: AnswerResult) -> list[CitationOut]:
    return [
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
            document_id=c.hit.document_id,
        )
        for c in res.citations
        if c.hit is not None
    ]


def _plan(plan) -> PlanOut:
    return PlanOut(
        mode=plan.mode,
        statuses=list(plan.statuses),
        period=plan.period,
        referenced=plan.referenced,
        reasons=plan.reasons,
    )


def _sources(hits) -> list[HitOut]:
    return [HitOut(citation=h.citation, **vars(h)) for h in hits]


def to_response(res: AnswerResult) -> AnswerResponse:
    return AnswerResponse(
        question=res.question,
        answer=res.answer,
        refused=res.refused,
        refusal_reason=res.refusal_reason,
        citations=_citations(res),
        warnings=res.warnings,
        plan=_plan(res.plan),
        sources=_sources(res.hits),
        model=res.model,
        usage=res.usage,
        timings=res.timings,
    )


def _options(settings) -> dict:
    return {
        "candidates": settings.rerank_candidates,
        "top_n": settings.rerank_top_n,
        "min_rerank_score": settings.answer_min_rerank_score,
    }


class _Cache:
    """Tra / ghi Semantic Cache cho một câu hỏi; ``cache`` None thì không làm gì."""

    def __init__(self, cache: SemanticCache | None, req: AnswerRequest, embedder, conn) -> None:
        self.cache, self.req = cache, req
        if cache is not None:
            self.vector = embedder.encode([req.question])[0]
            self.scope = cache.scope(
                req.include_expired, req.as_of, date.today(), corpus_version(conn)
            )

    def lookup(self) -> AnswerResponse | None:
        if self.cache is None:
            return None
        started = time.perf_counter()
        hit = self.cache.lookup(self.req.question, self.vector, self.scope)
        if hit is None:
            return None
        log.info("Cache: '%s' ~ '%s' (%.3f)", self.req.question, hit.question, hit.similarity)
        res = AnswerResponse(**hit.payload)
        res.question = self.req.question
        res.cached = True
        res.usage = {}
        res.timings = {"cache": time.perf_counter() - started}
        return res

    def store(self, res: AnswerResponse) -> None:
        # Không lưu lời từ chối: lần hỏi sau vẫn có cơ hội trả lời (VD LLM chỉ lỗi tạm thời)
        if self.cache is not None and not res.refused:
            self.cache.store(
                self.req.question, self.vector, self.scope, res.model_dump(mode="json")
            )


@router.post("/answer", response_model=AnswerResponse)
def answer(
    req: AnswerRequest,
    settings: SettingsDep,
    embedder: EmbedderDep,
    reranker: RerankerDep,
    llm: LLMDep,
    cache: CacheDep,
) -> AnswerResponse:
    plan = make_plan(req.question, include_expired=req.include_expired, as_of=req.as_of)
    try:
        with psycopg.connect(settings.database_url) as conn:
            cached = _Cache(cache, req, embedder, conn)
            if (hit := cached.lookup()) is not None:
                return hit
            res = answer_question(
                conn, req.question, embedder=embedder, reranker=reranker, llm=llm, plan=plan,
                **_options(settings),
            )  # fmt: skip
    except LLMError as exc:
        raise HTTPException(
            status_code=503, detail=f"Dịch vụ LLM tạm thời không khả dụng: {exc}"
        ) from exc
    out = to_response(res)
    cached.store(out)
    return out


def _meta(prep) -> dict[str, Any]:
    return {
        "plan": _plan(prep.plan).model_dump(mode="json"),
        "sources": [src.model_dump(mode="json") for src in _sources(prep.hits)],
    }


def sse(event: str, data: Any) -> str:
    """Một sự kiện Server-Sent Events; ``data`` là JSON một dòng."""
    payload = data.model_dump_json() if isinstance(data, BaseModel) else json.dumps(
        data, ensure_ascii=False, default=str
    )  # fmt: skip
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/answer/stream")
def answer_stream(
    req: AnswerRequest,
    settings: SettingsDep,
    embedder: EmbedderDep,
    reranker: RerankerDep,
    llm: LLMDep,
    cache: CacheDep,
) -> StreamingResponse:
    """Như POST /answer nhưng trả về luồng SSE (Task 4.2):

    - ``meta``: ``{plan, sources}`` ngay sau bước truy xuất
    - ``delta``: ``{text}`` từng mẩu câu trả lời
    - ``done``: toàn bộ kết quả như POST /answer – bản chính thức, client thay nội dung đã hiển thị
      bằng ``answer`` ở đây (có thể thêm cảnh báo hiệu lực hoặc thành lời từ chối)
    - ``error``: ``{message}``
    """
    plan = make_plan(req.question, include_expired=req.include_expired, as_of=req.as_of)

    def events() -> Iterator[str]:
        try:
            with psycopg.connect(settings.database_url) as conn:
                cached = _Cache(cache, req, embedder, conn)
                if (hit := cached.lookup()) is not None:
                    # Trúng cache: gửi ngay toàn bộ câu trả lời, cùng thứ tự sự kiện như bình thường
                    sources = [src.model_dump(mode="json") for src in hit.sources]
                    yield sse(
                        "meta", {"plan": hit.plan.model_dump(mode="json"), "sources": sources}
                    )
                    yield sse("delta", {"text": hit.answer})
                    yield sse("done", hit)
                    return
                for kind, payload in stream_answer(
                    conn, req.question, embedder=embedder, reranker=reranker, llm=llm, plan=plan,
                    **_options(settings),
                ):  # fmt: skip
                    if kind == "meta":
                        yield sse("meta", _meta(payload))
                    elif kind == "delta":
                        yield sse("delta", {"text": payload})
                    elif kind == "done":
                        out = to_response(payload)
                        cached.store(out)
                        yield sse("done", out)
                    else:
                        yield sse("error", payload)
        except Exception as exc:  # noqa: BLE001 – luồng đã mở: báo lỗi bằng sự kiện, không bằng HTTP
            log.exception("Lỗi khi stream câu trả lời")
            yield sse("error", {"message": f"Lỗi xử lý câu hỏi: {type(exc).__name__}"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # Không để proxy (nginx...) gom luồng lại rồi mới gửi
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
