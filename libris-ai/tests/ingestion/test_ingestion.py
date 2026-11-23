import uuid
from datetime import date
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.ingestion.service import IngestError, UploadedDocument, create_job, get_job, run_job
from app.main import app
from app.pipeline.embedding import get_embedder
from tests.crawler.test_http_and_pipeline import _docx_bytes
from tests.fakes import FakeEmbedder

OLD_LAW = [
    "QUỐC HỘI",
    "Luật số: 23/2008/QH12",
    "Điều 1. Phạm vi điều chỉnh",
    "Luật này quy định về quy tắc giao thông đường bộ cho người tham gia giao thông.",
    "Điều 2. Hiệu lực thi hành",
    "Luật này có hiệu lực thi hành từ ngày 01 tháng 7 năm 2009.",
]
NEW_LAW = [
    "QUỐC HỘI",
    "Luật số: 36/2024/QH15",
    "Căn cứ Hiến pháp nước Cộng hòa xã hội chủ nghĩa Việt Nam;",
    "Chương I",
    "NHỮNG QUY ĐỊNH CHUNG",
    "Điều 1. Phạm vi điều chỉnh",
    "Luật này quy định về quy tắc, phương tiện, người tham gia giao thông đường bộ.",
    "Điều 2. Hiệu lực thi hành",
    "1. Luật này có hiệu lực thi hành từ ngày 01 tháng 01 năm 2025.",
    "2. Luật Giao thông đường bộ số 23/2008/QH12 hết hiệu lực kể từ ngày Luật này có hiệu lực "
    "thi hành.",
]


def _doc(number: str, paragraphs: list[str], **kw) -> UploadedDocument:
    return UploadedDocument(
        filename=f"{number.replace('/', '-')}.docx", content_type=None,
        data=_docx_bytes(paragraphs), document_number=number, title=kw.pop("title", "Luật"), **kw,
    )  # fmt: skip


def _ingest(conninfo: str, doc: UploadedDocument, tmp_path: Path) -> dict:
    with psycopg.connect(conninfo) as conn:
        job_id = create_job(conn, doc, tmp_path)
    run_job(conninfo, job_id, FakeEmbedder(), tmp_path, ocr=False, today=date(2026, 1, 1))
    with psycopg.connect(conninfo) as conn:
        job = get_job(conn, job_id)
    assert job is not None
    return job


def test_ingest_document_end_to_end(pg_conninfo: str, tmp_path: Path) -> None:
    job = _ingest(pg_conninfo, _doc("23/2008/QH12", OLD_LAW, title="LUẬT GIAO THÔNG ĐƯỜNG BỘ"),
                  tmp_path)  # fmt: skip
    assert job["status"] == "done", job["error"]
    assert job["chunks"] >= 2 and job["document_id"] and job["finished_at"]
    assert "Ngày hiệu lực lấy từ nội dung văn bản: 2009-07-01" in job["warnings"]
    with psycopg.connect(pg_conninfo) as conn:
        doc = conn.execute(
            "SELECT title, document_type, effective_date, status::text, source FROM legal_documents"
        ).fetchone()
        assert doc == ("Luật giao thông đường bộ", "Luật", date(2009, 7, 1), "ACTIVE", "upload")
        chunks = conn.execute("SELECT count(*), count(embedding) FROM legal_chunks").fetchone()
        assert chunks == (job["chunks"], job["chunks"])


def test_new_law_expires_old_one(pg_conninfo: str, tmp_path: Path) -> None:
    _ingest(pg_conninfo, _doc("23/2008/QH12", OLD_LAW), tmp_path)
    job = _ingest(pg_conninfo, _doc("36/2024/QH15", NEW_LAW, effective_date=date(2025, 1, 1)),
                  tmp_path)  # fmt: skip
    assert job["status"] == "done", job["error"]
    assert "Đã cập nhật quan hệ hiệu lực với: 23/2008/QH12" in job["warnings"]
    with psycopg.connect(pg_conninfo) as conn:
        rows = dict(conn.execute(
            "SELECT document_number, status::text || ' ' || coalesce(expiry_date::text, '') "
            "FROM legal_documents"
        ).fetchall())  # fmt: skip
    assert rows == {"23/2008/QH12": "EXPIRED 2025-01-01", "36/2024/QH15": "ACTIVE "}


def test_reupload_replaces_document(pg_conninfo: str, tmp_path: Path) -> None:
    _ingest(pg_conninfo, _doc("23/2008/QH12", OLD_LAW), tmp_path)
    job = _ingest(pg_conninfo, _doc("23/2008/QH12", [*OLD_LAW[:4], "Điều 2. Bổ sung"]), tmp_path)
    assert job["status"] == "done"
    with psycopg.connect(pg_conninfo) as conn:
        assert conn.execute("SELECT count(*) FROM legal_documents").fetchone() == (1,)
        texts = [r[0] for r in conn.execute("SELECT content FROM legal_chunks").fetchall()]
    assert any("Bổ sung" in t for t in texts) and not any("2009" in t for t in texts)


def test_failed_job_records_error(pg_conninfo: str, tmp_path: Path) -> None:
    job = _ingest(pg_conninfo, _doc("1/2024/QH15", ["Ngắn"]), tmp_path)
    assert job["status"] == "failed" and "Không trích xuất được nội dung" in job["error"]
    with psycopg.connect(pg_conninfo) as conn, pytest.raises(IngestError):
        create_job(conn, UploadedDocument("a.txt", None, b"x", "1/2024/QH15", "X"), tmp_path)


def test_ingest_api_with_internal_token(pg_conninfo: str, tmp_path: Path) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=pg_conninfo, internal_api_token="secret-token", upload_dir=str(tmp_path)
    )
    app.dependency_overrides[get_embedder] = FakeEmbedder
    try:
        client = TestClient(app)
        form = {"document_number": "23/2008/QH12", "title": "Luật Giao thông đường bộ"}
        files = {"file": ("luat.docx", _docx_bytes(OLD_LAW))}
        assert client.post("/ingest", data=form, files=files).status_code == 401
        assert client.post("/search", json={"query": "x"}).status_code == 401
        assert client.get("/health").status_code == 200  # giám sát không cần token

        headers = {"X-Internal-Token": "secret-token"}
        res = client.post("/ingest", data=form, files=files, headers=headers)
        assert res.status_code == 202, res.text
        job_id = res.json()["job_id"]
        # TestClient chạy BackgroundTasks xong trước khi trả về
        job = client.get(f"/ingest/{job_id}", headers=headers).json()
        assert job["status"] == "done", job
        assert client.get(f"/ingest/{uuid.uuid4()}", headers=headers).status_code == 404

        bad = client.post("/ingest", data=form, files={"file": ("a.txt", b"x")}, headers=headers)
        assert bad.status_code == 422
    finally:
        app.dependency_overrides.clear()
