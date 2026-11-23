"""POST /ingest, GET /ingest/{id} – nạp văn bản Admin tải lên (Task 4.1, gọi từ libris-api)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app.api.search import EmbedderDep, SettingsDep
from app.ingestion.service import IngestError, UploadedDocument, create_job, get_job, run_job

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _upload_dir(settings) -> Path:
    path = Path(settings.upload_dir)
    return path if path.is_absolute() else Path(__file__).resolve().parents[2] / path


@router.post("", status_code=202)
async def ingest(
    settings: SettingsDep,
    embedder: EmbedderDep,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    document_number: Annotated[str, Form(min_length=3, max_length=100)],
    title: Annotated[str, Form(min_length=1, max_length=1000)],
    document_type: Annotated[str | None, Form()] = None,
    issuing_body: Annotated[str | None, Form()] = None,
    signer: Annotated[str | None, Form()] = None,
    issue_date: Annotated[date | None, Form()] = None,
    effective_date: Annotated[date | None, Form()] = None,
    created_by: Annotated[UUID | None, Form()] = None,
) -> dict[str, Any]:
    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File vượt quá {settings.max_upload_mb} MB")
    upload_dir = _upload_dir(settings)
    doc = UploadedDocument(
        filename=file.filename or "upload",
        content_type=file.content_type,
        data=data,
        document_number=document_number,
        title=title,
        document_type=document_type,
        issuing_body=issuing_body,
        signer=signer,
        issue_date=issue_date,
        effective_date=effective_date,
        created_by=str(created_by) if created_by else None,
    )
    try:
        with psycopg.connect(settings.database_url) as conn:
            job_id = create_job(conn, doc, upload_dir)
    except IngestError as exc:
        raise HTTPException(422, str(exc)) from exc
    background.add_task(run_job, settings.database_url, job_id, embedder, upload_dir)
    return {"job_id": job_id, "status": "queued"}


@router.get("/{job_id}")
def ingest_status(job_id: UUID, settings: SettingsDep) -> dict[str, Any]:
    with psycopg.connect(settings.database_url) as conn:
        job = get_job(conn, str(job_id))
    if job is None:
        raise HTTPException(404, "Không tìm thấy job")
    return job
