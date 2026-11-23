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

# --- Regex chịu lỗi dấu của OCR -------------------------------------------------------------
# OCR tiếng Việt hay nhầm dấu ("hệt hiệu lực", "bỗ sung", "Điêu"), nên các cụm từ khóa được so khớp
# theo "họ" chữ cái: mọi biến thể dấu của cùng một chữ cái gốc đều được chấp nhận.
_VN_LETTERS = "aàáảãạăằắẳẵặâầấẩẫậeèéẻẽẹêềếểễệiìíỉĩịoòóỏõọôồốổỗộơờớởỡợuùúủũụưừứửữựyỳýỷỹỵdđ"


def _base_letter(c: str) -> str:
    return "d" if c in "đĐ" else unicodedata.normalize("NFD", c.lower())[0]


_FAMILIES: dict[str, set[str]] = {}
for _ch in _VN_LETTERS:
    _FAMILIES.setdefault(_base_letter(_ch), set()).update({_ch, _ch.upper()})


def _fz(phrase: str) -> str:
    """Regex khớp ``phrase`` bất kể sai lệch dấu và hoa/thường."""
    out: list[str] = []
    for c in phrase:
        if c == " ":
            out.append(r"\s+")
        elif c.lower() in _VN_LETTERS:
            out.append("[" + "".join(sorted(_FAMILIES[_base_letter(c)])) + "]")
        elif c.isalpha():
            out.append(f"[{c.lower()}{c.upper()}]")
        else:
            out.append(re.escape(c))
    return "".join(out)


_KINDS = [
    "Bộ luật", "Luật", "Pháp lệnh", "Nghị quyết", "Nghị định", "Quyết định",
    "Thông tư liên tịch", "Thông tư",
]  # fmt: skip
_DOC_KINDS = "(?:" + "|".join(_fz(k) for k in _KINDS) + ")"
# Số hiệu: 45/2013/QH13, 168/2024/NĐ-CP, 38/2024/TT-BCA, 06/2012/TTLT-BTP-BNG ...
# OCR đôi khi chèn khoảng trắng quanh dấu gạch ("NĐ- CP"); normalize_number sẽ bỏ khoảng trắng.
_NUMBER_RE = re.compile(
    r"\b(\d{1,4}/(?:19|20)\d{2}/[A-ZĐÐ][A-ZĐÐ0-9]*(?:\s?-\s?[A-ZĐÐ0-9]*[A-ZĐÐ][A-ZĐÐ0-9]*(?!\w))*)"
)
_REF_RE = re.compile(_DOC_KINDS + r"[^;:.]{0,250}?\b" + _fz("số") + r"\s+" + _NUMBER_RE.pattern)
_SELF_RE = _DOC_KINDS + r"\s+" + _fz("này")

