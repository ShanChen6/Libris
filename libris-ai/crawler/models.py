from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class ListingItem:
    source_id: str
    document_number: str
    issue_date: date | None
    title: str
    url: str


@dataclass
class Attachment:
    url: str
    filename: str


@dataclass
class DocumentDetail:
    source: str
    source_id: str
    url: str
    document_number: str
    document_type: str | None
    issuing_body: str | None
    signer: str | None
    title: str | None
    issue_date: date | None
    effective_date: date | None
    attachments: list[Attachment] = field(default_factory=list)
    raw_fields: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("issue_date", "effective_date"):
            d[k] = d[k].isoformat() if d[k] else None
        return d
