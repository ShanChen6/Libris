"""Nguồn: Hệ thống văn bản của Chính phủ (https://vanban.chinhphu.vn).

- Danh sách: ``/he-thong-van-ban?classid=1&mode=1&orggroupid=..&typegroupid=..``, mỗi trang
  50 văn bản, sắp xếp theo ngày ban hành giảm dần; chuyển trang bằng ASP.NET postback.
- Chi tiết: ``/?pageid=27160&docid=<id>`` gồm bảng thuộc tính và file đính kèm (PDF) trên
  ``datafiles.chinhphu.vn``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from crawler.http import PoliteClient
from crawler.models import Attachment, DocumentDetail, ListingItem

SOURCE = "vanban.chinhphu.vn"
BASE_URL = "https://vanban.chinhphu.vn"
DETAIL_PAGE_ID = "27160"

ORG_GROUPS = {
    "quoc-hoi": 1,
    "chinh-phu": 2,
    "thu-tuong": 3,
    "bo-nganh": 4,
    "lien-bo": 5,
    "ubnd-tinh": 6,
}
TYPE_GROUPS = {
    "hien-phap": 1,
    "sac-lenh": 2,
    "luat": 3,
    "nghi-dinh": 4,
    "quyet-dinh": 5,
    "thong-tu": 6,
}

# Nhãn trên trang chi tiết -> tên trường chuẩn
_FIELD_MAP = {
    "Số ký hiệu": "document_number",
    "Ngày ban hành": "issue_date",
    "Ngày có hiệu lực": "effective_date",
    "Loại văn bản": "document_type",
    "Cơ quan ban hành": "issuing_body",
    "Người ký": "signer",
    "Trích yếu": "title",
}


_PAGER_RE = re.compile(r"__doPostBack\('([^']*grvDocument)','Page\$(\w+)'\)")


def listing_url(org: str | None = None, doc_type: str | None = None) -> str:
    url = f"{BASE_URL}/he-thong-van-ban?classid=1&mode=1&maxresults=50"
    if org:
        url += f"&orggroupid={ORG_GROUPS[org]}"
    if doc_type:
        url += f"&typegroupid={TYPE_GROUPS[doc_type]}"
    return url


def detail_url(source_id: str) -> str:
    return f"{BASE_URL}/?pageid={DETAIL_PAGE_ID}&docid={source_id}"


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _find_grid(soup: BeautifulSoup) -> Tag | None:
    grid = soup.find("table", id=re.compile(r"grvDocument$"))
    return grid if isinstance(grid, Tag) else None


def parse_listing(html: str) -> list[ListingItem]:
    soup = BeautifulSoup(html, "lxml")
    grid = _find_grid(soup)
    if grid is None:
        return []
    items: list[ListingItem] = []
    for row in grid.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            continue
        link = cells[0].find("a", href=re.compile(r"docid=\d+"))
        code = cells[0].find("span", class_="code")
        if link is None or code is None:
            continue
        source_id = parse_qs(urlsplit(str(link["href"])).query)["docid"][0]
        issued = cells[1].find("span", class_="issued-date")
        title = cells[2].find("span", class_="substract")
        items.append(
            ListingItem(
                source_id=source_id,
                document_number=_clean(code.get_text()),
                issue_date=parse_date(issued.get_text() if issued else None),
                title=_clean(title.get_text()) if title else "",
                url=detail_url(source_id),
            )
        )
    return items


def _postback_form(html: str, page: int) -> dict[str, str] | None:
    """Dựng dữ liệu form ASP.NET để chuyển sang trang ``page`` của lưới văn bản."""
    soup = BeautifulSoup(html, "lxml")
    grid = _find_grid(soup)
    form = soup.find("form")
    if grid is None or not isinstance(form, Tag):
        return None
    event_target: str | None = None
    has_next = False
    for a in grid.find_all("a", href=True):
        m = _PAGER_RE.search(str(a["href"]))
        if m is None:
            continue
        event_target = m.group(1)
        arg = m.group(2)
        if arg in ("Next", "Last") or (arg.isdigit() and int(arg) >= page):
            has_next = True
    if event_target is None or not has_next:
        return None
    data = {
        str(i["name"]): str(i.get("value", ""))
        for i in form.find_all("input", attrs={"type": "hidden"})
        if i.get("name")
    }
    data["__EVENTTARGET"] = event_target
    data["__EVENTARGUMENT"] = f"Page${page}"
    return data


def iter_listing(
    client: PoliteClient,
    *,
    org: str | None = None,
    doc_type: str | None = None,
    max_pages: int = 20,
    stop_before: date | None = None,
) -> Iterator[ListingItem]:
    """Duyệt danh sách văn bản (mới nhất trước).

    Dừng khi hết trang, đạt ``max_pages`` hoặc khi gặp văn bản ban hành trước ``stop_before``.
    """
    url = listing_url(org, doc_type)
    html = client.get_text(url)
    page = 1
    while True:
        items = parse_listing(html)
        if not items:
            return
        yield from items
        oldest = min((i.issue_date for i in items if i.issue_date), default=None)
        if page >= max_pages or (stop_before and oldest and oldest < stop_before):
            return
        form = _postback_form(html, page + 1)
        if form is None:
            return
        html = client.post_form(url, form)
        page += 1


def parse_detail(html: str, source_id: str) -> DocumentDetail:
    soup = BeautifulSoup(html, "lxml")
    raw: dict[str, str] = {}
    attachments: list[Attachment] = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) != 2 or "col1" not in (cells[0].get("class") or []):
            continue
        label = _clean(cells[0].get_text())
        if label == "Tài liệu đính kèm":
            for a in cells[1].select(".rp-file a[href]"):
                href = str(a["href"])
                if href.startswith("javascript"):
                    continue
                url = urljoin(BASE_URL, href)
                attachments.append(Attachment(url=url, filename=url.rsplit("/", 1)[-1]))
            continue
        raw[label] = _clean(cells[1].get_text(" "))

    fields = {_FIELD_MAP[k]: v for k, v in raw.items() if k in _FIELD_MAP}
    if "document_number" not in fields:
        raise ValueError(f"docid={source_id}: không tìm thấy bảng thuộc tính văn bản")
    return DocumentDetail(
        source=SOURCE,
        source_id=source_id,
        url=detail_url(source_id),
        document_number=fields["document_number"],
        document_type=fields.get("document_type"),
        issuing_body=fields.get("issuing_body"),
        signer=fields.get("signer"),
        title=fields.get("title"),
        issue_date=parse_date(fields.get("issue_date")),
        effective_date=parse_date(fields.get("effective_date")),
        attachments=attachments,
        raw_fields=raw,
    )


def fetch_detail(client: PoliteClient, source_id: str) -> DocumentDetail:
    return parse_detail(client.get_text(detail_url(source_id)), source_id)