_AMENDED_BY_CLAUSE_RE = re.compile(
    "(?:" + _fz("đã") + "|" + _fz("được") + r")\s+(?:" + _fz("được") + r"\s+)?"
    + _fz("sửa đổi") + r",?\s*" + _fz("bổ sung")
    + r"[^()]*?(?=\(|" + _fz("hết hiệu lực") + r"|;|$)"
)  # fmt: skip
_EXPIRE_RE = re.compile(_fz("hết hiệu lực") + r"(?:\s+" + _fz("thi hành") + ")?")
_DATE_TAIL = r"\s+(\d{1,2})\s+" + _fz("tháng") + r"\s+(\d{1,2})\s+" + _fz("năm") + r"\s+(\d{4})"
_FROM_DATE_RE = re.compile(_fz("kể từ ngày") + _DATE_TAIL)
_LIST_INTRO_RE = re.compile(
    _fz("sau đây") + r"\s+" + _EXPIRE_RE.pattern + "|" + _EXPIRE_RE.pattern + r"[^:]*:\s*$"
)
_LIST_ITEM_RE = re.compile(r"^(?:[a-zđ]\)|[-–+])\s")
_REPEAL_RE = re.compile(r"^\W*(?:[a-zđ\d]{1,2}[.)]?\s+)?" + _fz("Bãi bỏ") + r"\s+(.*)$")
_PART_RE = re.compile(
    r"^(?:" + _fz("một số") + r"\s+)?(?:"
    + "|".join(_fz(w) for w in ["Điều", "khoản", "điểm", "Chương", "Mục", "Phụ lục",
                                "nội dung", "cụm từ", "đoạn"])
    + ")"
)  # fmt: skip
_EFFECTIVE_RE = re.compile(
    _fz("có hiệu lực") + r"(?:\s+" + _fz("thi hành") + r")?\s+(?:" + _fz("kể") + r"\s+)?"
    + _fz("từ ngày") + _DATE_TAIL
)  # fmt: skip
_SELF_EFFECTIVE_RE = re.compile(_SELF_RE + r"\s+" + _EFFECTIVE_RE.pattern)
_SELF_REPLACES_RE = re.compile(_SELF_RE + r"\s+" + _fz("thay thế") + r"\s+(.*)$")
_ARTICLE_RE = re.compile(r"^" + _fz("Điều") + r"\s+\d+[a-zđ]?\s*\.")
_AMEND_RE = re.compile(_fz("sửa đổi"))
_PARTIAL_EFFECTIVE_RE = re.compile(
    r"\b(?:" + "|".join(_fz(w) for w in ["Điều", "khoản", "điểm"]) + r")\s+\d"
)
_NUMBERING_RE = re.compile(r"^\W*(?:\d{1,2}[.)]|[a-zđ]\))?\s*")
_PART_WORDS = "|".join(_fz(w) for w in ["Điều", "khoản", "điểm", "Chương", "Mục", "Phụ lục"])
# Ngay trước tên văn bản là "Điều 1 ", "khoản 2 Điều 86 của " ... -> chỉ một phần văn bản
_PART_PREFIX_RE = re.compile(
    r"(?:" + _PART_WORDS + r")\s+[\dIVXLa-zđ]+[.,]?\s*(?:" + _fz("của") + r"\s+)?$"
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


def _refs_detailed(text: str) -> list[tuple[str, bool]]:
    """(số hiệu, có phải chỉ một phần văn bản) cho các văn bản được nhắc tới.

    Bỏ qua đoạn trích dẫn trong ngoặc kép và các văn bản 'đã được sửa đổi, bổ sung theo'.
    """
    text = _QUOTED_RE.sub(" ", text)
    text = _AMENDED_BY_CLAUSE_RE.sub(" ", text)
    seen: dict[str, bool] = {}
    for m in _REF_RE.finditer(text):
        n = normalize_number(m.group(1))
        partial = _PART_PREFIX_RE.search(text[max(0, m.start() - 60) : m.start()]) is not None
        if n not in seen:
            seen[n] = partial
    return list(seen.items())


def _refs(text: str) -> list[str]:
    return [n for n, _ in _refs_detailed(text)]


def _is_partial(segment: str) -> bool:
    """'Điều 1 Nghị định số X', 'khoản 3 Điều 36 của Luật X'... -> chỉ một phần của X."""
    return _PART_RE.match(_NUMBERING_RE.sub("", segment)) is not None


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

    def add_segments(subject: str, evidence: str, when: date | None) -> None:
        # "Nghị định số A ...; Điều 1 Nghị định số B ..." -> A bị thay thế, B bị bãi bỏ một phần
        for target, partial in _refs_detailed(subject):
            add("repeals_part" if partial else "replaces", target, evidence, when)

    if title and re.match(r"(?:" + _DOC_KINDS + r"\s+)?" + _fz("sửa đổi"), title):
        for target in _refs(title) or [normalize_number(n) for n in _NUMBER_RE.findall(title)]:
            add("amends", target, title, None)

    # Ngữ cảnh: văn bản được nêu ở tiêu đề Điều hiện tại, VD
    # "Điều 52. Sửa đổi, bổ sung một số điều của Nghị định số 100/2019/NĐ-CP"
    context: list[str] = []
    context_amends = False

    paragraphs = text.split("\n")
    for i, p in enumerate(paragraphs):
        if _ARTICLE_RE.match(p):
            context = _refs(p)
            context_amends = _AMEND_RE.search(p) is not None
            if context_amends:
                for target in context:
                    add("amends", target, p, None)

        if p[:1] in '“"':
            # Nội dung trích dẫn thuộc văn bản bị sửa đổi, không phải của văn bản này. Chỉ dùng để
            # nhận biết ngày hiệu lực mới: Sửa đổi khoản 1 Điều 252 như sau: “1. Luật này có ..."
            m = _SELF_EFFECTIVE_RE.search(p)
            if m and context_amends and len(context) == 1:
                if not _PARTIAL_EFFECTIVE_RE.search(p[: m.start()]):
                    add("sets_effective_date", context[0], p, _date(*m.groups()[-3:]))
            continue

        # Ngày hiệu lực của văn bản khác do văn bản này quy định
        m = _EFFECTIVE_RE.search(p)
        if m and not _SELF_EFFECTIVE_RE.search(p):
            before = p[: m.start()]
            targets = _refs(before)
            when = _date(*m.groups())
            # Bỏ qua khi chỉ một phần (Điều/khoản/điểm) của văn bản kia có ngày hiệu lực riêng
            if len(targets) == 1 and when and not _PARTIAL_EFFECTIVE_RE.search(before):
                add("sets_effective_date", targets[0], p, when)

        # "Nghị định này thay thế Nghị định số X"
        m = _SELF_REPLACES_RE.search(p)
        if m:
            add_segments(m.group(1), p, None)

        # Hết hiệu lực
        m = _EXPIRE_RE.search(p)
        if m:
            m_date = _FROM_DATE_RE.search(p, m.end())
            when = _date(*m_date.groups()) if m_date else None
            if _LIST_INTRO_RE.search(p):
                for item in paragraphs[i + 1 :]:
                    if not _LIST_ITEM_RE.match(item):
                        break
                    add_segments(item, f"{p} {item}", when)
            else:
                subject = p[: m.start()]
                # "... có hiệu lực từ ngày Nghị quyết số X hết hiệu lực": X chỉ là mốc thời gian
                subject = re.split(_fz("từ ngày") + r"\s+(?=" + _DOC_KINDS + ")", subject)[0]
                add_segments(subject, p, when)

        # Bãi bỏ
        m = _REPEAL_RE.match(p)
        if m:
            obj = m.group(1)
            items = [obj]
            if obj.rstrip().endswith(":"):
                items = []
                for it in paragraphs[i + 1 :]:
                    if not _LIST_ITEM_RE.match(it):
                        break
                    items.append(it)
            for item in items:
                body = re.sub(r"^\W*[a-zđ]\)\s*(?:" + _fz("Bãi bỏ") + r"\s+)?", "", item)
                partial = _is_partial(obj) or _is_partial(body)
                targets = _refs(body)
                if not targets and context_amends and partial:
                    # "Bãi bỏ khoản 1 Điều 3;" trong Điều sửa đổi văn bản X -> bãi bỏ một phần X
                    targets = context
                evidence = p if item is obj else f"{p} {item}"
                rtype: RelationType = "repeals_part" if partial else "replaces"
                # "Bãi bỏ Điều 57 của Luật A; Điều 2 của Luật B" -> mỗi văn bản bị bãi bỏ một phần
                for target in targets if partial else targets[:1]:
                    add(rtype, target, evidence, None)
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
    for p in text.split("\n"):
        if p[:1] in '“"':
            continue
        m = _SELF_EFFECTIVE_RE.search(p)
        if m:
            return _date(*m.groups()[-3:])
    return None


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
        for name in ("replaced_by", "amended_by", "replaces", "amends"):
            setattr(e, name, list(dict.fromkeys(getattr(e, name))))
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
