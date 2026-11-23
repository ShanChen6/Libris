"""Mở rộng truy vấn: cụm từ đời thường -> thuật ngữ trong văn bản pháp luật.

Người dùng hỏi "vượt đèn đỏ", "sổ đỏ", "bằng lái"... trong khi văn bản viết "không chấp hành hiệu
lệnh của đèn tín hiệu giao thông", "giấy chứng nhận quyền sử dụng đất", "giấy phép lái xe". Thuật
ngữ tương ứng được nối thêm vào câu truy vấn trước khi tìm (cả vector và từ khóa).

Bổ sung cặp mới khi bộ Golden Dataset (Task 5.1) phát hiện câu hỏi trượt vì khác cách diễn đạt.
"""

from __future__ import annotations

import re

from app.pipeline.vn import fz

SYNONYMS: dict[str, str] = {
    "vượt đèn đỏ": "không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
    "vượt đèn vàng": "không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
    "xe máy": "xe mô tô xe gắn máy",
    "bằng lái": "giấy phép lái xe",
    "say rượu": "nồng độ cồn",
    "uống rượu": "nồng độ cồn",
    "rượu bia": "nồng độ cồn",
    "nhậu": "nồng độ cồn",
    "mũ bảo hiểm": "đội mũ bảo hiểm cho người đi mô tô xe máy",
    "đi ngược chiều": "đi ngược chiều của đường một chiều",
    "chạy quá tốc độ": "điều khiển xe chạy quá tốc độ quy định",
    "sổ đỏ": "giấy chứng nhận quyền sử dụng đất",
    "sổ hồng": "giấy chứng nhận quyền sử dụng đất quyền sở hữu nhà ở",
    "thu hồi đất": "thu hồi đất bồi thường hỗ trợ tái định cư",
    "đền bù": "bồi thường",
    "lấy vợ": "kết hôn",
    "lấy chồng": "kết hôn",
    "cưới": "kết hôn",
    "bỏ vợ": "ly hôn",
    "bỏ chồng": "ly hôn",
    "nuôi con": "trông nom chăm sóc nuôi dưỡng giáo dục con cấp dưỡng",
    "nghỉ đẻ": "nghỉ thai sản",
    "nghỉ sinh": "nghỉ thai sản",
    "đuổi việc": "đơn phương chấm dứt hợp đồng lao động sa thải",
    "nghỉ việc": "đơn phương chấm dứt hợp đồng lao động",
    "tăng ca": "làm thêm giờ",
    "lương tối thiểu": "mức lương tối thiểu",
    "sếp": "người sử dụng lao động",
}

_PATTERNS = [(re.compile(r"(?<!\w)" + fz(k) + r"(?!\w)"), v) for k, v in SYNONYMS.items()]


def expand_query(query: str) -> str:
    """Câu truy vấn kèm thuật ngữ pháp lý tương ứng (nếu có); giữ nguyên câu gốc ở đầu."""
    extra: list[str] = []
    for pattern, terms in _PATTERNS:
        if pattern.search(query) and terms not in extra and terms.lower() not in query.lower():
            extra.append(terms)
    return f"{query} ({'; '.join(extra)})" if extra else query
