"""CLI pipeline xử lý văn bản pháp luật.

Ví dụ:
    uv run python -m app.pipeline chunk                          # cắt toàn bộ văn bản trong DB
    uv run python -m app.pipeline chunk --document 168/2024/NĐ-CP --dry-run
"""

from __future__ import annotations

import argparse
import logging

from app.core.config import get_settings
from app.pipeline.chunking import DEFAULT_MAX_CHARS
from app.pipeline.store import chunk_documents


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.pipeline", description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", help="mặc định: DATABASE_URL / .env")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_chunk = sub.add_parser("chunk", help="Hierarchical chunking -> legal_chunks (Task 2.1)")
    p_chunk.add_argument("--document", action="append", help="số hiệu văn bản (lặp lại được)")
    p_chunk.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    p_chunk.add_argument("--dry-run", action="store_true", help="chỉ báo cáo, không ghi DB")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conninfo = args.database_url or get_settings().database_url

    if args.cmd == "chunk":
        reports = chunk_documents(
            conninfo,
            document_numbers=args.document,
            max_chars=args.max_chars,
            dry_run=args.dry_run,
        )
        print(f"{'Văn bản':18} {'Đoạn':>5} {'Điều':>9} {'Phụ lục':>7} {'Dài nhất':>8}  Thiếu Điều")
        for r in reports:
            missing = ", ".join(map(str, r.missing_articles[:10]))
            if len(r.missing_articles) > 10:
                missing += f", … (+{len(r.missing_articles) - 10})"
            print(
                f"{r.document_number:18} {r.chunks:5} {r.articles:4}/{r.last_article:<4}"
                f" {r.appendices:7} {r.max_chars:8}  {missing}"
            )
        print(f"Tổng: {sum(r.chunks for r in reports)} đoạn / {len(reports)} văn bản")


if __name__ == "__main__":
    main()
