"""Nạp văn bản đã thu thập và chuẩn hóa vào PostgreSQL (bảng legal_documents, document_relations).

Schema được quản lý bằng migration SQL trong ``db/migrations`` ở gốc repo (dbmate).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

_UPSERT_DOCUMENT = """
INSERT INTO legal_documents (
  document_number, document_type, title, issuing_body, signer, issue_date, effective_date,
  expiry_date, status, status_as_of, full_text, needs_review, source, source_id, source_url,
  metadata
) VALUES (
  %(document_number)s, %(document_type)s, %(title)s, %(issuing_body)s, %(signer)s,
  %(issue_date)s, %(effective_date)s, %(expiry_date)s, %(status)s, %(status_as_of)s,
  %(full_text)s, %(needs_review)s, %(source)s, %(source_id)s, %(source_url)s, %(metadata)s
)
ON CONFLICT (document_number) DO UPDATE SET
  document_type = EXCLUDED.document_type,
  title = EXCLUDED.title,
  issuing_body = EXCLUDED.issuing_body,
  signer = EXCLUDED.signer,
  issue_date = EXCLUDED.issue_date,
  effective_date = EXCLUDED.effective_date,
  expiry_date = EXCLUDED.expiry_date,
  status = EXCLUDED.status,
  status_as_of = EXCLUDED.status_as_of,
  full_text = EXCLUDED.full_text,
  needs_review = EXCLUDED.needs_review,
  source = EXCLUDED.source,
  source_id = EXCLUDED.source_id,
  source_url = EXCLUDED.source_url,
  metadata = EXCLUDED.metadata
RETURNING id, (xmax = 0) AS inserted
"""


@dataclass
class LoadResult:
    inserted: int = 0
    updated: int = 0
    chunks_invalidated: int = 0
    relations: int = 0


def document_rows(catalog: dict[str, Any], processed_dir: Path) -> list[dict[str, Any]]:
    """Ghép catalog (metadata chuẩn hóa) với nguyên văn trong processed/<source_id>.json."""
    rows: list[dict[str, Any]] = []
    for doc in catalog["documents"]:
        record = json.loads(
            (processed_dir / f"{doc['source_id']}.json").read_text(encoding="utf-8")
        )
        meta = record["metadata"]
        extraction = record["extraction"]
        rows.append(
            {
                "document_number": doc["document_number"],
                "document_type": doc["document_type"],
                "title": doc["title"] or doc["document_number"],
                "issuing_body": doc["issuing_body"],
                "signer": doc["signer"],
                "issue_date": doc["issue_date"],
                "effective_date": doc["effective_date"],
                "expiry_date": doc["expiry_date"],
                "status": doc["status"],
                "status_as_of": catalog["as_of"],
                "full_text": record["text"],
                "needs_review": doc["needs_review"],
                "source": meta["source"],
                "source_id": doc["source_id"],
                "source_url": doc["source_url"],
                "metadata": Jsonb(
                    {
                        "raw_fields": meta.get("raw_fields", {}),
                        "attachments": meta.get("attachments", []),
                        "warnings": doc["warnings"],
                        "status_evidence": doc["evidence"],
                        "replaced_by": doc["replaced_by"],
                        "amended_by": doc["amended_by"],
                        "replaces": doc["replaces"],
                        "amends": doc["amends"],
                        "extraction": {
                            k: extraction[k]
                            for k in ("total_pages", "ocr_pages", "empty_pages")
                            if k in extraction
                        },
                    }
                ),
            }
        )
    return rows


def load(conninfo: str, catalog_path: Path, processed_dir: Path) -> LoadResult:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    rows = document_rows(catalog, processed_dir)
    result = LoadResult()
    with psycopg.connect(conninfo) as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT document_number, md5(full_text) FROM legal_documents")
        old_hashes = dict(cur.fetchall())

        for row in rows:
            cur.execute(_UPSERT_DOCUMENT, row)
            doc_id, inserted = cur.fetchone()  # type: ignore[misc]
            if inserted:
                result.inserted += 1
                continue
            result.updated += 1
            cur.execute("SELECT md5(%s)", (row["full_text"],))
            (new_hash,) = cur.fetchone()  # type: ignore[misc]
            if old_hashes.get(row["document_number"]) != new_hash:
                # Nguyên văn đổi -> vị trí char_start/char_end của chunk cũ không còn đúng
                cur.execute("DELETE FROM legal_chunks WHERE document_id = %s", (doc_id,))
                result.chunks_invalidated += cur.rowcount

        sources = [row["document_number"] for row in rows]
        cur.execute("DELETE FROM document_relations WHERE source_number = ANY(%s)", (sources,))
        relations = {
            (r["source"], r["target"], r["type"]): r
            for r in catalog.get("relations", [])
            if r["source"] in sources
        }
        cur.executemany(
            """
            INSERT INTO document_relations
              (source_number, target_number, relation_type, effective_date, evidence)
            VALUES (%s, %s, %s, %s, %s)
            """,
            [
                (r["source"], r["target"], r["type"], r["effective"], r["evidence"])
                for r in relations.values()
            ],
        )
        result.relations = len(relations)
    log.info("Nạp xong: %s", result)
    return result
