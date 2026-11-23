"""Integration test cho loader + migration SQL.

Cần PostgreSQL có pgvector (VD: `docker compose up -d` ở gốc repo), rồi:
    LIBRIS_TEST_DATABASE_URL=postgresql://libris:libris@localhost:5432/libris uv run pytest
Test chạy trong một schema tạm và xóa schema đó khi xong.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import psycopg
import pytest

from crawler.db import load

DB_URL = os.environ.get("LIBRIS_TEST_DATABASE_URL")
MIGRATIONS = Path(__file__).resolve().parents[3] / "db" / "migrations"

pytestmark = pytest.mark.skipif(not DB_URL, reason="cần LIBRIS_TEST_DATABASE_URL")


def _up_sql(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return re.split(r"^-- migrate:down", text, flags=re.MULTILINE)[0]


@pytest.fixture
def conninfo() -> Iterator[str]:
    assert DB_URL
    schema = f"test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute(f"SET search_path TO {schema}, public")
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(_up_sql(path).replace("CREATE EXTENSION IF NOT EXISTS vector;", ""))
    sep = "&" if "?" in DB_URL else "?"
    try:
        yield f"{DB_URL}{sep}options={quote(f'-csearch_path={schema},public')}"
    finally:
        with psycopg.connect(DB_URL, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")


def _write_data(tmp_path: Path, text: str) -> tuple[Path, Path]:
    processed = tmp_path / "processed"
    processed.mkdir(exist_ok=True)
    record = {
        "metadata": {
            "source": "vanban.chinhphu.vn",
            "source_id": "211194",
            "raw_fields": {"Số ký hiệu": "36/2024/QH15"},
            "attachments": [],
        },
        "text": text,
        "extraction": {"total_pages": 2, "ocr_pages": 0, "empty_pages": 0},
    }
    (processed / "211194.json").write_text(json.dumps(record), encoding="utf-8")
    catalog = {
        "as_of": "2026-01-01",
        "documents": [
            {
                "source_id": "211194",
                "document_number": "36/2024/QH15",
                "document_type": "Luật",
                "title": "Luật Trật tự, an toàn giao thông đường bộ",
                "issuing_body": "Quốc hội",
                "signer": "Trần Thanh Mẫn",
                "issue_date": "2024-06-27",
                "effective_date": "2025-01-01",
                "expiry_date": None,
                "status": "ACTIVE",
                "replaced_by": [],
                "amended_by": [],
                "replaces": ["23/2008/QH12"],
                "amends": [],
                "evidence": [],
                "source_url": "https://vanban.chinhphu.vn/?pageid=27160&docid=211194",
                "needs_review": False,
                "warnings": [],
            }
        ],
        "relations": [
            {
                "type": "replaces",
                "source": "36/2024/QH15",
                "target": "23/2008/QH12",
                "effective": "2025-01-01",
                "evidence": "Luật Giao thông đường bộ số 23/2008/QH12 ... hết hiệu lực",
            }
        ],
    }
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    return catalog_path, processed


def test_load_documents_and_relations(conninfo: str, tmp_path: Path) -> None:
    catalog_path, processed = _write_data(tmp_path, "Điều 1. Phạm vi điều chỉnh")
    res = load(conninfo, catalog_path, processed)
    assert (res.inserted, res.updated, res.relations) == (1, 0, 1)

    with psycopg.connect(conninfo) as conn:
        row = conn.execute(
            "SELECT status, effective_date::text, metadata->'replaces', full_text "
            "FROM legal_documents WHERE document_number = '36/2024/QH15'"
        ).fetchone()
        assert row == ("ACTIVE", "2025-01-01", ["23/2008/QH12"], "Điều 1. Phạm vi điều chỉnh")
        rel = conn.execute("SELECT target_number, relation_type FROM document_relations").fetchall()
        assert rel == [("23/2008/QH12", "replaces")]


def test_reload_invalidates_chunks_only_when_text_changes(conninfo: str, tmp_path: Path) -> None:
    catalog_path, processed = _write_data(tmp_path, "Điều 1. Phạm vi điều chỉnh")
    load(conninfo, catalog_path, processed)
    with psycopg.connect(conninfo) as conn:
        conn.execute(
            "INSERT INTO legal_chunks (document_id, chunk_index, context_prefix, content, "
            "char_start, char_end) SELECT id, 0, '[36/2024/QH15]', 'Điều 1', 0, 6 "
            "FROM legal_documents"
        )

    same = load(conninfo, catalog_path, processed)
    assert (same.inserted, same.updated, same.chunks_invalidated, same.relations) == (0, 1, 0, 1)

    catalog_path, processed = _write_data(tmp_path, "Điều 1. Phạm vi điều chỉnh (sửa)")
    changed = load(conninfo, catalog_path, processed)
    assert changed.chunks_invalidated == 1
    with psycopg.connect(conninfo) as conn:
        assert conn.execute("SELECT count(*) FROM legal_chunks").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM document_relations").fetchone() == (1,)
