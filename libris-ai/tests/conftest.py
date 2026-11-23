"""Fixture dùng chung: PostgreSQL thật cho integration test.

Cần PostgreSQL có pgvector (VD: `docker compose up -d` ở gốc repo), rồi:
    LIBRIS_TEST_DATABASE_URL=postgresql://libris:libris@localhost:5432/libris uv run pytest
Mỗi test chạy migration trong một schema tạm và xóa schema đó khi xong.
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import psycopg
import pytest

DB_URL = os.environ.get("LIBRIS_TEST_DATABASE_URL")
REDIS_URL = os.environ.get("LIBRIS_TEST_REDIS_URL")
# Semantic cache tắt mặc định trong test (test của cache tự bật với Redis riêng)
os.environ["SEMANTIC_CACHE_ENABLED"] = "false"
MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"


def _up_sql(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return re.split(r"^-- migrate:down", text, flags=re.MULTILINE)[0]


@pytest.fixture
def pg_conninfo() -> Iterator[str]:
    if not DB_URL:
        pytest.skip("cần LIBRIS_TEST_DATABASE_URL")
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


@pytest.fixture
def redis_client():
    """Redis 8 thật (vector set); test tự dọn các khóa có tiền tố riêng."""
    if not REDIS_URL:
        pytest.skip("Cần LIBRIS_TEST_REDIS_URL (VD redis://localhost:6379/15)")
    import redis

    client = redis.Redis.from_url(REDIS_URL)
    prefix = f"test:{uuid.uuid4().hex[:8]}"
    yield client, prefix
    keys = list(client.scan_iter(f"{prefix}:*"))
    if keys:
        client.delete(*keys)
