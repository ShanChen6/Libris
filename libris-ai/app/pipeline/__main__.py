"""CLI pipeline xử lý văn bản pháp luật.

Ví dụ:
    uv run python -m app.pipeline chunk                          # cắt toàn bộ văn bản trong DB
    uv run python -m app.pipeline chunk --document 168/2024/NĐ-CP --dry-run
    uv run python -m app.pipeline embed                          # sinh embedding còn thiếu
    uv run python -m app.pipeline search "Đi xe máy không có gương chiếu hậu bị phạt không?"
"""

from __future__ import annotations

import argparse
import logging

from app.core.config import get_settings
from app.pipeline.chunking import DEFAULT_MAX_CHARS
from app.pipeline.store import chunk_documents, embed_chunks


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.pipeline", description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", help="mặc định: DATABASE_URL / .env")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_chunk = sub.add_parser("chunk", help="Hierarchical chunking -> legal_chunks (Task 2.1)")
    p_chunk.add_argument("--document", action="append", help="số hiệu văn bản (lặp lại được)")
    p_chunk.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    p_chunk.add_argument("--dry-run", action="store_true", help="chỉ báo cáo, không ghi DB")

    p_embed = sub.add_parser("embed", help="sinh embedding bge-m3 cho legal_chunks (Task 2.2)")
    p_embed.add_argument("--document", action="append", help="số hiệu văn bản (lặp lại được)")
    p_embed.add_argument("--force", action="store_true", help="sinh lại cả đoạn đã có embedding")
    p_embed.add_argument("--batch-size", type=int, default=64, help="số đoạn mỗi lần commit")
    p_embed.add_argument("--limit", type=int)

    p_search = sub.add_parser("search", help="tra thử: so sánh tìm theo ngữ nghĩa và từ khóa")
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=5)
    p_search.add_argument(
        "--all-status", action="store_true", help="tìm cả văn bản đã hết hiệu lực"
    )

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
    elif args.cmd == "embed":
        from app.pipeline.embedding import get_embedder

        report = embed_chunks(
            conninfo,
            get_embedder(),
            document_numbers=args.document,
            force=args.force,
            batch_size=args.batch_size,
            limit=args.limit,
        )
        print(
            f"Đã sinh {report.embedded} embedding; dài nhất {report.max_tokens} token; "
            f"{report.over_limit} đoạn vượt max_seq_length"
        )
    elif args.cmd == "search":
        import psycopg

        from app.pipeline.embedding import get_embedder
        from app.pipeline.search import IN_FORCE, keyword_search, semantic_search

        statuses = ("ACTIVE", "AMENDED", "EXPIRED", "PENDING") if args.all_status else IN_FORCE
        vector = get_embedder().encode([args.query])[0]
        with psycopg.connect(conninfo) as conn:
            for name, hits in (
                ("Ngữ nghĩa (vector)", semantic_search(conn, vector, k=args.k, statuses=statuses)),
                ("Từ khóa (full-text)", keyword_search(conn, args.query, k=args.k,
                                                       statuses=statuses)),
            ):  # fmt: skip
                print(f"\n=== {name}")
                for i, h in enumerate(hits, 1):
                    snippet = " ".join(h.content.split())[:150]
                    print(f"{i}. {h.score:.3f} {h.citation} ({h.status})\n   {snippet}")


if __name__ == "__main__":
    main()
