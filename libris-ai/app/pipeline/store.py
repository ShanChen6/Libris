"""Ghi kết quả chunking vào bảng legal_chunks."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

import psycopg

from app.pipeline.chunking import DEFAULT_MAX_CHARS, build_chunks

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
    with psycopg.connect(conninfo) as conn:
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
