"""Pipeline: seed -> tra cứu docid -> chi tiết -> tải PDF -> trích xuất -> làm sạch -> lưu."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from crawler.clean import clean_text, is_colophon_page, strip_continuation_header
from crawler.extract import SUPPORTED_EXTENSIONS, UnsupportedDocument, extract_document
from crawler.http import FetchError, PoliteClient
from crawler.sources import vanban_chinhphu as vbcp

log = logging.getLogger(__name__)


@dataclass
class Seed:
    number: str
    org: str
    type: str | None = None
    source_id: str | None = None
    note: str | None = None


def normalize_number(number: str) -> str:
    n = unicodedata.normalize("NFC", number).upper().replace("Ð", "Đ")
    return re.sub(r"\s+", "", n)


def _number_year(number: str) -> int | None:
    m = re.search(r"/((?:19|20)\d{2})/", number)
    return int(m.group(1)) if m else None


def load_seeds(path: Path) -> list[Seed]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    allowed = set(Seed.__dataclass_fields__)
    seeds: list[Seed] = []
    for i, item in enumerate(raw.get("documents", []), start=1):
        unknown = set(item) - allowed
        if unknown:
            raise ValueError(f"{path}: mục #{i} có khóa không hợp lệ {sorted(unknown)}")
        item = {k: str(v) if v is not None else None for k, v in item.items()}
        seeds.append(Seed(**item))
    return seeds


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.raw = root / "raw" / vbcp.SOURCE
        self.processed = root / "processed" / vbcp.SOURCE
        self.resolved_path = self.raw / "resolved.json"

    def load_resolved(self) -> dict[str, str]:
        if self.resolved_path.exists():
            return json.loads(self.resolved_path.read_text(encoding="utf-8"))
        return {}

    def save_resolved(self, resolved: dict[str, str]) -> None:
        self.raw.mkdir(parents=True, exist_ok=True)
        self.resolved_path.write_text(
            json.dumps(resolved, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )

    def raw_dir(self, source_id: str) -> Path:
        return self.raw / source_id

    def processed_path(self, source_id: str) -> Path:
        return self.processed / f"{source_id}.json"

    def write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def resolve_seeds(
    client: PoliteClient, seeds: list[Seed], store: Store, *, max_pages: int = 60
) -> dict[str, str]:
    """Tìm docid cho các seed chưa biết bằng cách duyệt danh sách theo (cơ quan, loại)."""
    resolved = store.load_resolved()
    for s in seeds:
        if s.source_id:
            resolved[normalize_number(s.number)] = s.source_id

    pending: dict[tuple[str, str | None], set[str]] = defaultdict(set)
    for s in seeds:
        key = normalize_number(s.number)
        if key not in resolved:
            pending[(s.org, s.type)].add(key)

    for (org, doc_type), wanted in pending.items():
        years = [y for y in map(_number_year, wanted) if y]
        stop_before = date(min(years) - 1, 1, 1) if years else None
        log.info("Duyệt danh sách %s/%s để tìm %d văn bản", org, doc_type or "*", len(wanted))
        for item in vbcp.iter_listing(
            client, org=org, doc_type=doc_type, max_pages=max_pages, stop_before=stop_before
        ):
            key = normalize_number(item.document_number)
            if key in wanted:
                resolved[key] = item.source_id
                wanted.discard(key)
                log.info("  %s -> docid %s", item.document_number, item.source_id)
                store.save_resolved(resolved)
                if not wanted:
                    break
        for key in wanted:
            log.warning("  Không tìm thấy %s trong danh sách %s/%s", key, org, doc_type or "*")
    store.save_resolved(resolved)
    return resolved


def crawl_document(
    client: PoliteClient, source_id: str, store: Store, *, ocr: bool = True, force: bool = False
) -> dict[str, Any]:
    out_path = store.processed_path(source_id)
    if out_path.exists() and not force:
        log.info("docid %s đã có, bỏ qua (dùng --force để tải lại)", source_id)
        return json.loads(out_path.read_text(encoding="utf-8"))

    raw_dir = store.raw_dir(source_id)
    html = client.get_text(vbcp.detail_url(source_id))
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "detail.html").write_text(html, encoding="utf-8")
    detail = vbcp.parse_detail(html, source_id)
    log.info("%s – %s", detail.document_number, detail.title)

    pages_info: list[dict[str, Any]] = []
    texts: list[str] = []
    skipped: list[str] = []
    for att in detail.attachments:
        if not att.filename.lower().endswith(SUPPORTED_EXTENSIONS):
            skipped.append(att.filename)
            continue
        path = raw_dir / "files" / att.filename
        if not path.exists() or force:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(client.download(att.url))
        try:
            pages = extract_document(path.read_bytes(), att.filename, ocr=ocr)
        except (UnsupportedDocument, subprocess.CalledProcessError) as exc:
            log.warning("Không trích xuất được %s: %s", att.filename, exc)
            skipped.append(att.filename)
            continue
        kept = []
        for p in pages:
            dropped = is_colophon_page(p.text)
            if not dropped:
                kept.append(p.text)
            pages_info.append(
                {
                    "file": att.filename,
                    "page": p.page,
                    "method": p.method,
                    "chars": len(p.text),
                    "dropped": dropped,
                }
            )
        texts.append(strip_continuation_header("\n".join(kept)))

    methods = [p["method"] for p in pages_info if not p["dropped"]]
    record = {
        "metadata": detail.to_dict(),
        "text": clean_text("\n".join(texts)),
        "extraction": {
            "total_pages": len(pages_info),
            "ocr_pages": methods.count("ocr"),
            "empty_pages": methods.count("empty"),
            # Văn bản OCR hoặc thiếu chữ cần được rà soát trước khi đưa vào kho tri thức.
            "needs_review": bool(methods.count("ocr") or methods.count("empty")) or not pages_info,
            "skipped_attachments": skipped,
            "pages": pages_info,
        },
        "crawled_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    store.write_json(out_path, record)
    return record


def crawl_seeds(
    seeds_path: Path, data_dir: Path, *, ocr: bool = True, force: bool = False, delay: float = 1.0
) -> list[dict[str, Any]]:
    seeds = load_seeds(seeds_path)
    store = Store(data_dir)
    summary: list[dict[str, Any]] = []
    with PoliteClient(min_interval=delay) as client:
        resolved = resolve_seeds(client, seeds, store)
        for s in seeds:
            source_id = resolved.get(normalize_number(s.number))
            row: dict[str, Any] = {"number": s.number, "source_id": source_id}
            if source_id is None:
                row["status"] = "not_found"
            else:
                try:
                    rec = crawl_document(client, source_id, store, ocr=ocr, force=force)
                    row |= {
                        "status": "ok",
                        "title": rec["metadata"]["title"],
                        "pages": rec["extraction"]["total_pages"],
                        "ocr_pages": rec["extraction"]["ocr_pages"],
                        "needs_review": rec["extraction"]["needs_review"],
                    }
                except (FetchError, ValueError) as exc:
                    log.error("docid %s lỗi: %s", source_id, exc)
                    row["status"] = f"error: {exc}"
            summary.append(row)
    return summary
