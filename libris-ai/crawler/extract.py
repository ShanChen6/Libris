"""Trích xuất văn bản từ PDF: lớp chữ (PyMuPDF), OCR Tesseract cho trang scan."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

import pymupdf

log = logging.getLogger(__name__)

# Trang có ít hơn ngần này chữ cái được coi là ảnh scan (thường chỉ còn dấu chữ ký số).
MIN_LETTERS_PER_PAGE = 100
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


@dataclass
class PageText:
    page: int
    text: str
    method: Literal["text", "ocr", "empty"]


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
