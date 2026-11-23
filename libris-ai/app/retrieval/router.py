"""Task 3.2 – Query Router: xác định phạm vi hiệu lực văn bản cần tìm cho mỗi câu hỏi.

Quy tắc (theo thứ tự ưu tiên):

1. Mặc định ("current"): chỉ văn bản đang có hiệu lực (ACTIVE, AMENDED) – tránh tư vấn theo luật cũ.
2. Hỏi theo mốc thời gian ("point_in_time"): "vào năm 2019", "tại ngày 01/7/2024",
   "trước ngày 1/1/2025"... -> lọc văn bản có hiệu lực trong khoảng đó (theo ngày hiệu lực/hết hiệu
   lực), không theo trạng thái hiện tại.
3. So sánh / hỏi luật cũ ("compare"): "so sánh", "khác gì", "trước đây", "luật cũ", "đã hết hiệu
   lực"... -> mở rộng sang EXPIRED.
4. Nêu đích danh văn bản (số hiệu "100/2019/NĐ-CP", hoặc tên + năm "Luật Đất đai 2013") -> văn bản
   đó luôn được tìm (kể cả đã hết hiệu lực) và được ưu tiên trong xếp hạng.
5. Hỏi về quy định sắp có hiệu lực ("sắp", "sẽ có hiệu lực") -> thêm PENDING.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from app.pipeline.vn import fz

Mode = Literal["current", "compare", "point_in_time"]
IN_FORCE = ("ACTIVE", "AMENDED")

_NUMBER_RE = re.compile(
    r"\b(\d{1,4}/(?:19|20)\d{2}/[A-ZĐÐa-zđ][A-ZĐÐa-zđ0-9]*(?:-[A-ZĐÐa-zđ0-9]+)*)"
)
_KINDS = ["Bộ luật", "Luật", "Nghị định", "Thông tư", "Quyết định", "Nghị quyết", "Pháp lệnh"]
# "Luật Đất đai 2013", "Bộ luật Lao động năm 2012", "Nghị định 100 năm 2019"
_NAMED_YEAR_RE = re.compile(
    r"\b(" + "|".join(fz(k) for k in _KINDS) + r")\s+((?:[^\W\d]+\s+){0,6}?)"
    r"(?:" + fz("năm") + r"\s+)?((?:19|20)\d{2})\b"
)
_COMPARE_RE = re.compile(
    "|".join(
        fz(p)
        for p in [
            "so sánh", "khác gì", "khác nhau", "khác biệt", "thay đổi", "điểm mới", "trước đây",
            "trước kia", "luật cũ", "quy định cũ", "nghị định cũ", "bản cũ", "cũ và mới",
            "cũ so với", "hết hiệu lực", "bị thay thế", "bị bãi bỏ", "còn hiệu lực không",
            "còn áp dụng không",
        ]
    )
)  # fmt: skip
_PENDING_RE = re.compile("|".join(fz(p) for p in ["sắp có hiệu lực", "sẽ có hiệu lực", "sắp tới"]))
# Mốc thời gian: chỉ nhận khi có từ dẫn để không nhầm với năm trong số hiệu / tên văn bản
_DATE_CUE = r"(?:" + "|".join(
    fz(c) for c in ["vào", "tại thời điểm", "thời điểm", "lúc", "hồi", "trong", "trước", "sau"]
) + r")"  # fmt: skip
_FULL_DATE_RE = re.compile(
    r"(" + _DATE_CUE + r")\s+(?:" + fz("ngày") + r"\s+)?(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*"
    r"((?:19|20)\d{2})"
    r"|(" + _DATE_CUE + r")\s+" + fz("ngày") + r"\s+(\d{1,2})\s+" + fz("tháng") + r"\s+(\d{1,2})\s+"
    + fz("năm") + r"\s+((?:19|20)\d{2})"
)  # fmt: skip
_YEAR_RE = re.compile(r"(" + _DATE_CUE + r")\s+" + fz("năm") + r"\s+((?:19|20)\d{2})\b")
# "Năm 2023, ..." ở đầu câu / đầu vế: cũng là mốc thời gian (Golden Dataset GD-028, GD-088).
# Năm trong tên văn bản ("Luật Đất đai năm 2013") đã bị loại trước khi xét mốc thời gian.
_LEADING_YEAR_RE = re.compile(r"(?:^|[,;:.]\s*)(" + fz("năm") + r")\s+((?:19|20)\d{2})\b")


@dataclass
class RetrievalPlan:
    mode: Mode = "current"
    statuses: tuple[str, ...] = IN_FORCE
    # Lọc theo khoảng hiệu lực (point_in_time): văn bản có hiệu lực tại một thời điểm trong khoảng
    period: tuple[date, date] | None = None
    # Văn bản được nêu đích danh: luôn được tìm và được ưu tiên
    referenced: list[str] = field(default_factory=list)
    # Tên + năm chưa quy được về số hiệu (cần tra trong DB): [(loại, tên, năm)]
    named: list[tuple[str, str, int]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def normalize_number(number: str) -> str:
    return unicodedata.normalize("NFC", number).upper().replace("Ð", "Đ")


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _period(query: str) -> tuple[tuple[date, date], str] | None:
    m = _FULL_DATE_RE.search(query)
    if m:
        cue, d, mth, y = (m.group(1), m.group(2), m.group(3), m.group(4)) if m.group(1) else (
            m.group(5), m.group(6), m.group(7), m.group(8))  # fmt: skip
        day = _safe_date(int(y), int(mth), int(d))
        if day:
            return _range_for_cue(cue, day, day), m.group(0)
    m = _YEAR_RE.search(query) or _LEADING_YEAR_RE.search(query.strip())
    if m:
        y = int(m.group(2))
        return _range_for_cue(m.group(1), date(y, 1, 1), date(y, 12, 31)), m.group(0).strip(" ,;:.")
    return None


def _range_for_cue(cue: str, start: date, end: date) -> tuple[date, date]:
    """'trước ngày X' -> hôm trước X; 'sau ngày X' -> hôm sau X; còn lại -> [start, end]."""
    base = unicodedata.normalize("NFD", cue.lower())
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    if base == "truoc":
        before = date.fromordinal(start.toordinal() - 1)
        return before, before
    if base == "sau":
        after = date.fromordinal(end.toordinal() + 1)
        return after, after
    return start, end


_COMPARE_FILLER_RE = re.compile(
    r"(?:\b(?:" + "|".join(fz(p) for p in ["theo", "giữa", "của", "giữa các", "và"]) + r")\s+)?"
    + r"(?:" + "|".join(fz(p) for p in ["quy định", "luật", "nghị định"]) + r")?\s*"
    + r"(?:" + _COMPARE_RE.pattern + r")"
    + r"(?:\s+(?:" + "|".join(fz(p) for p in ["và mới", "với hiện nay", "hiện nay", "hiện hành",
                                              "và hiện hành", "so với"]) + r"))*"
)  # fmt: skip


def core_question(query: str) -> str:
    """Bỏ các cụm chỉ ý so sánh ("So sánh ...", "theo quy định cũ và mới"...) để tìm kiếm theo
    đúng nội dung được hỏi; các cụm này làm nhiễu cả vector lẫn reranker."""
    core = _COMPARE_FILLER_RE.sub(" ", query)
    core = re.sub(r"\s+", " ", core).strip(" ,.?")
    core = re.sub(r"\s+(?:" + fz("so với") + "|" + fz("với") + r")$", "", core)
    return core if len(core) >= 8 else query


def route(query: str) -> RetrievalPlan:
    plan = RetrievalPlan()
    statuses = set(IN_FORCE)

    numbers = [normalize_number(n) for n in _NUMBER_RE.findall(query)]
    if numbers:
        plan.referenced = list(dict.fromkeys(numbers))
        plan.reasons.append(f"Nêu đích danh văn bản: {', '.join(plan.referenced)}")

    scrubbed = _NUMBER_RE.sub(" ", query)
    for m in _NAMED_YEAR_RE.finditer(scrubbed):
        kind, name, year = m.group(1), " ".join(m.group(2).split()), int(m.group(3))
        plan.named.append((kind, name, year))
        plan.reasons.append(f"Nêu tên văn bản kèm năm: {m.group(0).strip()}")
    # Năm trong "Luật Đất đai 2013" là tên văn bản, không phải mốc thời gian
    scrubbed = _NAMED_YEAR_RE.sub(" ", scrubbed)

    if _COMPARE_RE.search(query):
        plan.mode = "compare"
        statuses.add("EXPIRED")
        plan.reasons.append("Câu hỏi so sánh / về quy định cũ: tìm cả văn bản hết hiệu lực")

    found = _period(scrubbed)
    if found:
        plan.period, text = found
        plan.mode = "point_in_time"
        plan.reasons.append(
            f"Hỏi theo mốc thời gian '{text.strip()}': văn bản có hiệu lực từ "
            f"{plan.period[0].isoformat()} đến {plan.period[1].isoformat()}"
        )

    if _PENDING_RE.search(query):
        statuses.add("PENDING")
        plan.reasons.append("Hỏi về quy định sắp có hiệu lực: tìm cả văn bản chưa có hiệu lực")

    order = ("ACTIVE", "AMENDED", "EXPIRED", "PENDING")
    plan.statuses = tuple(s for s in order if s in statuses)
    if not plan.reasons:
        plan.reasons.append("Mặc định: chỉ văn bản đang có hiệu lực")
    return plan
