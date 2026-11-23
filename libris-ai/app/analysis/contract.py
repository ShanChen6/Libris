"""Task 4.4 – Tóm tắt hợp đồng và cảnh báo điều khoản bất lợi, có căn cứ pháp lý đã xác minh.

Luồng xử lý:

1. Đọc file (.pdf/.doc/.docx, OCR nếu là bản scan) hoặc văn bản dán vào.
2. LLM đọc hợp đồng (JSON): tóm tắt, điều khoản chính, các điểm cần kiểm tra kèm trích dẫn
   nguyên văn và một câu hỏi pháp lý cho mỗi điểm. Trích dẫn được dò lại trong văn bản gốc;
   không tìm thấy thì đánh dấu là chưa xác minh.
3. Mỗi câu hỏi pháp lý đi qua Hybrid Search + Rerank (chỉ quy định đang có hiệu lực); bỏ đoạn
   luật dưới ngưỡng liên quan.
4. LLM đánh giá từng điểm CHỈ dựa trên các đoạn luật tìm được (JSON). Thẻ trích dẫn được xác minh
   như câu trả lời hỏi đáp; điểm bị đánh giá nặng mà không có căn cứ hợp lệ được gắn cờ.

Hợp đồng không được lưu lại.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import psycopg

from app.analysis.prompt import DISCLAIMER, assess_messages, read_messages
from app.generation.answer import validity_notices
from app.generation.citations import Citation, extract_citations
from app.generation.llm import LLMClient, LLMError
from app.pipeline.embedding import Embedder
from app.retrieval.hybrid import FusedHit
from app.retrieval.rerank import Reranker
from app.retrieval.service import make_plan, retrieve

log = logging.getLogger(__name__)

SEVERITIES = ("high", "medium", "low", "unclear")
MIN_CHARS = 200  # ngắn hơn thì không đủ để phân tích


class AnalysisError(ValueError):
    """Lỗi do dữ liệu đầu vào hoặc mô hình trả về sai định dạng – báo lại cho người dùng."""


@dataclass
class Quote:
    text: str
    start: int | None = None  # vị trí (code point) trong văn bản; None = không tìm thấy nguyên văn
    end: int | None = None

    @property
    def verified(self) -> bool:
        return self.start is not None


@dataclass
class KeyTerm:
    topic: str
    content: str
    quote: Quote | None


@dataclass
class Issue:
    id: int
    title: str
    concern: str
    affected_party: str | None
    legal_query: str
    quote: Quote | None
    severity: str = "unclear"
    verdict: str = ""
    recommendation: str = ""
    citations: list[Citation] = field(default_factory=list)
    hits: list[FusedHit] = field(default_factory=list)  # đoạn luật tìm được cho điểm này
    grounded: bool = False  # có ít nhất một trích dẫn luật hợp lệ
    warnings: list[str] = field(default_factory=list)


@dataclass
class ContractAnalysis:
    document_type: str
    parties: list[dict[str, str]]
    summary: str
    key_terms: list[KeyTerm]
    issues: list[Issue]
    text: str  # nguyên văn đã đọc được – để hiển thị và bôi vàng trích dẫn
    truncated: bool
    warnings: list[str]
    disclaimer: str
    model: str | None
    usage: dict[str, int]
    timings: dict[str, float]


# ---------------------------------------------------------------------------- đọc văn bản


def extract_upload(data: bytes, filename: str, *, ocr: bool = True) -> tuple[str, dict[str, int]]:
    from crawler.clean import clean_text
    from crawler.extract import extract_document

    pages = extract_document(data, filename, ocr=ocr)
    text = clean_text("\n".join(p.text for p in pages))
    methods = [p.method for p in pages]
    return text, {"pages": len(pages), "ocr_pages": methods.count("ocr")}


# ------------------------------------------------------------------------------- tiện ích

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json(text: str) -> dict[str, Any]:
    """JSON của LLM: bỏ khối ```json```, lấy từ '{' đầu tiên đến '}' cuối cùng."""
    raw = _FENCE_RE.sub("", text.strip())
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise AnalysisError("Mô hình không trả về JSON")
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"JSON không hợp lệ: {exc}") from exc
    if not isinstance(data, dict):
        raise AnalysisError("JSON không phải một đối tượng")
    return data


def locate_quote(text: str, quote: str | None) -> Quote | None:
    """Tìm trích dẫn của LLM trong văn bản gốc, bỏ qua khác biệt khoảng trắng và hoa/thường."""
    if not isinstance(quote, str) or not quote.strip():
        return None
    q = quote.strip().strip("\"'“”«»")
    # LLM đôi khi rút gọn bằng "..." dù đã dặn: lấy đoạn dài nhất để dò
    segment = max(re.split(r"\s*(?:\.\.\.|…)\s*", q), key=len)
    words = segment.split()
    if not words:
        return Quote(q)
    pattern = r"\s+".join(re.escape(w) for w in words)
    m = re.search(pattern, text, re.IGNORECASE)
    return Quote(q, m.start(), m.end()) if m else Quote(q)


def _str(value: Any, default: str = "") -> str:
    return value.strip() if isinstance(value, str) else default


def _complete_json(llm: LLMClient, messages, *, max_tokens: int) -> tuple[dict[str, Any], Any]:
    """Gọi LLM ở chế độ JSON; sai định dạng thì thử lại một lần."""
    last: AnalysisError | None = None
    for _ in range(2):
        completion = llm.complete(messages, json_mode=True, max_tokens=max_tokens)
        try:
            return parse_json(completion.text), completion
        except AnalysisError as exc:
            log.warning("LLM trả về JSON lỗi: %s", exc)
            last = exc
    raise AnalysisError(f"Mô hình trả về dữ liệu không đúng định dạng ({last})")


def _add_usage(total: dict[str, int], usage: dict[str, Any]) -> None:
    for key, value in (usage or {}).items():
        if isinstance(value, int):
            total[key] = total.get(key, 0) + value


# -------------------------------------------------------------------------------- phân tích


def analyze_contract(
    conn: psycopg.Connection,
    text: str,
    *,
    embedder: Embedder,
    reranker: Reranker | None,
    llm: LLMClient,
    max_chars: int = 60_000,
    max_issues: int = 6,
    passages_per_issue: int = 3,
    candidates: int = 10,
    min_rerank_score: float = 0.2,
    today: date | None = None,
) -> Iterator[tuple[str, Any]]:
    """Sinh ``("progress", {step, message})`` trong lúc xử lý, cuối cùng ``("done",
    ContractAnalysis)``. Lỗi đầu vào hoặc định dạng: ``AnalysisError``."""
    today = today or date.today()
    text = text.strip()
    if len(text) < MIN_CHARS:
        raise AnalysisError(
            "Không đọc được đủ nội dung văn bản (file rỗng, bản scan quá mờ hoặc văn bản quá ngắn)"
        )
    timings: dict[str, float] = {}
    usage: dict[str, int] = {}
    warnings: list[str] = []
    truncated = len(text) > max_chars
    if truncated:
        warnings.append(
            f"Văn bản dài {len(text):,} ký tự; chỉ {max_chars:,} ký tự đầu được phân tích.".replace(
                ",", "."
            )
        )

    # 1. Đọc hợp đồng
    yield "progress", {"step": "read", "message": "Đang đọc và tóm tắt văn bản…"}
    started = time.monotonic()
    data, completion = _complete_json(
        llm, read_messages(text[:max_chars], max_issues), max_tokens=4096
    )
    timings["read"] = time.monotonic() - started
    _add_usage(usage, completion.usage)
    model = completion.model

    key_terms = [
        KeyTerm(_str(t.get("topic")), _str(t.get("content")), locate_quote(text, t.get("quote")))
        for t in data.get("key_terms") or []
        if isinstance(t, dict) and _str(t.get("topic"))
    ][:8]
    issues = [
        Issue(
            id=i,
            title=_str(raw.get("title"), "Vấn đề cần kiểm tra"),
            concern=_str(raw.get("concern")),
            affected_party=_str(raw.get("affected_party")) or None,
            legal_query=_str(raw.get("legal_query")) or _str(raw.get("title")),
            quote=locate_quote(text, raw.get("quote")),
        )
        for i, raw in enumerate(
            [r for r in data.get("issues") or [] if isinstance(r, dict)][:max_issues], 1
        )
    ]
    for issue in issues:
        if issue.quote and not issue.quote.verified:
            issue.warnings.append("Không tìm thấy nguyên văn đoạn trích này trong văn bản.")

    # 2. Tra luật cho từng điểm (chỉ quy định đang có hiệu lực)
    started = time.monotonic()
    for issue in issues:
        yield (
            "progress",
            {
                "step": "retrieve",
                "message": f"Đang tra cứu căn cứ pháp lý ({issue.id}/{len(issues)}): {issue.title}",
            },
        )
        plan = make_plan(issue.legal_query, include_expired=False)
        res = retrieve(
            conn, issue.legal_query, embedder, reranker,
            candidates=candidates, top_n=passages_per_issue, plan=plan,
        )  # fmt: skip
        issue.hits = [
            h for h in res.hits if h.rerank_score is None or h.rerank_score >= min_rerank_score
        ]
    timings["retrieve"] = time.monotonic() - started

    # 3. Đối chiếu với luật
    all_hits: list[FusedHit] = []
    index: dict[str, int] = {}
    for issue in issues:
        for h in issue.hits:
            if h.chunk_id not in index:
                all_hits.append(h)
                index[h.chunk_id] = len(all_hits)
    if issues and all_hits:
        yield "progress", {"step": "assess", "message": "Đang đối chiếu với quy định pháp luật…"}
        started = time.monotonic()
        raw_issues = [
            {
                "id": i.id,
                "title": i.title,
                "quote": i.quote.text if i.quote else None,
                "concern": i.concern,
                "legal_query": i.legal_query,
            }
            for i in issues
        ]
        passages = [[index[h.chunk_id] for h in i.hits] for i in issues]
        try:
            assessed, completion = _complete_json(
                llm, assess_messages(raw_issues, all_hits, passages, today), max_tokens=4096
            )
        except (LLMError, AnalysisError) as exc:
            # Không bỏ phí kết quả bước 1: vẫn trả tóm tắt, các điểm cần lưu ý và quy định liên
            # quan đã tìm được, chỉ thiếu phần đánh giá
            log.warning("Không đối chiếu được với luật: %s", exc)
            warnings.append(
                "Chưa đối chiếu được các điểm cần lưu ý với quy định pháp luật (dịch vụ LLM tạm "
                "thời không khả dụng). Các quy định liên quan vẫn được liệt kê; hãy thử lại sau."
            )
            for issue in issues:
                _apply_assessment(issue, None, all_hits, verdict=_NOT_ASSESSED)
        else:
            timings["assess"] = time.monotonic() - started
            _add_usage(usage, completion.usage)
            model = completion.model or model
            by_id = {
                a.get("id"): a for a in assessed.get("assessments") or [] if isinstance(a, dict)
            }
            for issue in issues:
                _apply_assessment(issue, by_id.get(issue.id), all_hits)
    else:
        for issue in issues:
            _apply_assessment(issue, None, all_hits)

    order = {s: i for i, s in enumerate(SEVERITIES)}
    issues.sort(key=lambda i: (order[i.severity], i.id))
    parties = [
        {"role": _str(p.get("role")), "name": _str(p.get("name"))}
        for p in data.get("parties") or []
        if isinstance(p, dict)
    ]
    yield (
        "done",
        ContractAnalysis(
            document_type=_str(data.get("document_type"), "Không xác định"),
            parties=parties,
            summary=_str(data.get("summary")),
            key_terms=key_terms,
            issues=issues,
            text=text,
            truncated=truncated,
            warnings=warnings,
            disclaimer=DISCLAIMER,
            model=model,
            usage=usage,
            timings=timings,
        ),
    )


_NO_BASIS = (
    "Chưa tìm thấy quy định liên quan trong kho dữ liệu của Libris để kết luận về điều khoản này."
)


_NOT_ASSESSED = "Chưa đánh giá được điều khoản này; xem các quy định liên quan bên dưới."


def _apply_assessment(
    issue: Issue, raw: dict | None, hits: list[FusedHit], *, verdict: str = _NO_BASIS
) -> None:
    if raw is None:
        issue.severity, issue.verdict = "unclear", verdict
        return
    severity = _str(raw.get("severity")).lower()
    issue.severity = severity if severity in SEVERITIES else "unclear"
    issue.verdict = _str(raw.get("verdict")) or _NO_BASIS
    issue.recommendation = _str(raw.get("recommendation"))
    found = extract_citations(issue.verdict, hits)
    issue.citations = [c for c in found if c.valid]
    issue.warnings += [
        f"Trích dẫn không khớp đoạn luật nào: {c.label}" for c in found if not c.valid
    ]
    issue.warnings += validity_notices(issue.citations)
    issue.grounded = bool(issue.citations)
    if not issue.grounded and issue.severity in ("high", "medium"):
        issue.warnings.append(
            "Đánh giá này chưa có căn cứ pháp lý được xác minh; nên tham khảo ý kiến luật sư."
        )
