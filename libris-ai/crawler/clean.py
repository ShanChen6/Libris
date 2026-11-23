"""Làm sạch văn bản pháp luật trích từ PDF.

- Chuẩn hóa Unicode NFC, khoảng trắng.
- Bỏ khối chữ ký số, header trang Công báo, số trang, ký tự rác OCR.
- Nối các dòng bị ngắt cứng trong cùng một đoạn, giữ nguyên ranh giới cấu trúc
  Phần / Chương / Mục / Điều / Khoản / Điểm (phục vụ Hierarchical Chunking ở Task 2.1).
"""

from __future__ import annotations

import re
import unicodedata

_SIGNATURE_RE = re.compile(
    r"^\W*(?:(?:Ký bởi|Email|Cơ quan|Thời gian ký)\s*:"
    r"|Người ký\s*:\s*CỔNG THÔNG TIN ĐIỆN TỬ)",
    re.IGNORECASE,
)
_CONTINUATION_RE = re.compile(r"^\W*\(?\s*Tiếp theo Công báo số[^)]*\)?\s*$", re.IGNORECASE)
_COLOPHON_MARKERS = ("In tại", "congbao.chinhphu.vn", "Giá:", "XUẤT BẢN")
_GAZETTE_HEADER_RE = re.compile(r"^\W*\d*\s*CÔNG BÁO\s*/\s*Số\b.*$", re.IGNORECASE)
_PAGE_NUMBER_RE = re.compile(r"^\W*\d{1,4}\W*$")
_OCR_JUNK_RE = re.compile(r"[|¬]")
_EDGE_JUNK_RE = re.compile(r"^[\s_'\"`.,:;\-–—~^]+(?=\S)|(?<=\S)[\s_'\"`~^\-–—]+$")

# Dòng mở đầu một đơn vị cấu trúc -> luôn bắt đầu đoạn mới.
_STRUCT_START_RE = re.compile(
    r"^(?:"
    r"(?:PHẦN|Phần)\s+(?:THỨ\s+)?[\wÀ-ỹ]+"
    r"|(?:CHƯƠNG|Chương)\s+[IVXLCDM\d]+"
    r"|(?:MỤC|Mục)\s+\d+"
    r"|Điều\s+\d+[a-zđ]?\."
    r"|\d+[a-zđ]?\.\s"
    r"|[a-zđ]\)\s"
    r"|[-–•+]\s"
    r"|[“\"]"
    r")"
)
# Dòng tiêu đề đứng riêng (Phần/Chương/Mục/Điều) -> đoạn sau cũng bắt đầu mới.
_HEADING_RE = re.compile(r"^(?:(?:PHẦN|Phần|CHƯƠNG|Chương|MỤC|Mục)\s+\S+$|Điều\s+\d+[a-zđ]?\.\s)")
_BROKEN_NUMBER_RE = re.compile(r"\b\d{1,4}/(?:19|20)\d{2}/[A-ZĐ][A-ZĐ0-9]*-?$")
_NUMBER_TAIL_RE = re.compile(r"^[A-ZĐ][A-ZĐ0-9]*(?:-[A-ZĐ0-9]+)*\b(?![a-zà-ỹ])")
_SENTENCE_END_RE = re.compile(r"[.:;!?”\"’)]$")


def is_colophon_page(text: str) -> bool:
    """Trang bìa sau của Công báo (thông tin xuất bản), không chứa nội dung văn bản."""
    if re.search(r"^\s*Điều\s+\d+", text, re.MULTILINE):
        return False
    return sum(marker.lower() in text.lower() for marker in _COLOPHON_MARKERS) >= 2


def strip_continuation_header(text: str, max_lines: int = 20) -> str:
    """Bỏ phần đầu '... (Tiếp theo Công báo số ...)' khi một văn bản bị tách nhiều số Công báo."""
    lines = text.splitlines()
    for i, line in enumerate(lines[:max_lines]):
        if _CONTINUATION_RE.match(line):
            return "\n".join(lines[i + 1 :])
    return text


def _is_upper_line(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def _clean_line(line: str) -> str:
    line = _OCR_JUNK_RE.sub(" ", line)
    line = re.sub(r"\s+", " ", line).strip()
    line = _EDGE_JUNK_RE.sub("", line).strip()
    return line


def clean_lines(raw: str) -> list[str]:
    text = unicodedata.normalize("NFC", raw).replace(" ", " ").replace("Ð", "Đ")
    lines: list[str] = []
    for line in text.splitlines():
        if _SIGNATURE_RE.match(line) or _GAZETTE_HEADER_RE.match(line):
            continue
        line = _clean_line(line)
        if not line or _PAGE_NUMBER_RE.match(line):
            continue
        if not any(c.isalnum() for c in line) or (len(line) <= 2 and not line.isdigit()):
            continue
        lines.append(line)
    return lines


def join_paragraphs(lines: list[str]) -> list[str]:
    paragraphs: list[str] = []
    for line in lines:
        if not paragraphs:
            paragraphs.append(line)
            continue
        prev = paragraphs[-1]
        starts_lower = line[0].islower()
        # Số hiệu bị ngắt dòng: "... Nghị định số 37/2019/NĐ" + "CP ngày 07 ..." / "NĐ-" + "CP"
        broken = _BROKEN_NUMBER_RE.search(prev)
        if broken and _NUMBER_TAIL_RE.match(line):
            sep = "" if prev.endswith("-") else "-"
            paragraphs[-1] = f"{prev}{sep}{line}"
            continue
        if _STRUCT_START_RE.match(line):
            new_paragraph = True
        elif starts_lower and not _HEADING_RE.match(prev):
            # Dòng bắt đầu bằng chữ thường luôn là phần tiếp của câu trước
            # (kể cả khi dòng trước kết thúc bằng "bao gồm:" hay ngắt trang).
            new_paragraph = False
        elif _SENTENCE_END_RE.search(prev):
            new_paragraph = True
        elif _HEADING_RE.match(prev):
            # Tên Điều/Chương xuống dòng thì dòng sau viết thường; nội dung mới viết hoa.
            new_paragraph = not starts_lower and not (
                _is_upper_line(prev.split(" ", 2)[-1]) and _is_upper_line(line)
            )
        elif _is_upper_line(prev) or _is_upper_line(line):
            new_paragraph = not (_is_upper_line(prev) and _is_upper_line(line))
        else:
            new_paragraph = False
        if new_paragraph:
            paragraphs.append(line)
        else:
            paragraphs[-1] = f"{prev} {line}"
    return paragraphs


def clean_text(raw: str) -> str:
    return "\n".join(join_paragraphs(clean_lines(raw)))
