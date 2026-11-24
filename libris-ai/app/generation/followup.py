"""Câu hỏi nối tiếp trong hội thoại: "Xe máy vượt đèn đỏ bị phạt bao nhiêu?" -> "Còn ô tô thì sao?".

Câu nối tiếp tự nó không đủ nghĩa để tra luật, nên được ghép với câu hỏi trước đó (libris-api gửi
kèm lịch sử). Nhận diện bằng quy tắc, không tốn thêm lượt gọi LLM.
"""

from __future__ import annotations

import re

from app.pipeline.vn import fz

_STARTERS = ["còn", "thế còn", "vậy còn", "vậy thì", "vậy", "thế", "nếu", "còn nếu", "nhưng nếu",
             "trường hợp", "ngoài ra", "và"]  # fmt: skip
_REFERS = ["trường hợp đó", "trường hợp này", "trường hợp trên", "như vậy", "như trên",
           "điều đó", "điều này", "quy định đó", "quy định này", "mức đó", "mức này",
           "hành vi đó", "hành vi này", "luật đó", "luật này", "văn bản đó",
           "văn bản này"]  # fmt: skip
_START_RE = re.compile(r"^\W*(?:" + "|".join(fz(w) for w in _STARTERS) + r")\b", re.IGNORECASE)
_REFER_RE = re.compile(r"\b(?:" + "|".join(fz(w) for w in _REFERS) + r")\b", re.IGNORECASE)
_TAIL_RE = re.compile(fz("thì sao") + r"\W*$", re.IGNORECASE)


def is_follow_up(question: str) -> bool:
    q = question.strip()
    return bool(
        _START_RE.search(q) or _REFER_RE.search(q) or _TAIL_RE.search(q) or len(q.split()) <= 4
    )


def contextualize(question: str, history: list[str] | None) -> str:
    """Ghép câu hỏi nối tiếp với câu hỏi gần nhất trước đó; câu độc lập giữ nguyên."""
    previous = [h.strip() for h in history or [] if h.strip()]
    if not previous or not is_follow_up(question):
        return question
    return f"{previous[-1]} Hỏi tiếp: {question.strip()}"
