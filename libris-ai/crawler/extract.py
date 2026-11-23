"""Trích xuất văn bản từ file đính kèm.

- PDF: lớp chữ (PyMuPDF), OCR Tesseract cho trang scan.
- DOC (Word 97-2003): ``catdoc``.
- DOCX: đọc trực tiếp ``word/document.xml``.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import Literal
from xml.etree import ElementTree

import pymupdf

log = logging.getLogger(__name__)

# Trang có ít hơn ngần này chữ cái được coi là ảnh scan (thường chỉ còn dấu chữ ký số).
MIN_LETTERS_PER_PAGE = 100
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


@dataclass
class PageText:
    page: int
    text: str
    method: Literal["text", "ocr", "empty", "doc", "docx"]


def tesseract_available(lang: str = "vie") -> bool:
    if shutil.which("tesseract") is None:
        return False
    out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
    return lang in out.stdout.split()


def _count_letters(text: str) -> int:
    return len(_LETTER_RE.findall(text))


def _ocr_page(page: pymupdf.Page, *, lang: str, dpi: int) -> str:
    png = page.get_pixmap(dpi=dpi).tobytes("png")
    proc = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", lang, "--psm", "6"],
        input=png,
        capture_output=True,
        check=True,
    )
    return proc.stdout.decode("utf-8")


def extract_pdf(
    data: bytes, *, ocr: bool = True, lang: str = "vie", dpi: int = 300
) -> list[PageText]:
    can_ocr = ocr and tesseract_available(lang)
    if ocr and not can_ocr:
        log.warning("Không tìm thấy tesseract (ngôn ngữ '%s'); bỏ qua OCR trang scan", lang)
    pages: list[PageText] = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text()
            if _count_letters(text) >= MIN_LETTERS_PER_PAGE:
                pages.append(PageText(i, text, "text"))
            elif can_ocr:
                pages.append(PageText(i, _ocr_page(page, lang=lang, dpi=dpi), "ocr"))
            else:
                pages.append(PageText(i, text, "empty"))
    return pages


SUPPORTED_EXTENSIONS = (".pdf", ".doc", ".docx")
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class UnsupportedDocument(RuntimeError):
    pass


def extract_doc(data: bytes) -> list[PageText]:
    """Word 97-2003 (.doc) qua ``catdoc``: mỗi đoạn một dòng, mã hóa UTF-8."""
    if shutil.which("catdoc") is None:
        raise UnsupportedDocument("cần cài 'catdoc' để đọc file .doc")
    proc = subprocess.run(
        ["catdoc", "-d", "utf-8", "-w", "-"], input=data, capture_output=True, check=True
    )
    return [PageText(1, proc.stdout.decode("utf-8", errors="replace"), "doc")]


def extract_docx(data: bytes) -> list[PageText]:
    with zipfile.ZipFile(BytesIO(data)) as z:
        # Một số file được nén trên Windows với tên mục dùng dấu '\'.
        names = {n.replace("\\", "/"): n for n in z.namelist()}
        if "word/document.xml" not in names:
            raise UnsupportedDocument("không tìm thấy word/document.xml")
        root = ElementTree.fromstring(z.read(names["word/document.xml"]))
    paragraphs: list[str] = []
    for p in root.iter(f"{_W_NS}p"):
        parts: list[str] = []
        for node in p.iter():
            if node.tag == f"{_W_NS}t" and node.text:
                parts.append(node.text)
            elif node.tag in (f"{_W_NS}tab", f"{_W_NS}br"):
                parts.append(" ")
        paragraphs.append("".join(parts))
    return [PageText(1, "\n".join(paragraphs), "docx")]


def extract_document(
    data: bytes, filename: str, *, ocr: bool = True, lang: str = "vie"
) -> list[PageText]:
    name = filename.lower()
    if name.endswith(".pdf"):
        return extract_pdf(data, ocr=ocr, lang=lang)
    if name.endswith(".docx"):
        return extract_docx(data)
    if name.endswith(".doc"):
        return extract_doc(data)
    raise UnsupportedDocument(f"định dạng chưa hỗ trợ: {filename}")
