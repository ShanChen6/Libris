"""Tiện ích xử lý tiếng Việt dùng chung cho crawler và pipeline."""

from __future__ import annotations

import re
import unicodedata

# OCR tiếng Việt hay nhầm dấu ("hệt hiệu lực", "bỗ sung", "Điêu"), nên các cụm từ khóa được so khớp
# theo "họ" chữ cái: mọi biến thể dấu của cùng một chữ cái gốc đều được chấp nhận.
VN_LETTERS = "aàáảãạăằắẳẵặâầấẩẫậeèéẻẽẹêềếểễệiìíỉĩịoòóỏõọôồốổỗộơờớởỡợuùúủũụưừứửữựyỳýỷỹỵdđ"

# Thứ tự chữ cái đánh số điểm trong văn bản pháp luật (không dùng f, j, w, z).
POINT_LETTERS = "abcdđeghiklmnopqrstuvxy"


def base_letter(c: str) -> str:
    return "d" if c in "đĐ" else unicodedata.normalize("NFD", c.lower())[0]


_FAMILIES: dict[str, set[str]] = {}
for _ch in VN_LETTERS:
    _FAMILIES.setdefault(base_letter(_ch), set()).update({_ch, _ch.upper()})


def fz(phrase: str) -> str:
    """Regex khớp ``phrase`` bất kể sai lệch dấu và hoa/thường."""
    out: list[str] = []
    for c in phrase:
        if c == " ":
            out.append(r"\s+")
        elif c.lower() in VN_LETTERS:
            out.append("[" + "".join(sorted(_FAMILIES[base_letter(c)])) + "]")
        elif c.isalpha():
            out.append(f"[{c.lower()}{c.upper()}]")
        else:
            out.append(re.escape(c))
    return "".join(out)
