"""Tách câu hỏi nhiều ý thành các câu hỏi con để truy xuất riêng từng ý.

Một lượt truy xuất cho cả câu "Đi xe máy vừa không đội mũ bảo hiểm vừa vượt đèn đỏ thì bị phạt những
khoản nào?" thường chỉ lấy được căn cứ cho một hành vi (Golden Dataset: câu nhiều căn cứ chỉ đúng
50%). Hai dạng được tách:

1. "vừa A vừa B" -> "... A ..." và "... B ..." (giữ phần đầu và phần cuối câu);
2. nhiều vế hỏi ("... có đúng luật không, công ty bị phạt thế nào?") -> mỗi vế hỏi kèm các câu bối
   cảnh không phải câu hỏi ("Công ty bắt tôi thử việc 90 ngày...").

Không tách được thì trả về một phần tử (chính câu hỏi).
"""

from __future__ import annotations

import re

from app.pipeline.vn import fz

_BOTH_RE = re.compile(
    r"^(?P<pre>.*?)\b" + fz("vừa") + r"\s+(?P<a>.+?)\s+" + fz("vừa") + r"\s+(?P<b>.+?)"
    r"(?P<post>\s+(?:" + fz("thì") + "|" + fz("sẽ") + r")\s+.*)?$",
    re.IGNORECASE,
)
# "vừa lái xe máy vừa cầm điện thoại" là MỘT hành vi (lái xe là hoạt động nền), không tách
_BACKGROUND_RE = re.compile(
    r"^(?:"
    + "|".join(fz(w) for w in ["lái", "đi", "chạy", "điều khiển", "làm việc", "đang"])
    + r")\b",
    re.IGNORECASE,
)
_ASK_RE = re.compile(
    r"\b(?:"
    + "|".join(
        fz(w)
        for w in [
            "bao nhiêu", "bao lâu", "thế nào", "ra sao", "khi nào", "ở đâu",
            "những gì", "là gì", "gì", "nào", "không", "được không", "chưa",
        ]
    )
    + r")\s*[?.!]*\s*$",
    re.IGNORECASE,
)  # fmt: skip
_SPLIT_RE = re.compile(r"(?<=[.?!;])\s+|,\s+")


def sub_questions(question: str) -> list[str]:
    q = " ".join(question.split())
    m = _BOTH_RE.match(q)
    if (
        m
        and len(m.group("a")) > 3
        and len(m.group("b")) > 3
        and not _BACKGROUND_RE.match(m.group("a"))
    ):
        pre, post = m.group("pre").strip(), (m.group("post") or "").strip()
        return [" ".join(p for p in (pre, part, post) if p) for part in (m["a"], m["b"])]

    parts = [p.strip() for p in _SPLIT_RE.split(q) if p.strip()]
    asks = [p for p in parts if _ASK_RE.search(p)]
    if len(asks) < 2:
        return [question]
    context = " ".join(p for p in parts if p not in asks)
    if not context:
        # "Chở 3 người bị phạt bao nhiêu? Có trường hợp nào được chở không?": vế sau cần vế đầu
        return [asks[0]] + [f"{asks[0]} {a}" for a in asks[1:]]
    return [f"{context} {a}".strip() for a in asks]
