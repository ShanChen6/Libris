"""Lớp 4 chống ảo giác: kiểm tra câu trả lời có áp dụng đúng Khoản/Điểm hay không.

Thẻ trích dẫn hợp lệ (``citations.py``) mới chỉ bảo đảm Điều/Khoản có trong ngữ cảnh. Lỗi còn lại
hay gặp là mô hình chọn nhầm giữa các Khoản gần giống nhau, chỉ khác ở con số, VD "chở theo 02
người" (Khoản 2) với "chở theo từ 03 người trở lên" (Khoản 3), hay nồng độ cồn "vượt quá 0,25 đến
0,4 miligam/1 lít khí thở" (Khoản 8) với "vượt quá 0,4 miligam" (Khoản 9). Sửa prompt chỉ làm
giảm tần suất; ở đây kiểm tra bằng luật cố định:

1. **Điều kiện**: con số có đơn vị trong câu hỏi (số người được chở, km/h, nồng độ cồn, tuổi) được
   đổi thành khoảng giá trị và đối chiếu với khoảng trong Khoản/Điểm được dẫn. Không giao nhau mà
   có đoạn khác trong ngữ cảnh khớp -> dẫn nhầm.
2. **Số tiền**: số tiền nêu trong câu (trước thẻ trích dẫn) phải có trong Khoản được dẫn; nếu
   không mà có đoạn khác chứa đủ -> dẫn nhầm.

Chỉ báo lỗi khi tìm được đoạn thay thế, nên không làm hỏng các câu trả lời không thuộc dạng này.
Phát hiện lỗi -> ``answer.py`` cho mô hình viết lại một lần với gợi ý cụ thể.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

from app.generation.citations import Citation, extract_citations
from app.retrieval.hybrid import FusedHit

_NUM = r"\d{1,3}(?:\.\d{3})+|\d+(?:,\d+)?"
_WORD_NUMBERS = {
    "một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5, "sáu": 6, "bảy": 7, "tám": 8, "chín": 9,
    "mười": 10,
}  # fmt: skip
_WNUM = rf"{_NUM}|{'|'.join(_WORD_NUMBERS)}"

_MG = r"mi\s*li\s*gam|mg"
_UNITS = {
    "mg/100ml máu": rf"(?:{_MG})\s*/\s*100\s*(?:mi\s*li\s*lít|ml)(?:\s*máu)?",
    "mg/l khí thở": rf"(?:{_MG})\s*/\s*(?:1\s*)?(?:lít|l\b)(?:\s*khí\s*thở)?",
    "km/h": r"km\s*(?:[^\w\s]|ủ){0,3}\s*(?:h|giờ)\b",
    "tuổi": r"tuổi\b",
}
_UNIT_RE = "|".join(f"(?P<u{i}>{p})" for i, p in enumerate(_UNITS.values()))
_UNIT_NAMES = list(_UNITS)
_PARTIAL_UNIT = rf"(?:{_MG}|km\S{{0,3}}h|tuổi)"
_ABOVE = r"vượt\s+quá|vượt|quá|trên|hơn"
_OP = rf"(?P<op>{_ABOVE}|từ|dưới|tối\s+đa)"

_RANGE_RE = re.compile(
    rf"(?:{_OP}\s+)?(?P<a>{_NUM})\s*(?:{_PARTIAL_UNIT}\s*)?"
    rf"(?P<to>đến\s+dưới|đến|tới|[-–—])\s*(?P<b>{_NUM})\s*(?:{_UNIT_RE})"
)
_SINGLE_RE = re.compile(rf"(?:{_OP}\s+)?(?P<a>{_NUM})\s*(?:{_UNIT_RE})(?P<up>\s*trở\s+lên)?")
_PEOPLE_RE = re.compile(
    rf"chở(?:\s+theo)?(?:\s+{_OP})?\s+(?P<a>{_WNUM})\s+người(?P<up>\s+trở\s+lên)?"
)
_MONEY_RE = re.compile(
    rf"(?P<a>{_NUM})(?:\s*(?:đến|[-–—])\s*(?P<b>{_NUM}))?\s*(?P<mul>triệu|tỷ|nghìn|ngàn|đồng)"
)
_MULTIPLIER = {"triệu": 1e6, "tỷ": 1e9, "nghìn": 1e3, "ngàn": 1e3, "đồng": 1}
_POINT_RE = re.compile(r"Điểm\s+([a-zđ])\b", re.IGNORECASE)
_STRAY_PUNCT_RE = re.compile(r"\s[.:;,¿°]\s")  # dấu chấm lạc do OCR: "vượt . quá 80"


@dataclass(frozen=True)
class Interval:
    unit: str
    lo: float
    hi: float
    lo_incl: bool = True
    hi_incl: bool = True
    text: str = ""

    def overlaps(self, other: Interval) -> bool:
        if self.unit != other.unit:
            return False
        lo, lo_incl = max((self.lo, self.lo_incl), (other.lo, other.lo_incl), key=_lo_key)
        hi, hi_incl = min((self.hi, self.hi_incl), (other.hi, other.hi_incl), key=_hi_key)
        return lo < hi or (lo == hi and lo_incl and hi_incl)


def _lo_key(bound: tuple[float, bool]) -> tuple[float, int]:
    return bound[0], 0 if bound[1] else 1  # cùng giá trị: cận mở chặt hơn


def _hi_key(bound: tuple[float, bool]) -> tuple[float, int]:
    return bound[0], 1 if bound[1] else 0


def _number(text: str) -> float:
    text = text.strip().lower()
    if text in _WORD_NUMBERS:
        return float(_WORD_NUMBERS[text])
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        return float(text.replace(".", ""))
    return float(text.replace(",", "."))


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = _STRAY_PUNCT_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text)


def _unit_of(m: re.Match) -> str:
    for i, name in enumerate(_UNIT_NAMES):
        if m.group(f"u{i}"):
            return name
    raise ValueError("không có đơn vị")


def _single(unit: str, a: float, op: str | None, up: bool, text: str) -> Interval:
    op = re.sub(r"\s+", " ", op or "")
    if up:
        return Interval(unit, a, math.inf, op != "trên", False, text)
    if op and re.fullmatch(_ABOVE, op):
        return Interval(unit, a, math.inf, False, False, text)
    if op == "dưới":
        return Interval(unit, -math.inf, a, False, False, text)
    if op == "tối đa":
        return Interval(unit, 0, a, True, True, text)
    return Interval(unit, a, a, True, True, text)


def conditions(text: str) -> list[Interval]:
    """Các điều kiện dạng con số + đơn vị trong một đoạn văn, dưới dạng khoảng giá trị."""
    text = _normalize(text)
    out: list[Interval] = []
    taken: list[tuple[int, int]] = []
    for m in _RANGE_RE.finditer(text):
        op = re.sub(r"\s+", " ", m.group("op") or "")
        lo_incl = not (op and re.fullmatch(_ABOVE, op))
        hi_incl = "dưới" not in m.group("to")
        unit = _unit_of(m)
        a, b = _number(m.group("a")), _number(m.group("b"))
        out.append(Interval(unit, a, b, lo_incl, hi_incl, m.group(0)))
        taken.append(m.span())
    for m in _SINGLE_RE.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        a = _number(m.group("a"))
        out.append(_single(_unit_of(m), a, m.group("op"), bool(m.group("up")), m.group(0)))
    for m in _PEOPLE_RE.finditer(text):
        a = _number(m.group("a"))
        out.append(_single("người chở theo", a, m.group("op"), bool(m.group("up")), m.group(0)))
    return out


def amounts(text: str) -> set[float]:
    """Số tiền trong đoạn văn (đồng); "18 – 20 triệu" -> {18e6, 20e6}."""
    out: set[float] = set()
    for m in _MONEY_RE.finditer(_normalize(text)):
        mul = _MULTIPLIER[m.group("mul")]
        values = [m.group("a")] + ([m.group("b")] if m.group("b") else [])
        for v in values:
            amount = _number(v) * mul
            if amount >= 1000:  # bỏ các số nhỏ trùng hợp đứng trước "đồng"
                out.add(amount)
    return out


def _point_text(hit: FusedHit, label: str) -> str:
    """Chỉ lấy dòng của Điểm được dẫn (nếu tìm được) thay vì cả Khoản."""
    m = _POINT_RE.search(label)
    if not m:
        return hit.content
    letter = m.group(1).lower()
    for line in hit.content.splitlines():
        if re.match(rf"\s*{letter}\)", line.lower()):
            return line
    return hit.content


def _location(hit: FusedHit) -> str:
    parts = [p for p in (hit.article, hit.clause) if p]
    return f"[{', '.join(parts)} - {hit.document_number}]"


def _same_clause(a: FusedHit, b: FusedHit) -> bool:
    return (a.document_number, a.article, a.clause) == (b.document_number, b.article, b.clause)


@dataclass
class Mismatch:
    citation: str  # thẻ trích dẫn trong câu trả lời
    reason: str  # mô tả cho mô hình và cho cảnh báo
    suggestion: str  # đoạn phù hợp hơn


def _short(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _check_conditions(
    question: str, citations: list[Citation], hits: list[FusedHit]
) -> list[Mismatch]:
    asked = conditions(question)
    if not asked:
        return []
    out: list[Mismatch] = []
    seen: set[str] = set()
    valid = [c for c in citations if c.hit is not None]
    cited_by = {c.label: conditions(_point_text(c.hit, c.label)) for c in valid}

    def contrasted(c: Citation, q: Interval) -> bool:
        """Câu trả lời đã dẫn một Khoản khác **cùng Điều** khớp điều kiện -> Khoản này chỉ được
        nêu để đối chiếu ("trên 80 miligam: 8–10 triệu [Khoản 9]; mức 50–80 thì [Khoản 8]"),
        không phải áp dụng nhầm (GD-026)."""
        return any(
            o.label != c.label
            and (o.hit.document_number, o.hit.article) == (c.hit.document_number, c.hit.article)
            and any(x.overlaps(q) for x in cited_by[o.label])
            for o in valid
        )

    for c in valid:
        if c.label in seen:
            continue
        seen.add(c.label)
        cited = cited_by[c.label]
        for q in asked:
            if contrasted(c, q):
                continue
            same_unit = [x for x in cited if x.unit == q.unit]
            if not same_unit or any(x.overlaps(q) for x in same_unit):
                continue
            alternatives = [
                (h, line)
                for h in hits
                if not _same_clause(h, c.hit)
                for line in h.content.splitlines()
                if any(x.overlaps(q) for x in conditions(line))
            ]
            if not alternatives:
                continue
            h, line = alternatives[0]
            out.append(
                Mismatch(
                    citation=c.label,
                    reason=(
                        f'câu hỏi nêu "{q.text}" nhưng {c.label} quy định '
                        f'"{same_unit[0].text}", không áp dụng cho trường hợp này'
                    ),
                    suggestion=f'{_location(h)}: "{_short(line)}"',
                )
            )
            break
    return out


def _check_amounts(answer: str, citations: list[Citation], hits: list[FusedHit]) -> list[Mismatch]:
    out: list[Mismatch] = []
    previous_end = 0
    for c in citations:
        if c.start <= previous_end:  # thẻ liền sau thẻ khác: cùng đoạn văn, đã xét
            previous_end = max(previous_end, c.end)
            continue
        line_start = answer.rfind("\n", 0, c.start) + 1
        segment = answer[max(previous_end, line_start) : c.start]
        previous_end = c.end
        stated = amounts(segment)
        if not stated or c.hit is None:
            continue
        # Khoản dài bị chia nhiều đoạn: mức phạt nằm ở đoạn đầu (hoặc ở tiền tố ngữ cảnh)
        clause_hits = [h for h in hits if _same_clause(h, c.hit)]
        available = set().union(*(amounts(h.content + " " + h.context_prefix) for h in clause_hits))
        if not available or stated <= available:
            continue
        better = [
            h
            for h in hits
            if not _same_clause(h, c.hit) and stated <= amounts(h.content + " " + h.context_prefix)
        ]
        if not better:
            continue
        money = ", ".join(f"{int(v):,}".replace(",", ".") for v in sorted(stated - available))
        out.append(
            Mismatch(
                citation=c.label,
                reason=f"{c.label} không có mức tiền {money} đồng nêu trong câu",
                suggestion=f'{_location(better[0])}: "{_short(better[0].content)}"',
            )
        )
    return out


def check_answer(question: str, answer: str, hits: list[FusedHit]) -> list[Mismatch]:
    citations = [c for c in extract_citations(answer, hits) if c.valid]
    return _check_conditions(question, citations, hits) + _check_amounts(answer, citations, hits)


def correction_prompt(mismatches: list[Mismatch]) -> str:
    lines = "\n".join(f"- {m.reason}. Đoạn phù hợp hơn: {m.suggestion}" for m in mismatches)
    return (
        "Kiểm tra tự động phát hiện câu trả lời trên có thể áp dụng nhầm Khoản/Điểm:\n"
        f"{lines}\n"
        "Hãy đối chiếu lại điều kiện trong câu hỏi với từng đoạn luật và viết lại TOÀN BỘ câu "
        "trả lời theo đúng các quy tắc ban đầu (chỉ đưa câu trả lời mới, không nhắc tới lần kiểm "
        "tra này). Nếu sau khi đối chiếu bạn vẫn thấy câu trả lời cũ là đúng thì giữ nguyên."
    )
