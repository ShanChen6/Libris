"""Task 1.3 – Chuẩn hóa siêu dữ liệu và suy ra trạng thái hiệu lực.

Nguồn dữ liệu không cung cấp trạng thái hiệu lực, nên trạng thái được suy ra từ chính nội dung các
văn bản trong kho, kèm câu trích dẫn làm bằng chứng (``evidence``):

- "<X> ... hết hiệu lực kể từ ngày <văn bản này> có hiệu lực" -> X bị thay thế (EXPIRED)
- "Các nghị định sau đây hết hiệu lực ...:" + a), b), ...   -> từng văn bản bị thay thế
- "Bãi bỏ <Điều/khoản/...> của <X>"                         -> X bị bãi bỏ một phần (AMENDED)
- "Bãi bỏ <X>"                                              -> X bị bãi bỏ (EXPIRED)
- Trích yếu "Sửa đổi, bổ sung ... <X>"                       -> X bị sửa đổi (AMENDED)
- "<X> ... có hiệu lực thi hành từ ngày D" (văn bản khác)    -> ngày hiệu lực của X là D

Trạng thái tại thời điểm ``as_of``:
  PENDING  – chưa đến ngày có hiệu lực
  EXPIRED  – đã bị thay thế/bãi bỏ toàn bộ và văn bản thay thế đã có hiệu lực
  AMENDED  – còn hiệu lực nhưng đã bị sửa đổi, bổ sung hoặc bãi bỏ một phần
  ACTIVE   – còn hiệu lực
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

Status = Literal["ACTIVE", "EXPIRED", "AMENDED", "PENDING"]
RelationType = Literal["replaces", "repeals_part", "amends", "sets_effective_date"]

_DOC_KINDS = (
    r"(?:Bộ luật|Luật|Pháp lệnh|Nghị quyết|Nghị định|Quyết định|Thông tư liên tịch|Thông tư)"
)
# Số hiệu: 45/2013/QH13, 168/2024/NĐ-CP, 38/2024/TT-BCA, 06/2012/TTLT-BTP-BNG ...
_NUMBER_RE = re.compile(r"\b(\d{1,4}/(?:19|20)\d{2}/[A-ZĐ][A-ZĐ0-9]*(?:-[A-ZĐ0-9]+)*)")
_REF_RE = re.compile(_DOC_KINDS + r"[^;:.]{0,250}?\bsố\s+" + _NUMBER_RE.pattern)
_SELF_RE = r"(?:Bộ luật|Luật|Pháp lệnh|Nghị quyết|Nghị định|Quyết định|Thông tư)\s+này"

_AMENDED_BY_CLAUSE_RE = re.compile(
    r"(?:đã|được)\s+(?:được\s+)?sửa đổi,?\s*bổ sung[^()]*?(?=\(|hết hiệu lực|;|$)"
)
_EXPIRE_RE = re.compile(r"hết hiệu lực(?:\s+thi hành)?", re.IGNORECASE)
_EXPIRE_DATE_RE = re.compile(r"kể từ ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})")
_LIST_INTRO_RE = re.compile(r"sau đây\s+hết hiệu lực|hết hiệu lực[^:]*:\s*$", re.IGNORECASE)
_LIST_ITEM_RE = re.compile(r"^(?:[a-zđ]\)|[-–+])\s")
_REPEAL_RE = re.compile(r"^(?:[a-zđ\d]+[.)]\s*)?Bãi bỏ\s+(.*)$")
_PART_RE = re.compile(
    r"^(?:một số\s+)?(?:Điều|khoản|điểm|Chương|Mục|Phụ lục|nội dung|cụm từ)", re.I
)
_EFFECTIVE_RE = re.compile(
    r"có hiệu lực(?:\s+thi hành)?\s+(?:kể\s+)?từ ngày"
    r"\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})"
)
_TYPE_BY_SUFFIX = [
    (re.compile(r"/QH\d+$"), "Luật"),
    (re.compile(r"/NĐ-CP$"), "Nghị định"),
    (re.compile(r"/(?:TT|TTLT)-"), "Thông tư"),
    (re.compile(r"/QĐ-"), "Quyết định"),
    (re.compile(r"/NQ-|/NQ\d*$"), "Nghị quyết"),
    (re.compile(r"/UBTVQH\d+$"), "Pháp lệnh"),
]


def normalize_number(number: str) -> str:
    n = unicodedata.normalize("NFC", number).upper().replace("Ð", "Đ")
    return re.sub(r"\s+", "", n)


def normalize_document_type(raw_type: str | None, number: str) -> str | None:
    if raw_type:
        t = re.sub(r"\s+", " ", raw_type).strip().capitalize()
        if t in {"Luật", "Bộ luật"}:
            return "Luật"
        if t in {"Nghị định", "Thông tư", "Quyết định", "Nghị quyết", "Pháp lệnh", "Hiến pháp"}:
            return t
    for pattern, doc_type in _TYPE_BY_SUFFIX:
        if pattern.search(number):
            return doc_type
    return raw_type


def normalize_title(title: str | None) -> str | None:
    if not title:
        return title
    t = re.sub(r"\s+", " ", title).strip()
    t = re.sub(r"^Bộ Luật\b", "Bộ luật", t)
    if t.isupper():
        t = t.capitalize()
    return t


def _date(d: str, m: str, y: str) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


_QUOTED_RE = re.compile(r"[“\"][^”\"]*[”\"]")


def _refs(text: str) -> list[str]:
    """Số hiệu các văn bản được nhắc tới.

    Bỏ qua đoạn trích dẫn trong ngoặc kép và các văn bản 'đã được sửa đổi, bổ sung theo'.
    """
    text = _QUOTED_RE.sub(" ", text)
    text = _AMENDED_BY_CLAUSE_RE.sub(" ", text)
    seen: list[str] = []
    for m in _REF_RE.finditer(text):
        n = normalize_number(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


@dataclass
class Relation:
    type: RelationType
    source: str  # văn bản ban hành quy định
    target: str  # văn bản bị tác động
    evidence: str
    effective: date | None = None  # thời điểm quan hệ phát sinh hiệu lực


def extract_relations(number: str, title: str | None, text: str) -> list[Relation]:
    """Trích quan hệ giữa văn bản ``number`` và các văn bản khác.

    ``Relation.effective`` chỉ được gán khi văn bản nêu ngày cụ thể; ``None`` nghĩa là
    "kể từ ngày văn bản này có hiệu lực" và được xác định sau trong ``build_catalog``.
    """
    me = normalize_number(number)
    rels: list[Relation] = []

    def add(rtype: RelationType, target: str, evidence: str, when: date | None) -> None:
        if target != me and not any(r.type == rtype and r.target == target for r in rels):
            rels.append(Relation(rtype, me, target, evidence[:500], when))

    if title and re.match(r"(?:Luật\s+|Nghị định\s+)?sửa đổi,?\s*bổ sung", title, re.I):
        for target in _refs(title) or [normalize_number(n) for n in _NUMBER_RE.findall(title)]:
            add("amends", target, title, None)

    paragraphs = text.split("\n")
    for i, p in enumerate(paragraphs):
        # Ngày hiệu lực của văn bản khác do văn bản này quy định
        if _EFFECTIVE_RE.search(p) and not re.search(_SELF_RE + r"\s+có hiệu lực", p):
            m = _EFFECTIVE_RE.search(p)
            assert m is not None
            before = p[: m.start()]
            targets = _refs(before)
            when = _date(*m.groups())
            # Bỏ qua khi chỉ một phần (Điều/khoản/điểm) của văn bản kia có ngày hiệu lực riêng
            partial = re.search(r"\b(?:Điều|khoản|điểm)\s+\d", before, re.IGNORECASE)
            if len(targets) == 1 and when and not partial:
                add("sets_effective_date", targets[0], p, when)

        # Hết hiệu lực
        if _EXPIRE_RE.search(p):
            m_date = _EXPIRE_DATE_RE.search(p)
            when = _date(*m_date.groups()) if m_date else None
            if _LIST_INTRO_RE.search(p):
                for item in paragraphs[i + 1 :]:
                    if not _LIST_ITEM_RE.match(item):
                        break
                    for target in _refs(item)[:1]:
                        add("replaces", target, f"{p} {item}", when)
            else:
                subject = p[: _EXPIRE_RE.search(p).start()]  # type: ignore[union-attr]
                # "... có hiệu lực từ ngày Nghị quyết số X hết hiệu lực": X chỉ là mốc thời gian
                subject = re.split(r"(?:kể\s+)?từ ngày\s+(?=" + _DOC_KINDS + ")", subject)[0]
                for target in _refs(subject):
                    add("replaces", target, p, when)

        # Bãi bỏ
        m_rep = _REPEAL_RE.match(p)
        if m_rep:
            obj = m_rep.group(1)
            partial = _PART_RE.match(obj) is not None
            items = [obj]
            if obj.rstrip().endswith(":"):
                items = []
                for it in paragraphs[i + 1 :]:
                    if not _LIST_ITEM_RE.match(it):
                        break
                    items.append(it)
            for item in items:
                targets = _refs(item)
                if not targets:
                    continue
                part = partial or _PART_RE.match(re.sub(r"^\W+|^[a-zđ]\)\s*", "", item)) is not None
                # "Bãi bỏ Điều 57 của Luật A; Điều 2 của Luật B" -> mỗi văn bản bị bãi bỏ một phần
                rtype: RelationType = "repeals_part" if part else "replaces"
                for target in targets if part else targets[:1]:
                    add(rtype, target, f"{p} {item}" if item is not obj else p, None)
    return rels


@dataclass
class CatalogEntry:
    source_id: str
    document_number: str
    document_type: str | None
    title: str | None
    issuing_body: str | None
    signer: str | None
    issue_date: date | None
    effective_date: date | None
    status: Status
    expiry_date: date | None = None
    replaced_by: list[str] = field(default_factory=list)
    amended_by: list[str] = field(default_factory=list)
    replaces: list[str] = field(default_factory=list)
    amends: list[str] = field(default_factory=list)
    evidence: list[dict[str, str]] = field(default_factory=list)
    source_url: str | None = None
    needs_review: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("issue_date", "effective_date", "expiry_date"):
            d[k] = d[k].isoformat() if d[k] else None
        return d


def _self_effective_date(text: str) -> date | None:
    m = re.search(_SELF_RE + r"\s+" + _EFFECTIVE_RE.pattern, text)
    return _date(*m.groups()) if m else None


def build_catalog(records: list[dict[str, Any]], as_of: date) -> list[CatalogEntry]:
    entries: dict[str, CatalogEntry] = {}
    relations: list[Relation] = []

    for rec in records:
        meta = rec["metadata"]
        number = normalize_number(meta["document_number"])
        site_eff = date.fromisoformat(meta["effective_date"]) if meta["effective_date"] else None
        text_eff = _self_effective_date(rec["text"])
        entry = CatalogEntry(
            source_id=meta["source_id"],
            document_number=number,
            document_type=normalize_document_type(meta.get("document_type"), number),
            title=normalize_title(meta.get("title")),
            issuing_body=meta.get("issuing_body"),
            signer=meta.get("signer"),
            issue_date=date.fromisoformat(meta["issue_date"]) if meta["issue_date"] else None,
            effective_date=site_eff or text_eff,
            status="ACTIVE",
            source_url=meta.get("url"),
            needs_review=rec["extraction"]["needs_review"],
        )
        if site_eff and text_eff and site_eff != text_eff:
            entry.warnings.append(
                f"Ngày hiệu lực trên trang nguồn ({site_eff}) khác nội dung văn bản ({text_eff})"
            )
        entries[number] = entry
        relations += extract_relations(number, entry.title, rec["text"])

    def ev(r: Relation) -> dict[str, str]:
        return {"type": r.type, "source": r.source, "target": r.target, "text": r.evidence}

    # Ngày hiệu lực do văn bản khác quy định (VD: luật sửa đổi cho phép có hiệu lực sớm hơn)
    for r in relations:
        target = entries.get(r.target)
        if r.type == "sets_effective_date" and target and r.effective:
            if target.effective_date != r.effective:
                target.warnings.append(
                    f"Ngày hiệu lực {target.effective_date} được điều chỉnh thành {r.effective} "
                    f"theo {r.source}"
                )
                target.effective_date = r.effective
            target.evidence.append(ev(r))

    # Quan hệ không nêu ngày cụ thể phát sinh từ ngày văn bản nguồn có hiệu lực (đã chuẩn hóa)
    for r in relations:
        src = entries.get(r.source)
        if r.effective is None and src is not None:
            r.effective = src.effective_date

    for r in relations:
        src, target = entries.get(r.source), entries.get(r.target)
        if src is None or r.type == "sets_effective_date":
            continue
        if r.type == "replaces":
            src.replaces.append(r.target)
        elif r.type in ("amends", "repeals_part"):
            src.amends.append(r.target)
        if target is None:
            continue
        target.evidence.append(ev(r))
        in_force = r.effective is not None and r.effective <= as_of
        if r.type == "replaces":
            target.replaced_by.append(r.source)
            if in_force and (target.expiry_date is None or r.effective < target.expiry_date):  # type: ignore[operator]
                target.expiry_date = r.effective
        elif in_force:
            target.amended_by.append(r.source)

    for e in entries.values():
        if e.effective_date and e.effective_date > as_of:
            e.status = "PENDING"
        elif e.expiry_date and e.expiry_date <= as_of:
            e.status = "EXPIRED"
        elif e.amended_by:
            e.status = "AMENDED"
        else:
            e.status = "ACTIVE"
        if e.effective_date is None:
            e.warnings.append("Không xác định được ngày có hiệu lực")
    return sorted(entries.values(), key=lambda e: (e.issue_date or date.min, e.document_number))


def load_records(processed_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(processed_dir.glob("*.json"))]


def write_catalog(entries: list[CatalogEntry], path: Path, as_of: date) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"as_of": as_of.isoformat(), "documents": [e.to_dict() for e in entries]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
