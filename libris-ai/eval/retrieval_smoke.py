"""Kiểm tra nhanh chất lượng truy xuất (Recall@k) trên dữ liệu thật.

    uv run python eval/retrieval_smoke.py            # cần DB đã nạp + embedding
    uv run python eval/retrieval_smoke.py -k 10

Mỗi ca: câu hỏi đời thường, văn bản + Điều chứa câu trả lời, và một cụm từ phải có trong đoạn.
Đây là bộ khởi đầu cho Golden Dataset (Task 5.1); kết quả dùng để so sánh khi chỉnh tham số.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.pipeline.embedding import get_embedder  # noqa: E402
from app.retrieval.expansion import expand_query  # noqa: E402
from app.retrieval.hybrid import hybrid_search  # noqa: E402
from app.retrieval.rerank import rerank  # noqa: E402
from app.retrieval.router import route  # noqa: E402
from app.retrieval.service import retrieve  # noqa: E402

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


def _rank(hits, number: str, article: str, must: str) -> int | None:
    return next(
        (
            i
            for i, h in enumerate(hits, 1)
            if h.document_number == number
            and h.article == article
            and must.lower() in h.content.lower()
        ),
        None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-k", type=int, default=20, help="số ứng viên từ Hybrid Search")
    parser.add_argument("--rerank", action="store_true", help="tái xếp hạng bằng cross-encoder")
    parser.add_argument(
        "--rerank-query", choices=["original", "expanded"], default="expanded",
        help="câu đưa cho reranker: câu hỏi gốc hay câu đã mở rộng thuật ngữ",
    )  # fmt: skip
    args = parser.parse_args()
    embedder = get_embedder()
    reranker = None
    if args.rerank:
        from app.retrieval.rerank import get_reranker

        reranker = get_reranker()
        reranker.score("khởi động", ["mô hình"])  # tải mô hình trước khi đo thời gian
    ranks: list[int | None] = []
    timings: list[float] = []
    with psycopg.connect(get_settings().database_url) as conn:
        for question, number, article, must in CASES:
            started = time.perf_counter()
            if reranker is not None and args.rerank_query == "original":
                expanded = expand_query(question)
                res = hybrid_search(
                    conn, expanded, embedder.encode([expanded])[0], top_k=args.k,
                    plan=route(question),
                )  # fmt: skip
                hits = rerank(question, res.hits, reranker, top_n=args.k)
            else:
                # Cấu hình chuẩn của hệ thống: retrieve() rerank bằng câu đã mở rộng
                hits = retrieve(
                    conn, question, embedder, reranker, candidates=args.k, top_n=args.k
                ).hits
            timings.append(time.perf_counter() - started)
            rank = _rank(hits, number, article, must)
            ranks.append(rank)
            score = f" {hits[rank - 1].rerank_score:.3f}" if rank and reranker else ""
            print(f"{str(rank or '-'):>4}{score}  {article:9} {number:16} {question}")

    n = len(CASES)

    def recall(k: int) -> int:
        return sum(1 for r in ranks if r and r <= k)

    mrr = sum(1 / r for r in ranks if r) / n
    print(
        f"\nRecall@1: {recall(1)}/{n}  Recall@5: {recall(5)}/{n}  Recall@{args.k}: "
        f"{recall(args.k)}/{n}  MRR: {mrr:.3f}  thời gian TB: {sum(timings) / n:.2f}s"
    )


if __name__ == "__main__":
    main()
