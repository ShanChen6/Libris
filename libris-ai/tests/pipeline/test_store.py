import psycopg

from app.pipeline.store import chunk_documents
from tests.pipeline.test_chunking import DOC


def _insert_document(conninfo: str, text: str) -> None:
    with psycopg.connect(conninfo) as conn:
        conn.execute(
            "INSERT INTO legal_documents (document_number, document_type, title, full_text, "
            "source, source_id) VALUES ('168/2024/NĐ-CP', 'Nghị định', 'Quy định xử phạt', %s, "
            "'test', '1')",
            (text,),
        )


def test_chunk_documents_writes_and_replaces(pg_conninfo: str) -> None:
    _insert_document(pg_conninfo, DOC)

    dry = chunk_documents(pg_conninfo, dry_run=True)
    assert dry[0].articles == 3
    with psycopg.connect(pg_conninfo) as conn:
        assert conn.execute("SELECT count(*) FROM legal_chunks").fetchone() == (0,)

    (report,) = chunk_documents(pg_conninfo, max_chars=160)
    with psycopg.connect(pg_conninfo) as conn:
        rows = conn.execute(
            "SELECT c.content = substr(d.full_text, c.char_start + 1, c.char_end - c.char_start),"
            " c.article, c.clause, c.point, c.search_vector @@ to_tsquery('simple', 'gương')"
            " FROM legal_chunks c JOIN legal_documents d ON d.id = c.document_id"
            " ORDER BY c.chunk_index"
        ).fetchall()
    assert len(rows) == report.chunks
    assert all(r[0] for r in rows)  # char_start/char_end khớp full_text trong DB
    assert ("Điều 2", "Khoản 1", "Điểm a–b", True) in [r[1:] for r in rows]

    # Chạy lại thay thế hoàn toàn, không nhân đôi
    chunk_documents(pg_conninfo)
    with psycopg.connect(pg_conninfo) as conn:
        (count,) = conn.execute("SELECT count(*) FROM legal_chunks").fetchone()  # type: ignore[misc]
    assert count < report.chunks
