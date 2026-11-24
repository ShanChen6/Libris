"""CLI pipeline xử lý văn bản pháp luật.

Ví dụ:
    uv run python -m app.pipeline chunk                          # cắt toàn bộ văn bản trong DB
    uv run python -m app.pipeline chunk --document 168/2024/NĐ-CP --dry-run
    uv run python -m app.pipeline embed                          # sinh embedding còn thiếu
    uv run python -m app.pipeline search "Đi xe máy không có gương chiếu hậu bị phạt không?"
    uv run python -m app.pipeline ocrfix --dry-run              # hiệu đính dấu thanh bị OCR làm mất
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

    p_search = sub.add_parser(
        "search", help="tra thử truy xuất: Router + Hybrid + Rerank (3.1-3.3)"
    )
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=5)
    p_search.add_argument(
        "--all-status", action="store_true", help="tìm cả văn bản đã hết hiệu lực"
    )
    p_search.add_argument("--no-rerank", action="store_true", help="bỏ qua cross-encoder")
    p_search.add_argument("--candidates", type=int, help="số ứng viên đưa vào reranker")

    p_fix = sub.add_parser(
        "ocrfix", help="hiệu đính dấu thanh bị OCR làm mất, rồi cắt đoạn + embedding lại"
    )
    p_fix.add_argument("--document", action="append", help="số hiệu văn bản (lặp lại được)")
    p_fix.add_argument("--dry-run", action="store_true", help="chỉ đếm, không ghi DB")

    p_ask = sub.add_parser("ask", help="hỏi đáp có trích dẫn (Task 3.4), cần LLM")
    p_ask.add_argument("question")
    p_ask.add_argument("--all-status", action="store_true", help="dùng cả văn bản hết hiệu lực")

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
        from app.retrieval.rerank import get_reranker
        from app.retrieval.service import make_plan, retrieve

        settings = get_settings()
        plan = make_plan(args.query, include_expired=True if args.all_status else None)
        reranker = None if args.no_rerank else get_reranker()
        with psycopg.connect(conninfo) as conn:
            res = retrieve(
                conn,
                args.query,
                get_embedder(),
                reranker,
                candidates=args.candidates or settings.rerank_candidates,
                top_n=args.k,
                plan=plan,
            )
        if res.expanded_query != args.query:
            print(f"Mở rộng: {res.expanded_query}")
        print(f"Router: {res.plan.mode} {res.plan.statuses}")
        for reason in res.plan.reasons:
            print(f"  - {reason}")
        for i, h in enumerate(res.hits, 1):
            ranks = f"vec={h.vec_rank} kw={h.kw_rank}" + (
                f" ref={h.ref_rank}" if h.ref_rank else ""
            )
            if h.rerank_score is not None:
                ranks = f"rerank={h.rerank_score:.3f} hybrid#{h.hybrid_rank} " + ranks
            note = f" (bị thay thế bởi {', '.join(h.replaced_by)})" if h.replaced_by else ""
            if h.superseded_by:
                note += f" (Điều/Khoản bị bãi bỏ/sửa đổi: {', '.join(h.superseded_by)})"
            print(f"\n{i}. [{ranks}] {h.citation} {h.status}{note}")
            print(f"   {' '.join(h.content.split())[:160]}")

    elif args.cmd == "ocrfix":
        from app.pipeline.embedding import get_embedder
        from app.pipeline.ocr_fix import fix_documents

        fixed = fix_documents(conninfo, args.document, dry_run=args.dry_run)
        for number, n in fixed:
            print(f"{number:18} {n:6} chỗ")
        changed = [number for number, n in fixed if n]
        if changed and not args.dry_run:
            chunk_documents(conninfo, document_numbers=changed)
            report = embed_chunks(conninfo, get_embedder(), document_numbers=changed)
            print(f"Đã cắt đoạn và sinh {report.embedded} embedding cho {len(changed)} văn bản")

    elif args.cmd == "ask":
        import psycopg

        from app.generation.answer import answer_question
        from app.generation.llm import get_llm
        from app.pipeline.embedding import get_embedder
        from app.retrieval.rerank import get_reranker
        from app.retrieval.service import make_plan

        settings = get_settings()
        plan = make_plan(args.question, include_expired=True if args.all_status else None)
        with psycopg.connect(conninfo) as conn:
            res = answer_question(
                conn,
                args.question,
                embedder=get_embedder(),
                reranker=get_reranker(),
                llm=get_llm(),
                plan=plan,
                candidates=settings.rerank_candidates,
                top_n=settings.rerank_top_n,
                min_rerank_score=settings.answer_min_rerank_score,
            )
        print(res.answer)
        print(
            f"\n— Router: {res.plan.mode}; mô hình: {res.model}; "
            f"thời gian: {', '.join(f'{k} {v:.1f}s' for k, v in res.timings.items())}"
        )
        if res.refused:
            print(f"— Từ chối: {res.refusal_reason}")
        for w in res.warnings:
            print(f"— Cảnh báo: {w}")


if __name__ == "__main__":
    main()
