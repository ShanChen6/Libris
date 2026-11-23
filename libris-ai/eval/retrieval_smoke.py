"""Kiểm tra nhanh chất lượng truy xuất (Recall@k) trên dữ liệu thật.

    uv run python eval/retrieval_smoke.py            # cần DB đã nạp + embedding
    uv run python eval/retrieval_smoke.py -k 10

Mỗi ca: câu hỏi đời thường, văn bản + Điều chứa câu trả lời, và một cụm từ phải có trong đoạn.
Đây là bộ khởi đầu cho Golden Dataset (Task 5.1); kết quả dùng để so sánh khi chỉnh tham số.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.pipeline.embedding import get_embedder  # noqa: E402
from app.retrieval.expansion import expand_query  # noqa: E402
from app.retrieval.hybrid import hybrid_search  # noqa: E402
from app.retrieval.router import route  # noqa: E402

# (câu hỏi, số hiệu, Điều, cụm từ phải có trong đoạn)
CASES = [
    ("Đi xe máy không có gương chiếu hậu bên trái có bị phạt không?", "168/2024/NĐ-CP",
     "Điều 14", "gương chiếu hậu"),
    ("Vượt đèn đỏ bằng xe máy bị phạt bao nhiêu tiền?", "168/2024/NĐ-CP", "Điều 7",
     "đèn tín hiệu"),
    ("Không đội mũ bảo hiểm khi đi xe máy bị phạt bao nhiêu?", "168/2024/NĐ-CP", "Điều 7",
     "mũ bảo hiểm"),
    ("Điều khiển xe máy có nồng độ cồn bị phạt thế nào?", "168/2024/NĐ-CP", "Điều 7",
     "nồng độ cồn"),
    ("Nam nữ bao nhiêu tuổi thì được kết hôn?", "52/2014/QH13", "Điều 8", "20 tuổi"),
    ("Tài sản chung của vợ chồng gồm những gì?", "52/2014/QH13", "Điều 33", ""),
    ("Thời gian thử việc tối đa là bao lâu?", "45/2019/QH14", "Điều 25", ""),
    ("Người lao động được nghỉ thai sản bao lâu?", "45/2019/QH14", "Điều 139", ""),
    ("Hạn mức giao đất trồng cây hằng năm cho hộ gia đình", "31/2024/QH15", "Điều 176", ""),
    ("Thời hạn sử dụng đất nông nghiệp của cá nhân là bao lâu?", "31/2024/QH15", "Điều 172", ""),
]  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-k", type=int, default=20)
    args = parser.parse_args()
    embedder = get_embedder()
    found, rr = 0, 0.0
    with psycopg.connect(get_settings().database_url) as conn:
        for question, number, article, must in CASES:
            expanded = expand_query(question)
            res = hybrid_search(
                conn, expanded, embedder.encode([expanded])[0], top_k=args.k, plan=route(question)
            )
            rank = next(
                (
                    i
                    for i, h in enumerate(res.hits, 1)
                    if h.document_number == number
                    and h.article == article
                    and must.lower() in h.content.lower()
                ),
                None,
            )
            found += rank is not None
            rr += 1 / rank if rank else 0
            print(f"{str(rank or '-'):>4}  {article:9} {number:16} {question}")
    print(f"\nRecall@{args.k}: {found}/{len(CASES)}   MRR: {rr / len(CASES):.3f}")


if __name__ == "__main__":
    main()
