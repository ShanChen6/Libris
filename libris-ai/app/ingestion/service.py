"""Task 4.1 – Nạp văn bản do Admin tải lên: file -> văn bản sạch -> metadata & hiệu lực -> chunk
-> embedding. Chạy nền; tiến trình ghi vào bảng ingestion_jobs để libris-api theo dõi.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.pipeline.embedding import Embedder
from app.pipeline.ocr_fix import clean_corpus_model, fix_text
from app.pipeline.store import chunk_documents, embed_chunks
from crawler.clean import clean_text, is_colophon_page, strip_continuation_header
from crawler.extract import SUPPORTED_EXTENSIONS, extract_document
from crawler.metadata import (
    extract_provisions,
    extract_relations,
    normalize_document_type,
    normalize_number,
    normalize_title,
    self_effective_date,
)

log = logging.getLogger(__name__)

# Một văn bản một lúc: OCR và embedding đều dùng hết CPU
_LOCK = threading.Lock()


class IngestError(ValueError):
    pass


@dataclass
class UploadedDocument:
    filename: str
    content_type: str | None
    data: bytes
    document_number: str
    title: str
    document_type: str | None = None
    issuing_body: str | None = None
    signer: str | None = None
    issue_date: date | None = None
    effective_date: date | None = None
    created_by: str | None = None


def create_job(conn: psycopg.Connection, doc: UploadedDocument, upload_dir: Path) -> str:
    ext = Path(doc.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise IngestError(f"Chỉ nhận file {', '.join(SUPPORTED_EXTENSIONS)}")
    if not doc.data:
        raise IngestError("File rỗng")
    sha = hashlib.sha256(doc.data).hexdigest()
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / f"{sha}{ext}").write_bytes(doc.data)
    metadata = {
        "title": doc.title,
        "document_type": doc.document_type,
        "issuing_body": doc.issuing_body,
        "signer": doc.signer,
        "issue_date": doc.issue_date.isoformat() if doc.issue_date else None,
        "effective_date": doc.effective_date.isoformat() if doc.effective_date else None,
        "stored_as": f"{sha}{ext}",
    }
    row = conn.execute(
        """
        INSERT INTO ingestion_jobs
          (filename, content_type, size_bytes, sha256, document_number, metadata, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (
            doc.filename,
            doc.content_type,
            len(doc.data),
            sha,
            normalize_number(doc.document_number),
            Jsonb(metadata),
            doc.created_by,
        ),
    ).fetchone()
    conn.commit()
    assert row is not None
    return str(row[0])


def _extract_text(path: Path, filename: str, ocr: bool) -> tuple[str, dict[str, Any]]:
    pages = extract_document(path.read_bytes(), filename, ocr=ocr)
    kept = [p for p in pages if not is_colophon_page(p.text)]
    text = clean_text(strip_continuation_header("\n".join(p.text for p in kept)))
    methods = [p.method for p in kept]
    stats = {
        "total_pages": len(pages),
        "ocr_pages": methods.count("ocr"),
        "empty_pages": methods.count("empty"),
    }
    return text, stats


def _step(conn: psycopg.Connection, job_id: str, step: str, **fields: Any) -> None:
    sets = ", ".join(["step = %s", *[f"{k} = %s" for k in fields]])
    conn.execute(
        f"UPDATE ingestion_jobs SET {sets} WHERE id = %s", [step, *fields.values(), job_id]
    )
    conn.commit()


def run_job(
    conninfo: str,
    job_id: str,
    embedder: Embedder,
    upload_dir: Path,
    *,
    ocr: bool = True,
    today: date | None = None,
) -> None:
    """Chạy trọn pipeline cho một job; lỗi được ghi vào job (không ném ra ngoài)."""
    with _LOCK, psycopg.connect(conninfo) as conn:
        try:
            _run(conn, conninfo, job_id, embedder, upload_dir, ocr=ocr, today=today)
        except Exception as exc:  # noqa: BLE001 – ghi mọi lỗi vào job cho Admin xem
            log.exception("Ingestion %s lỗi", job_id)
            conn.rollback()
            conn.execute(
                "UPDATE ingestion_jobs SET status = 'failed', error = %s, finished_at = now() "
                "WHERE id = %s",
                (str(exc)[:2000], job_id),
            )
            conn.commit()


