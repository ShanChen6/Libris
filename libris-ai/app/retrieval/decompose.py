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
# "Tôi muốn ly hôn và giành quyền nuôi con được không?": hai việc muốn làm, mỗi việc một căn cứ
# (GD-100). Chỉ tách khi có động từ tình thái đứng trước và phần hỏi đứng sau, để không tách nhầm
# "tuổi kết hôn của nam và nữ".
_MODAL_AND_RE = re.compile(
    r"^(?P<pre>.*?\b(?:"
    + "|".join(fz(w) for w in ["muốn", "định", "có thể", "được phép", "có quyền"])
    + r"))\s+(?P<a>\S.+?)\s+"
    + fz("và")
    + r"\s+(?P<b>\S.+?)"
    r"(?P<post>\s*(?:"
    + "|".join(fz(w) for w in ["được không", "không", "thế nào", "ra sao", "được chứ"])
    + r")\s*[?.!]*)$",
    re.IGNORECASE,
)
_LEAD_RE = re.compile(r"^(?:" + fz("và") + "|" + fz("còn") + "|" + fz("rồi") + r")\s+", re.I)
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

    # Bỏ từ nối ở đầu vế: "..., và trợ cấp thôi việc tính thế nào?" -> "trợ cấp thôi việc..."
    parts = [_LEAD_RE.sub("", p).strip() for p in _SPLIT_RE.split(q) if p.strip()]
    asks = [p for p in parts if _ASK_RE.search(p)]
    if len(asks) == 1 and (m := _MODAL_AND_RE.match(asks[0])):
        context = " ".join(p for p in parts if p not in asks)
        pre, post = m.group("pre").strip(), m.group("post").strip()
        return [" ".join(x for x in (context, pre, part, post) if x) for part in (m["a"], m["b"])]
    if len(asks) < 2:
        return [question]
    context = " ".join(p for p in parts if p not in asks)
    if not context:
        # "Chở 3 người bị phạt bao nhiêu? Có trường hợp nào được chở không?": vế sau cần vế đầu
        return [asks[0]] + [f"{asks[0]} {a}" for a in asks[1:]]
    return [f"{context} {a}".strip() for a in asks]
