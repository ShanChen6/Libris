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

    p_search = sub.add_parser("search", help="tra thử Hybrid Search + Query Router (Task 3.1, 3.2)")
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
        from app.retrieval.hybrid import hybrid_search
        from app.retrieval.router import route

        plan = route(args.query)
        if args.all_status:
            plan.statuses = ("ACTIVE", "AMENDED", "EXPIRED", "PENDING")
        vector = get_embedder().encode([args.query])[0]
        with psycopg.connect(conninfo) as conn:
            res = hybrid_search(conn, args.query, vector, top_k=args.k, plan=plan)
        print(f"Router: {res.plan.mode} {res.plan.statuses}")
        for reason in res.plan.reasons:
            print(f"  - {reason}")
        for i, h in enumerate(res.hits, 1):
            ranks = f"vec={h.vec_rank} kw={h.kw_rank}" + (
                f" ref={h.ref_rank}" if h.ref_rank else ""
            )
            note = f" (bị thay thế bởi {', '.join(h.replaced_by)})" if h.replaced_by else ""
            print(f"\n{i}. {h.score:.4f} [{ranks}] {h.citation} {h.status}{note}")
            print(f"   {' '.join(h.content.split())[:160]}")


if __name__ == "__main__":
    main()
