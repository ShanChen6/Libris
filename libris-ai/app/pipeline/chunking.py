"""Task 2.1 – Cắt văn bản pháp luật theo cấu trúc phân cấp (Hierarchical Chunking).

Nhận diện cấu trúc Phần → Chương → Mục → Điều → Khoản → Điểm trên văn bản đã làm sạch (mỗi đơn vị
cấu trúc bắt đầu một dòng), rồi cắt thành các đoạn:

- Điều ngắn (≤ ``max_chars``): cả Điều là một đoạn.
- Điều dài: mỗi Khoản một đoạn; phần mở đầu ngắn của Điều được gộp vào Khoản đầu tiên.
- Khoản quá dài: tách theo nhóm Điểm liên tiếp; câu dẫn của Khoản (VD "Phạt tiền từ 400.000 đồng
  đến 600.000 đồng đối với ... sau đây:") được đưa vào tiền tố ngữ cảnh của mọi nhóm.
- Phần "Căn cứ ban hành" và từng Phụ lục / Mẫu biểu thành đoạn riêng; khối chữ ký, nơi nhận bị bỏ.

Mỗi đoạn có tiền tố ngữ cảnh, VD:
``[Văn bản: Nghị định 168/2024/NĐ-CP | Chương II: ... | Điều 7: Xử phạt ... | Khoản 2]``
và vị trí ``char_start``/``char_end`` trỏ đúng vào ``full_text`` (``content == full_text[s:e]``).

Văn bản OCR có thể sai số Chương ("Chương HI") hoặc mất tiêu đề Điều, nên mọi số thứ tự được kiểm
tra tăng dần: tiêu đề nhảy số bất thường được coi là nội dung, số Điều bị thiếu được báo cáo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.pipeline.vn import POINT_LETTERS, fz

DEFAULT_MAX_CHARS = 1800
MAX_ARTICLE_GAP = 15  # số Điều tối đa có thể bị OCR bỏ sót giữa hai tiêu đề liên tiếp
MAX_CLAUSE_GAP = 2
MAX_POINT_GAP = 2

_NO_QUOTE = r"^[^\w“\"]{0,3}"  # cho phép ký tự rác OCR ở đầu dòng, nhưng không cho ngoặc kép
# Tiền tố rác OCR: tối đa 3 ký hiệu, hoặc 1-2 chữ cái lạc đứng riêng ("À Điều 2.", "° — Điều 41.")
_ARTICLE_RE = re.compile(
    r"^(?P<pre>[^\w\s]{0,3}\s*|\w{1,2}\s+[^\w\s]{0,2}\s*)" + fz("Điều")
    + r"\s*([\dIl|]{1,3})\s*([a-zđ]?)\s*(?:[.:,]\s*(.*)|\s+(\S.*))$"
)  # fmt: skip
_OCR_DIGITS = str.maketrans({"I": "1", "l": "1", "|": "1"})
_CHAPTER_RE = re.compile(_NO_QUOTE + fz("Chương") + r"(?![a-zà-ỹ])\s*([^\s.:,]*)\s*[.:,-]?\s*(.*)$")
_SECTION_RE = re.compile(_NO_QUOTE + fz("Mục") + r"\s*(\d{1,2})(?!\d)\s*[^\w\s]*\s*(.*)$")
_PART_RE = re.compile(_NO_QUOTE + r"(?:PHẦN|Phần)\s+(THỨ\s+[A-ZĐÀ-Ỹ]+|[IVXLC]+)\b\s*[.:]?\s*(.*)$")
_CLAUSE_RE = re.compile(_NO_QUOTE + r"(\d{1,3})\s*[.,]\s+(\S.*)$")
# OCR đọc nhầm số đầu Khoản thành ký hiệu: "%, Phạt tiền từ 4.000.000 đồng..." (Khoản 5 Điều 6
# NĐ 168/2024). Chỉ nhận khi: 1-2 ký hiệu hay bị nhầm với chữ số + "." hoặc "," + chữ hoa,
# Khoản trước đã kết thúc bằng dấu chấm; số Khoản = số Khoản trước + 1.
_OCR_CLAUSE_RE = re.compile(
    r"^[^\w“\"]{0,2}([%§$&?!SsIlLOoBgZz]{1,2})\s*[.,]\s+([A-ZĐÀ-Ỹ]\S*\s+\S.*)$"
)
_POINT_RE = re.compile(_NO_QUOTE + r"([a-zđ])\s*\)\s*(.*)$")
_PREAMBLE_RE = re.compile(r"^\W*" + fz("Căn cứ"))
_END_OF_BODY_RE = re.compile(
    r"^\W*(?:" + fz("Nơi nhận") + r"\s*:|(?:TM|KT|T/M)\.\s*[A-ZĐ]"
    + r"|(?:CHỦ|CHU)\s+TỊCH\b|THỦ\s+TƯỚNG\b|BỘ\s+TRƯỞNG\b)"
)  # fmt: skip
# Khối chữ ký đôi khi bị OCR dồn vào giữa dòng ("M* nhỆn: + Đ TM. CHÍNH PHỦ Ban Bí thư ...")
_SIGNATURE_ANYWHERE_RE = re.compile(
    r"\b(?:TM|KT|T/M)\.\s*(?:CHÍNH\s+PHỦ|QUỐC\s+HỘI|ỦY\s+BAN|BỘ\s+TRƯỞNG|THỦ\s+TƯỚNG|CHỦ\s+TỊCH)"
)
_FILED_RE = re.compile(r"^\W*" + fz("Lưu") + r"\s*:")  # "Lưu: VT, NN" – dòng cuối của nơi nhận
_APPENDIX_RE = re.compile(r"^\W*(?:PHỤ\s+LỤC|Phụ\s+lục\s+[IVXLC\d]+|" + fz("Mẫu số") + r"\s+\S)")

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def to_roman(n: int) -> str:
    out = ""
    for value, sym in ((100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
                       (5, "V"), (4, "IV"), (1, "I")):  # fmt: skip
        while n >= value:
            out += sym
            n -= value
    return out


def from_roman(s: str) -> int | None:
    s = s.upper()
    if not s or any(c not in _ROMAN for c in s):
        return None
    total = 0
    for i, c in enumerate(s):
        v = _ROMAN[c]
        total += -v if i + 1 < len(s) and _ROMAN[s[i + 1]] > v else v
    return total if to_roman(total) == s else None


def _letters(text: str) -> list[str]:
    return [c for c in text if c.isalpha()]


def _is_upper(text: str) -> bool:
    letters = _letters(text)
    return len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) >= 0.7


def _looks_like_heading_rest(rest: str) -> bool:
    """Phần sau "Chương II"/"Mục 1" là tiêu đề (chữ hoa) hoặc rác OCR ngắn, không phải câu văn."""
    rest = rest.strip()
    return not rest or _is_upper(rest) or len(rest) <= 12


@dataclass
class Para:
    text: str
    start: int
    end: int


@dataclass
class Clause:
    label: str  # "Khoản 2"
    paras: list[Para] = field(default_factory=list)
    # Vị trí (trong paras) bắt đầu của từng Điểm: [(chữ cái, index), ...]
    points: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class Article:
    number: int
    label: str  # "Điều 7" / "Điều 7a"
    title: str
    part: str | None
    chapter: str | None
    section: str | None
    paras: list[Para] = field(default_factory=list)
    clauses: list[Clause] = field(default_factory=list)
    intro_end: int = 1  # số đoạn văn trước Khoản đầu tiên (gồm dòng tiêu đề)


@dataclass
class Chunk:
    chunk_index: int
    context_prefix: str
    content: str
    char_start: int
    char_end: int
    part: str | None = None
    chapter: str | None = None
    section: str | None = None
    article: str | None = None
    article_title: str | None = None
    clause: str | None = None
    point: str | None = None


@dataclass
class ParseReport:
    articles: int = 0
    last_article: int = 0
    missing_articles: list[int] = field(default_factory=list)
    rejected_headings: list[str] = field(default_factory=list)
    appendices: int = 0


@dataclass
class ParsedDocument:
    preamble: list[Para]
    articles: list[Article]
    appendices: list[tuple[str, list[Para]]]
    report: ParseReport


def split_paragraphs(full_text: str) -> list[Para]:
    paras: list[Para] = []
    pos = 0
    for line in full_text.split("\n"):
        if line.strip():
            paras.append(Para(line, pos, pos + len(line)))
        pos += len(line) + 1
    return paras


def _accept_number(num: int, last: int, gap: int) -> bool:
    return (last == 0 and 1 <= num <= 1 + gap) or (last < num <= last + 1 + gap)


def parse(full_text: str) -> ParsedDocument:
    paras = split_paragraphs(full_text)
    report = ParseReport()
    preamble: list[Para] = []
    articles: list[Article] = []
    appendices: list[tuple[str, list[Para]]] = []

    part: str | None = None
    chapter: str | None = None
    chapter_count = 0
    section: str | None = None
    last_section = 0
    pending_title: str | None = None  # "chapter" | "section" | "part": dòng sau có thể là tiêu đề
    mode = "preamble"  # preamble -> body -> closing -> appendix
    article: Article | None = None

    def set_title(kind: str, title: str) -> None:
        nonlocal chapter, section, part
        if kind == "chapter" and chapter:
            chapter = f"{chapter.split(':')[0]}: {title}"
        elif kind == "section" and section:
            section = f"{section.split(':')[0]}: {title}"
        elif kind == "part" and part:
            part = f"{part.split(':')[0]}: {title}"

    for p in paras:
        text = p.text

        if mode == "appendix":
            if _APPENDIX_RE.match(text):
                appendices.append((text, [p]))
            else:
                appendices[-1][1].append(p)
            continue

        if mode == "closing":
            # Sau khối chữ ký chỉ còn Phụ lục / Mẫu biểu là đáng giữ lại
            if _APPENDIX_RE.match(text):
                mode = "appendix"
                appendices.append((text, [p]))
            elif _FILED_RE.match(text):
                # Hết danh sách nơi nhận: phần sau (nếu có) là phụ lục chưa rõ tiêu đề
                mode = "appendix"
                appendices.append(("Phụ lục", []))
            continue

        if article is not None and (
            _END_OF_BODY_RE.match(text) or _SIGNATURE_ANYWHERE_RE.search(text)
        ):
            mode = "closing"
            article = None
            continue

        if pending_title and _is_upper(text) and not _ARTICLE_RE.match(text):
            set_title(pending_title, text)
            pending_title = None
            continue
        pending_title = None

        m = _PART_RE.match(text)
        if m and _looks_like_heading_rest(m.group(2)):
            part = f"Phần {m.group(1).title()}"
            if m.group(2).strip():
                set_title("part", m.group(2).strip())
            else:
                pending_title = "part"
            chapter, section, article = None, None, None
            mode = "body"
            continue

        m = _CHAPTER_RE.match(text)
        if m and _looks_like_heading_rest(m.group(2)):
            chapter_count += 1
            parsed = from_roman(m.group(1)) if m.group(1) else None
            if parsed and chapter_count <= parsed <= chapter_count + 2:
                chapter_count = parsed
            chapter = f"Chương {to_roman(chapter_count)}"
            rest = m.group(2).strip()
            if rest and _is_upper(rest):
                set_title("chapter", rest)
            else:
                pending_title = "chapter"
            section, last_section, article = None, 0, None
            mode = "body"
            continue
        elif m and m.group(1) and from_roman(m.group(1)):
            report.rejected_headings.append(text[:80])

        m = _SECTION_RE.match(text)
        if m and mode == "body" and _looks_like_heading_rest(m.group(2)):
            num = int(m.group(1))
            if _accept_number(num, last_section, 1):
                last_section = num
                section = f"Mục {num}"
                rest = m.group(2).strip()
                if rest and _is_upper(rest):
                    set_title("section", rest)
                else:
                    pending_title = "section"
                article = None
                continue

        m = _ARTICLE_RE.match(text)
        if m and m.group(5) and not m.group(5)[0].isupper():
            m = None  # "Điều 5 của Luật này ..." là câu văn, không phải tiêu đề
        if m:
            digits = m.group(2).translate(_OCR_DIGITS)
            num = int(digits) if digits.isdigit() else -1
            quoted = any(q in m.group("pre") for q in '“"')
            ok = _accept_number(num, report.last_article, MAX_ARTICLE_GAP)
            # Ngoặc kép trước "Điều" thường là trích dẫn trong luật sửa đổi; chỉ chấp nhận khi
            # đúng số kế tiếp (ngoặc kép giả do OCR)
            if ok and (not quoted or num == report.last_article + 1):
                report.missing_articles += range(report.last_article + 1, num)
                report.last_article = num
                report.articles += 1
                title = (m.group(4) or m.group(5) or "").strip()
                article = Article(
                    number=num,
                    label=f"Điều {num}{m.group(3)}",
                    title=title,
                    part=part,
                    chapter=chapter,
                    section=section,
                    paras=[p],
                )
                articles.append(article)
                mode = "body"
                continue
            report.rejected_headings.append(text[:80])

        if article is None:
            if mode == "preamble" and (preamble or _PREAMBLE_RE.match(text)):
                preamble.append(p)
            continue

        _add_to_article(article, p)

    # Bỏ phụ lục rỗng (VD: sau dòng "Lưu:" chỉ còn tên người ký)
    appendices = [(h, ps) for h, ps in appendices if sum(len(p.text) for p in ps) >= 200]
    report.appendices = len(appendices)
    return ParsedDocument(preamble, articles, appendices, report)


def _add_to_article(article: Article, p: Para) -> None:
    m = _CLAUSE_RE.match(p.text)
    last_clause = int(article.clauses[-1].label.split()[-1]) if article.clauses else 0
    if m and _accept_number(int(m.group(1)), last_clause, MAX_CLAUSE_GAP):
        article.clauses.append(Clause(label=f"Khoản {int(m.group(1))}", paras=[p]))
        return
    if (
        article.clauses
        and _OCR_CLAUSE_RE.match(p.text)
        and article.clauses[-1].paras[-1].text.rstrip().endswith(".")
    ):
        article.clauses.append(Clause(label=f"Khoản {last_clause + 1}", paras=[p]))
        return
    if not article.clauses:
        article.paras.append(p)
        article.intro_end = len(article.paras)
        return

    clause = article.clauses[-1]
    m = _POINT_RE.match(p.text)
    if m:
        letter = m.group(1)
        last_idx = POINT_LETTERS.index(clause.points[-1][0]) if clause.points else -1
        idx = POINT_LETTERS.index(letter) if letter in POINT_LETTERS else -99
        if (last_idx == -1 and idx in (0, 1)) or last_idx < idx <= last_idx + 1 + MAX_POINT_GAP:
            clause.points.append((letter, len(clause.paras)))
    clause.paras.append(p)


def _span(paras: list[Para]) -> tuple[int, int]:
    return paras[0].start, paras[-1].end


def document_label(document_type: str | None, number: str, title: str | None) -> str:
    """'Luật Đất đai 31/2024/QH15' / 'Nghị định 168/2024/NĐ-CP'."""
    if document_type == "Luật" and title and re.match(r"(?:Bộ\s+)?[Ll]uật\s+\S", title):
        short = re.split(r"\s+(?:số|sửa đổi)\b", title)[0]
        if len(short) <= 80:
            return f"{short} {number}"
    return f"{document_type or 'Văn bản'} {number}"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _short_heading(text: str | None, limit: int = 90) -> str | None:
    """Rút gọn tiêu đề trong tiền tố: tên Chương/Mục viết hoa dài lặp lại ở mọi đoạn."""
    if not text:
        return text
    label, sep, title = text.partition(": ")
    if sep and _is_upper(title):
        title = title.capitalize()
    return f"{label}{sep}{_truncate(title, limit)}" if sep else _truncate(label, limit)


def _prefix(doc_label: str, *parts: str | None) -> str:
    """[Văn bản: ... | Chương II: ... | Điều 7: ... | Khoản 2]. Khoản (phần cuối) giữ nguyên."""
    items = [p for p in parts if p]
    head = [_short_heading(p) for p in items[:-1]]
    tail = (
        items[-1:]
        if items and items[-1].startswith("Khoản")
        else [_short_heading(p, 160) for p in items[-1:]]
    )
    return "[" + " | ".join([f"Văn bản: {doc_label}", *[p for p in head + tail if p]]) + "]"


def _pieces(p: Para, max_chars: int) -> list[Para]:
    """Tách đoạn văn quá dài (VD: bảng phụ lục bị OCR thành một dòng) theo ranh giới câu."""
    pieces: list[Para] = []
    text, s = p.text, 0
    while len(text) - s > max_chars:
        window = text[s : s + max_chars]
        cut = max(window.rfind(". "), window.rfind("; "), window.rfind(": "))
        if cut < max_chars * 0.4:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = max_chars - 1
        e = s + cut + 1
        piece = text[s:e].rstrip()
        pieces.append(Para(piece, p.start + s, p.start + s + len(piece)))
        s = e
        while s < len(text) and text[s] == " ":
            s += 1
    if s < len(text):
        pieces.append(Para(text[s:], p.start + s, p.end))
    return pieces


Unit = tuple[str | None, list[Para]]  # (chữ cái Điểm nếu có, các đoạn văn)


def _pack(units: list[Unit], max_chars: int) -> list[list[Unit]]:
    """Gom các đơn vị liên tiếp thành cửa sổ có độ dài ≤ max_chars.

    Đơn vị dài hơn max_chars được tách nhỏ theo đoạn văn, rồi theo câu.
    """
    flat: list[Unit] = []
    for letter, paras in units:
        if paras[-1].end - paras[0].start <= max_chars:
            flat.append((letter, paras))
        else:
            flat += [(letter, [piece]) for para in paras for piece in _pieces(para, max_chars)]
    windows: list[list[Unit]] = []
    for unit in flat:
        if windows and unit[1][-1].end - windows[-1][0][1][0].start <= max_chars:
            windows[-1].append(unit)
        else:
            windows.append([unit])
    return windows


def _paras(window: list[Unit]) -> list[Para]:
    return [p for _, paras in window for p in paras]


def build_chunks(
    full_text: str,
    *,
    document_type: str | None,
    document_number: str,
    title: str | None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> tuple[list[Chunk], ParseReport]:
    parsed = parse(full_text)
    label = document_label(document_type, document_number, title)
    chunks: list[Chunk] = []

    def emit(paras: list[Para], prefix: str, **fields: str | None) -> None:
        start, end = _span(paras)
        chunks.append(
            Chunk(
                chunk_index=len(chunks),
                context_prefix=prefix,
                content=full_text[start:end],
                char_start=start,
                char_end=end,
                **fields,
            )
        )

    def emit_windows(units: list[Unit], prefix: str, **fields: str | None) -> None:
        for window in _pack(units, max_chars):
            emit(_paras(window), prefix, **fields)

    if parsed.preamble:
        emit_windows(
            [(None, [p]) for p in parsed.preamble],
            _prefix(label, "Căn cứ ban hành"),
            article_title="Căn cứ ban hành",
        )

    for art in parsed.articles:
        heading = f"{art.label}: {art.title}" if art.title else art.label
        common = {
            "part": art.part,
            "chapter": art.chapter,
            "section": art.section,
            "article": art.label,
            "article_title": art.title or None,
        }
        art_prefix = _prefix(label, art.part, art.chapter, art.section, heading)
        all_paras = art.paras + [p for c in art.clauses for p in c.paras]
        start, end = _span(all_paras)
        if end - start <= max_chars:
            emit(all_paras, art_prefix, **common)
            continue
        if not art.clauses:
            emit_windows([(None, [p]) for p in all_paras], art_prefix, **common)
            continue

        clauses = list(art.clauses)
        intro = art.paras
        if intro[-1].end - intro[0].start <= 300:
            # Phần mở đầu ngắn (thường chỉ là dòng tiêu đề Điều) gộp vào Khoản đầu tiên
            first = clauses[0]
            clauses[0] = Clause(
                first.label, intro + first.paras, [(x, i + len(intro)) for x, i in first.points]
            )
        else:
            emit_windows([(None, [p]) for p in intro], art_prefix, **common)

        for clause in clauses:
            clause_prefix = _prefix(
                label, art.part, art.chapter, art.section, heading, clause.label
            )
            c_start, c_end = _span(clause.paras)
            if c_end - c_start <= max_chars or not clause.points:
                emit_windows(
                    [(None, [p]) for p in clause.paras],
                    clause_prefix,
                    clause=clause.label,
                    **common,
                )
                continue

            # Tách theo Điểm: đơn vị đầu là câu dẫn, mỗi Điểm (kèm đoạn tiếp theo) là một đơn vị
            bounds = [i for _, i in clause.points]
            lead = clause.paras[: bounds[0]]
            units: list[Unit] = [(None, lead)] if lead else []
            for k, (letter, b) in enumerate(clause.points):
                stop = bounds[k + 1] if k + 1 < len(bounds) else len(clause.paras)
                units.append((letter, clause.paras[b:stop]))
            lead_text = " ".join(p.text for p in lead if not _ARTICLE_RE.match(p.text))
            for window in _pack(units, max_chars):
                window_letters = list(dict.fromkeys(x for x, _ in window if x))
                starts_with_lead = bool(lead) and window[0][1][0] is lead[0]
                clause_ctx = (
                    clause.label
                    if starts_with_lead or not lead_text
                    else f"{clause.label}: {_truncate(lead_text, 400)}"
                )
                point = None
                if window_letters:
                    point = f"Điểm {window_letters[0]}"
                    if len(window_letters) > 1:
                        point += f"–{window_letters[-1]}"
                emit(
                    _paras(window),
                    _prefix(label, art.part, art.chapter, art.section, heading, clause_ctx),
                    clause=clause.label,
                    point=point,
                    **common,
                )

    for heading, paras in parsed.appendices:
        name = _truncate(heading, 120)
        emit_windows(
            [(None, [p]) for p in paras],
            _prefix(label, f"Phụ lục: {name}"),
            part="Phụ lục",
            article_title=name,
        )

    return chunks, parsed.report
