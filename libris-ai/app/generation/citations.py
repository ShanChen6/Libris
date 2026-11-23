"""Xác minh thẻ trích dẫn trong câu trả lời của LLM với các đoạn luật đã cung cấp.

Thẻ hợp lệ: [Điều X(, Khoản Y)(, Điểm z) - Số hiệu] mà văn bản + Điều (+ Khoản) khớp với một đoạn
trong ngữ cảnh. Thẻ không khớp là dấu hiệu ảo giác: được báo lại trong ``invalid``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.retrieval.hybrid import FusedHit

_TAG_RE = re.compile(r"\[([^\[\]]{1,300}?)\]")
_REF_RE = re.compile(
    r"^\s*(?P<loc>.*?)\s*[-–—]\s*(?P<num>\d{1,4}/(?:19|20)\d{2}/[A-Za-zĐđÐ0-9\-]+)\s*$"
)
_ARTICLE_RE = re.compile(r"Điều\s+(\d+[a-zđ]?)", re.IGNORECASE)
_CLAUSE_RE = re.compile(r"Khoản\s+(\d+[a-zđ]?)", re.IGNORECASE)


@dataclass
class Citation:
    label: str  # nguyên văn trong câu trả lời, VD "[Điều 7, Khoản 2 - 168/2024/NĐ-CP]"
    start: int  # vị trí trong câu trả lời
    end: int
    document_number: str
    article: str | None
    clause: str | None
    hit: FusedHit | None  # đoạn luật khớp; None = trích dẫn không có trong ngữ cảnh

    @property
    def valid(self) -> bool:
        return self.hit is not None


def _norm(number: str) -> str:
    return unicodedata.normalize("NFC", number).upper().replace("Ð", "Đ").strip()


def _num(label: str | None) -> str | None:
    return label.split()[-1].lower() if label else None


def _match(article: str | None, clause: str | None, number: str, hits: list[FusedHit]):
    candidates = [h for h in hits if _norm(h.document_number) == number]
    if article:
        candidates = [h for h in candidates if _num(h.article) == article]
    if clause:
        # Đoạn của cả Điều (clause None) cũng chứa Khoản được dẫn
        exact = [h for h in candidates if _num(h.clause) == clause]
        candidates = exact or [h for h in candidates if h.clause is None]
    return candidates[0] if candidates else None


def extract_citations(answer: str, hits: list[FusedHit]) -> list[Citation]:
    out: list[Citation] = []
    for m in _TAG_RE.finditer(answer):
        # Một thẻ có thể gộp nhiều căn cứ: [Điều 7 - A; Điều 8 - B]
        for part in m.group(1).split(";"):
            ref = _REF_RE.match(part)
            if not ref:
                continue
            loc, number = ref.group("loc"), _norm(ref.group("num"))
            art = _ARTICLE_RE.search(loc)
            cl = _CLAUSE_RE.search(loc)
            article = art.group(1).lower() if art else None
            clause = cl.group(1).lower() if cl else None
            out.append(
                Citation(
                    label=m.group(0),
                    start=m.start(),
                    end=m.end(),
                    document_number=number,
                    article=f"Điều {article}" if article else None,
                    clause=f"Khoản {clause}" if clause else None,
                    hit=_match(article, clause, number, hits),
                )
            )
    return out
