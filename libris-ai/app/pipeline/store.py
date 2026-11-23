"""Ghi kết quả chunking vào bảng legal_chunks."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field

import psycopg
from pgvector.psycopg import register_vector

from app.pipeline.chunking import DEFAULT_MAX_CHARS, build_chunks
from app.pipeline.embedding import Embedder, chunk_text

log = logging.getLogger(__name__)

_INSERT_CHUNK = """
INSERT INTO legal_chunks (
  document_id, chunk_index, part, chapter, section, article, article_title, clause, point,
  context_prefix, content, char_start, char_end
) VALUES (
  %(document_id)s, %(chunk_index)s, %(part)s, %(chapter)s, %(section)s, %(article)s,
  %(article_title)s, %(clause)s, %(point)s, %(context_prefix)s, %(content)s, %(char_start)s,
  %(char_end)s
)
"""


@dataclass
class ChunkReport:
    document_number: str
    chunks: int
    articles: int
    last_article: int
    missing_articles: list[int] = field(default_factory=list)
    appendices: int = 0
    max_chars: int = 0


def chunk_documents(
    conninfo: str,
    *,
    document_numbers: list[str] | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    dry_run: bool = False,
) -> list[ChunkReport]:
    """Cắt lại các văn bản (mặc định: tất cả) và thay thế toàn bộ chunk cũ của chúng."""
    reports: list[ChunkReport] = []
    # autocommit: mỗi khối conn.transaction() là một transaction thật, commit ngay khi xong
    with psycopg.connect(conninfo, autocommit=True) as conn:
        query = "SELECT id, document_number, document_type, title, full_text FROM legal_documents"
        params: tuple[object, ...] = ()
        if document_numbers:
            query += " WHERE document_number = ANY(%s)"
            params = (document_numbers,)
        docs = conn.execute(query + " ORDER BY issue_date, document_number", params).fetchall()

        for doc_id, number, doc_type, title, full_text in docs:
            chunks, parse_report = build_chunks(
                full_text,
                document_type=doc_type,
                document_number=number,
                title=title,
                max_chars=max_chars,
            )
            reports.append(
                ChunkReport(
                    document_number=number,
                    chunks=len(chunks),
                    articles=parse_report.articles,
                    last_article=parse_report.last_article,
                    missing_articles=parse_report.missing_articles,
                    appendices=parse_report.appendices,
                    max_chars=max((len(c.content) for c in chunks), default=0),
                )
            )
            if dry_run:
                continue
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("DELETE FROM legal_chunks WHERE document_id = %s", (doc_id,))
                cur.executemany(
                    _INSERT_CHUNK, [asdict(c) | {"document_id": doc_id} for c in chunks]
                )
            log.info("%s: %d đoạn", number, len(chunks))
    return reports


@dataclass
class EmbedReport:
    embedded: int = 0
    over_limit: int = 0  # đoạn dài hơn max_seq_length token (bị mô hình cắt bớt)
    max_tokens: int = 0


def embed_chunks(
    conninfo: str,
    embedder: Embedder,
    *,
    document_numbers: list[str] | None = None,
    force: bool = False,
    batch_size: int = 64,
    limit: int | None = None,
) -> EmbedReport:
    """Sinh embedding cho các đoạn chưa có (hoặc tất cả nếu ``force``).

    Commit sau mỗi lô, nên có thể dừng giữa chừng và chạy lại để làm tiếp.
    """
    report = EmbedReport()
    # autocommit: mỗi khối conn.transaction() là một transaction thật, commit ngay khi xong
    with psycopg.connect(conninfo, autocommit=True) as conn:
        register_vector(conn)
        where = [] if force else ["c.embedding IS NULL"]
        params: list[object] = []
        if document_numbers:
            where.append("d.document_number = ANY(%s)")
            params.append(document_numbers)
        query = (
            "SELECT c.id, c.context_prefix, c.content FROM legal_chunks c "
            "JOIN legal_documents d ON d.id = c.document_id"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY d.issue_date, d.document_number, c.chunk_index"
        )
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = conn.execute(query, params).fetchall()
        total = len(rows)
        log.info("Cần sinh embedding cho %d đoạn", total)
        started = time.monotonic()
        for i in range(0, total, batch_size):
            batch = rows[i : i + batch_size]
            texts = [chunk_text(prefix, content) for _, prefix, content in batch]
            vectors = embedder.encode(texts)
            tokens = embedder.count_tokens(texts)
            with conn.transaction(), conn.cursor() as cur:
                cur.executemany(
                    "UPDATE legal_chunks SET embedding = %s, token_count = %s WHERE id = %s",
                    [
                        (vec, n_tok, chunk_id)
                        for (chunk_id, _, _), vec, n_tok in zip(batch, vectors, tokens, strict=True)
                    ],
                )
            report.embedded += len(batch)
            report.over_limit += sum(t > embedder.max_seq_length for t in tokens)
            report.max_tokens = max([report.max_tokens, *tokens])
            elapsed = time.monotonic() - started
            eta = elapsed / report.embedded * (total - report.embedded)
            log.info("Embedding %d/%d (còn ~%.0f phút)", report.embedded, total, eta / 60)
    return report