def _run(
    conn: psycopg.Connection,
    conninfo: str,
    job_id: str,
    embedder: Embedder,
    upload_dir: Path,
    *,
    ocr: bool,
    today: date | None,
) -> None:
    job = conn.execute(
        "SELECT filename, document_number, metadata FROM ingestion_jobs WHERE id = %s", (job_id,)
    ).fetchone()
    if job is None:
        raise IngestError(f"Không có job {job_id}")
    filename, number, meta = job
    conn.execute(
        "UPDATE ingestion_jobs SET status = 'processing', step = 'extract', started_at = now() "
        "WHERE id = %s",
        (job_id,),
    )
    conn.commit()

    text, stats = _extract_text(upload_dir / meta["stored_as"], filename, ocr)
    if len(text) < 50:
        raise IngestError(
            "Không trích xuất được nội dung văn bản từ file (file scan không có chữ?)"
        )
    warnings: list[str] = []
    needs_review = bool(stats["ocr_pages"] or stats["empty_pages"])
    if needs_review:
        warnings.append(
            f"{stats['ocr_pages']}/{stats['total_pages']} trang phải OCR: cần rà soát nội dung"
        )
    if stats["ocr_pages"]:
        # Hiệu đính dấu thanh bị OCR làm mất, dựa trên văn bản sạch đã có trong kho
        text, fixes = fix_text(text, clean_corpus_model(conn))
        if fixes.replaced:
            warnings.append(f"Đã hiệu đính tự động {fixes.replaced} chỗ mất dấu do OCR")

    _step(conn, job_id, "metadata")
    title = normalize_title(meta.get("title")) or number
    effective = meta.get("effective_date") or self_effective_date(text)
    if not meta.get("effective_date") and effective:
        warnings.append(f"Ngày hiệu lực lấy từ nội dung văn bản: {effective}")
    row = conn.execute(
        """
        INSERT INTO legal_documents (
          document_number, document_type, title, issuing_body, signer, issue_date,
          effective_date, full_text, needs_review, source, source_id, metadata)
        VALUES (%(number)s, %(type)s, %(title)s, %(issuing_body)s, %(signer)s, %(issue_date)s,
                %(effective)s, %(text)s, %(review)s, 'upload', %(job)s, %(meta)s)
        ON CONFLICT (document_number) DO UPDATE SET
          document_type = EXCLUDED.document_type, title = EXCLUDED.title,
          issuing_body = EXCLUDED.issuing_body, signer = EXCLUDED.signer,
          issue_date = EXCLUDED.issue_date, effective_date = EXCLUDED.effective_date,
          full_text = EXCLUDED.full_text, needs_review = EXCLUDED.needs_review,
          source = EXCLUDED.source, source_id = EXCLUDED.source_id, metadata = EXCLUDED.metadata
        RETURNING id
        """,
        {
            "number": number,
            "type": normalize_document_type(meta.get("document_type"), number),
            "title": title,
            "issuing_body": meta.get("issuing_body"),
            "signer": meta.get("signer"),
            "issue_date": meta.get("issue_date"),
            "effective": effective,
            "text": text,
            "review": needs_review,
            "job": job_id,
            "meta": Jsonb(
                {"upload": {"job_id": job_id, "filename": filename}, "extraction": stats}
            ),
        },
    ).fetchone()
    assert row is not None
    document_id = row[0]

    # Quan hệ hiệu lực với văn bản khác (thay thế, bãi bỏ, sửa đổi) rồi tính lại trạng thái
    relations = extract_relations(number, title, text)
    provisions = extract_provisions(number, text)
    conn.execute("DELETE FROM document_relations WHERE source_number = %s", (number,))
    conn.execute("DELETE FROM superseded_provisions WHERE source_number = %s", (number,))
    for r in relations:
        when = r.effective or effective
        if r.type == "sets_effective_date" and r.effective:
            conn.execute(
                "UPDATE legal_documents SET effective_date = %s WHERE document_number = %s",
                (r.effective, r.target),
            )
        conn.execute(
            "INSERT INTO document_relations VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (r.source, r.target, r.type, when, r.evidence),
        )
    for p in provisions:
        conn.execute(
            "INSERT INTO superseded_provisions VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (p.target, p.article, p.clause or "", p.kind, p.source, effective, p.evidence),
        )
    conn.execute("SELECT recompute_document_status(%s)", (today or date.today(),))
    _step(conn, job_id, "chunk", document_id=document_id)

    (report,) = chunk_documents(conninfo, document_numbers=[number])
    if report.missing_articles:
        warnings.append(f"Không nhận diện được tiêu đề Điều: {report.missing_articles[:20]}")
    _step(conn, job_id, "embed", chunks=report.chunks)

    embed_chunks(conninfo, embedder, document_numbers=[number])
    affected = sorted({r.target for r in relations} | {p.target for p in provisions})
    if affected:
        warnings.append(f"Đã cập nhật quan hệ hiệu lực với: {', '.join(affected)}")
    conn.execute(
        "UPDATE ingestion_jobs SET status = 'done', step = NULL, warnings = %s, "
        "finished_at = now() WHERE id = %s",
        (Jsonb(warnings), job_id),
    )
    conn.commit()
    log.info("Ingestion %s xong: %s, %d đoạn", job_id, number, report.chunks)


JOB_COLUMNS = (
    "id, status, step, filename, content_type, size_bytes, document_number, metadata, "
    "document_id, chunks, warnings, error, created_by, created_at, started_at, finished_at"
)


def get_job(conn: psycopg.Connection, job_id: str) -> dict[str, Any] | None:
    cur = conn.execute(f"SELECT {JOB_COLUMNS} FROM ingestion_jobs WHERE id = %s", (job_id,))
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip([c.name for c in cur.description or []], row, strict=True))
