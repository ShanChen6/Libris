"""Viết lại câu hỏi đời thường bằng thuật ngữ pháp lý trước khi tìm kiếm.

Người hỏi nói "nghỉ ngang", "con trai 19 tuổi", "phạt tiền đi trễ"; văn bản viết "đơn phương chấm
dứt hợp đồng lao động trái pháp luật", "nam từ đủ 20 tuổi", "phạt tiền, cắt lương thay việc xử lý
kỷ luật lao động". Khi khác biệt từ ngữ quá lớn, đoạn đúng không lọt vào 20 ứng viên nên reranker
không có cơ hội xếp nó lên (GD-041, GD-053, GD-063). Bảng ánh xạ thuật ngữ (``expansion.py``) chỉ
vá được từng cụm đã biết; ở đây nhờ LLM viết lại thành truy vấn pháp lý, rồi tìm bằng **cả câu gốc
lẫn câu viết lại** và gộp ứng viên. Câu viết lại chỉ dùng để tìm, không đưa vào câu trả lời.

Kết quả đánh giá (``eval/README.md``, vòng 3): không cải thiện so với tìm bằng câu gốc, các câu mục
tiêu vẫn trượt, mỗi câu tốn thêm một lần gọi LLM -> **không bật trong API**; chỉ dùng qua cấu hình
đánh giá ``hybrid_kw1_rerank20_rewrite``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from app.generation.llm import LLMClient, LLMError, Message

log = logging.getLogger(__name__)

PROMPT = """Chuyển câu hỏi pháp luật của người dân thành MỘT truy vấn tìm kiếm ngắn (tối đa 30 từ) \
dùng đúng thuật ngữ của văn bản quy phạm pháp luật Việt Nam: nêu hành vi/quan hệ pháp lý và khái \
niệm chính. VD "chủ nhà đòi lấy lại nhà trước hạn thì sao" -> "bên cho thuê đơn phương chấm dứt \
hợp đồng thuê nhà ở trước thời hạn". Không trả lời câu hỏi, không nêu số Điều, số hiệu văn bản \
hay con số không có trong câu hỏi. Chỉ trả về truy vấn, không giải thích.

Câu hỏi: {question}"""


class QueryRewriter:
    """Gọi LLM viết lại câu hỏi; lỗi LLM -> None (vẫn tìm bằng câu gốc). ``cache_path``: lưu kết
    quả ra tệp JSON (dùng khi đánh giá để không gọi lại LLM)."""

    def __init__(self, llm: LLMClient, cache_path: Path | None = None) -> None:
        self.llm = llm
        self.cache_path = cache_path
        self.cache: dict[str, str] = {}
        if cache_path and cache_path.exists():
            self.cache = json.loads(cache_path.read_text(encoding="utf-8"))

    @staticmethod
    def _key(question: str) -> str:
        return hashlib.sha1(question.strip().encode()).hexdigest()

    def __call__(self, question: str) -> str | None:
        key = self._key(question)
        if key in self.cache:
            return self.cache[key] or None
        try:
            text = self.llm.complete(
                [Message("user", PROMPT.format(question=question.strip()))], max_tokens=120
            ).text
        except LLMError as exc:
            log.warning("Không viết lại được câu hỏi: %s", exc)
            return None
        rewritten = clean(text)
        self.cache[key] = rewritten or ""
        if self.cache_path:
            self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0))
        return rewritten


def clean(text: str) -> str | None:
    """Dòng đầu, bỏ ngoặc kép/tiền tố "Truy vấn:"; quá dài hoặc rỗng -> None."""
    line = next((s.strip() for s in text.strip().splitlines() if s.strip()), "")
    line = re.sub(r"^(?:truy vấn|query)\s*:\s*", "", line, flags=re.I).strip(" \"'“”*")
    if not line or len(line.split()) > 45:
        return None
    return line
