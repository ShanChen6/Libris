from datetime import date
from pathlib import Path

import pytest

from crawler.sources import vanban_chinhphu as vbcp

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_listing_url_filters() -> None:
    url = vbcp.listing_url("quoc-hoi", "luat")
    assert "orggroupid=1" in url and "typegroupid=3" in url and "maxresults=50" in url


def test_parse_listing() -> None:
    items = vbcp.parse_listing(_read("listing.html"))
    assert [i.document_number for i in items] == ["36/2024/QH15", "31/2024/QH15"]
    first = items[0]
    assert first.source_id == "211194"
    assert first.issue_date == date(2024, 6, 27)
    assert first.title == "Luật Trật tự, an toàn giao thông đường bộ"
    assert first.url == "https://vanban.chinhphu.vn/?pageid=27160&docid=211194"
    assert items[1].title == "Luật Đất đai"


def test_parse_listing_without_grid_returns_empty() -> None:
    assert vbcp.parse_listing("<html><body>Không có dữ liệu</body></html>") == []


def test_postback_form_for_next_page() -> None:
    form = vbcp._postback_form(_read("listing.html"), 2)
    assert form is not None
    assert form["__EVENTTARGET"] == "ctrl_191017_163$grvDocument"
    assert form["__EVENTARGUMENT"] == "Page$2"
    assert form["__VIEWSTATE"] == "VS123"
    assert form["__EVENTVALIDATION"] == "EV456"
    assert "ctrl_190922_45$txtSearch" not in form


def test_postback_form_on_last_page_returns_none() -> None:
    html = _read("listing.html").replace("Page$2", "Page$1").replace("Page$Last", "Page$First")
    assert vbcp._postback_form(html, 2) is None


def test_parse_detail() -> None:
    d = vbcp.parse_detail(_read("detail.html"), "198540")
    assert d.document_number == "45/2019/QH14"
    assert d.document_type == "Luật"
    assert d.issuing_body == "Quốc hội"
    assert d.signer == "Nguyễn Thị Kim Ngân"
    assert d.title == "Bộ Luật Lao động"
    assert d.issue_date == date(2019, 11, 20)
    assert d.effective_date == date(2021, 1, 1)
    assert [a.filename for a in d.attachments] == ["45.signed.pdf"]
    assert d.to_dict()["effective_date"] == "2021-01-01"


def test_parse_detail_missing_table_raises() -> None:
    with pytest.raises(ValueError):
        vbcp.parse_detail("<html></html>", "1")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("20-11-2019", date(2019, 11, 20)), ("27/06/2024", date(2024, 6, 27)), ("", None)],
)
def test_parse_date(value: str, expected: date | None) -> None:
    assert vbcp.parse_date(value) == expected
