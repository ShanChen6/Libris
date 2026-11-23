"""POST /analyze/stream – tóm tắt hợp đồng và cảnh báo rủi ro pháp lý (Task 4.4)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import psycopg
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.analysis.contract import (
    AnalysisError,
    ContractAnalysis,
    Issue,
    Quote,
    analyze_contract,
    extract_upload,
)
from app.api.answer import LLMDep, sse
from app.api.search import EmbedderDep, RerankerDep, SettingsDep
from app.generation.llm import LLMError
from app.retrieval.hybrid import FusedHit
from crawler.extract import SUPPORTED_EXTENSIONS

log = logging.getLogger(__name__)
router = APIRouter(tags=["analyze"])


class QuoteOut(BaseModel):
    text: str
    start: int | None  # vị trí (code point) trong `text` của kết quả; None = chưa xác minh
    end: int | None


class KeyTermOut(BaseModel):
    topic: str
    content: str
    quote: QuoteOut | None


class LegalCitationOut(BaseModel):
    label: str
    start: int  # vị trí thẻ trong `verdict`
    end: int
    chunk_id: str
    document_id: str | None
    document_number: str
    document_title: str
    status: str
    article: str | None
    clause: str | None
    point: str | None
    char_start: int
    char_end: int
    superseded_by: list[str]


class IssueOut(BaseModel):
    id: int
    title: str
    severity: str  # high | medium | low | unclear
    concern: str
    affected_party: str | None
    quote: QuoteOut | None
    verdict: str
    recommendation: str
    grounded: bool
    citations: list[LegalCitationOut]
    # Các đoạn luật tìm được cho điểm này (label = nhãn trích dẫn; start/end = 0)
    related: list[LegalCitationOut]
    warnings: list[str]


class AnalysisOut(BaseModel):
    document_type: str
    parties: list[dict[str, str]]
    summary: str
    key_terms: list[KeyTermOut]
    issues: list[IssueOut]
    text: str
    truncated: bool
    warnings: list[str]
    disclaimer: str
    model: str | None
    usage: dict[str, int]
    timings: dict[str, float]


def _quote(q: Quote | None) -> QuoteOut | None:
    return QuoteOut(text=q.text, start=q.start, end=q.end) if q else None


def _legal(hit: FusedHit, label: str, start: int = 0, end: int = 0) -> LegalCitationOut:
    return LegalCitationOut(
        label=label,
        start=start,
        end=end,
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        document_number=hit.document_number,
        document_title=hit.document_title,
        status=hit.status,
        article=hit.article,
        clause=hit.clause,
        point=hit.point,
        char_start=hit.char_start,
        char_end=hit.char_end,
        superseded_by=hit.superseded_by,
    )


def _issue(i: Issue) -> IssueOut:
    return IssueOut(
        id=i.id,
        title=i.title,
        severity=i.severity,
        concern=i.concern,
        affected_party=i.affected_party,
        quote=_quote(i.quote),
        verdict=i.verdict,
        recommendation=i.recommendation,
        grounded=i.grounded,
        citations=[_legal(c.hit, c.label, c.start, c.end) for c in i.citations if c.hit],
        related=[_legal(h, h.citation) for h in i.hits],
        warnings=i.warnings,
    )


def to_out(a: ContractAnalysis) -> AnalysisOut:
    return AnalysisOut(
        document_type=a.document_type,
        parties=a.parties,
        summary=a.summary,
        key_terms=[
            KeyTermOut(topic=t.topic, content=t.content, quote=_quote(t.quote)) for t in a.key_terms
        ],
        issues=[_issue(i) for i in a.issues],
        text=a.text,
        truncated=a.truncated,
        warnings=a.warnings,
        disclaimer=a.disclaimer,
        model=a.model,
        usage=a.usage,
        timings=a.timings,
    )


@router.post("/analyze/stream")
async def analyze_stream(
    settings: SettingsDep,
    embedder: EmbedderDep,
    reranker: RerankerDep,
    llm: LLMDep,
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form(max_length=200_000)] = None,
) -> StreamingResponse:
    """Nhận một file (.pdf/.doc/.docx) HOẶC văn bản dán vào; trả luồng SSE:

    - ``progress``: ``{step, message}`` – read_file, read, retrieve, assess
    - ``done``: kết quả phân tích (xem ``AnalysisOut``)
    - ``error``: ``{message}``

    Lỗi đầu vào phát hiện được ngay (thiếu dữ liệu, sai định dạng, file quá lớn) trả HTTP 422/413.
    Văn bản không được lưu lại.
    """
    if (file is None) == (not text or not text.strip()):
        raise HTTPException(422, "Gửi một file hoặc nội dung văn bản (không gửi cả hai)")
    data, filename = b"", ""
    if file is not None:
        filename = file.filename or "upload"
        if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise HTTPException(422, f"Chỉ nhận file {', '.join(SUPPORTED_EXTENSIONS)}")
        limit = settings.analysis_max_upload_mb * 1024 * 1024
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"File vượt quá {settings.analysis_max_upload_mb} MB")
        if not data:
            raise HTTPException(422, "File rỗng")

    def events() -> Iterator[str]:
        try:
            content = text or ""
            if data:
                yield sse("progress", {"step": "read_file", "message": "Đang đọc file…"})
                content, stats = extract_upload(data, filename)
                if stats["ocr_pages"]:
                    yield sse("progress", {
                        "step": "read_file",
                        "message": f"Đã nhận dạng chữ (OCR) {stats['ocr_pages']} trang bản scan",
                    })  # fmt: skip
            with psycopg.connect(settings.database_url) as conn:
                for kind, payload in analyze_contract(
                    conn, content, embedder=embedder, reranker=reranker, llm=llm,
                    max_chars=settings.analysis_max_chars,
                    max_issues=settings.analysis_max_issues,
                    passages_per_issue=settings.analysis_passages_per_issue,
                    candidates=settings.rerank_candidates,
                    min_rerank_score=settings.answer_min_rerank_score,
                ):  # fmt: skip
                    yield sse(kind, to_out(payload) if kind == "done" else payload)
        except AnalysisError as exc:
            yield sse("error", {"message": str(exc)})
        except LLMError:
            log.exception("LLM lỗi khi phân tích văn bản")
            yield sse(
                "error", {"message": "Dịch vụ LLM tạm thời không khả dụng, vui lòng thử lại sau"}
            )
        except Exception as exc:  # noqa: BLE001 – luồng đã mở: báo lỗi bằng sự kiện
            log.exception("Lỗi khi phân tích văn bản")
            yield sse("error", {"message": f"Lỗi xử lý văn bản: {type(exc).__name__}"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
