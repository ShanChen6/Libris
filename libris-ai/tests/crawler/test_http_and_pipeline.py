import json
from pathlib import Path

import httpx
import pymupdf
import pytest

from crawler import pipeline
from crawler.extract import extract_pdf
from crawler.http import FetchError, PoliteClient
from crawler.pipeline import Store, crawl_document, load_seeds, normalize_number

FIXTURES = Path(__file__).parent / "fixtures"


def _client(handler, **kw) -> PoliteClient:
    return PoliteClient(min_interval=0, transport=httpx.MockTransport(handler), **kw)


def test_client_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("crawler.http.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("reset", request=request)
        if calls["n"] == 2:
            return httpx.Response(503)
        return httpx.Response(200, text="ok")

    with _client(handler) as c:
        assert c.get_text("https://example.test/") == "ok"
    assert calls["n"] == 3


def test_client_raises_on_client_error() -> None:
    with _client(lambda r: httpx.Response(404)) as c, pytest.raises(FetchError):
        c.get_text("https://example.test/missing")


def test_client_enforces_max_bytes() -> None:
    with (
        _client(lambda r: httpx.Response(200, content=b"x" * 11), max_bytes=10) as c,
        pytest.raises(FetchError),
    ):
        c.download("https://example.test/big.pdf")


def _pdf_bytes(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_extract_pdf_text_and_empty_pages() -> None:
    body = "Dieu 1. Pham vi dieu chinh\n" + "Noi dung van ban phap luat. " * 20
    pages = extract_pdf(_pdf_bytes([body, ""]), ocr=False)
    assert [p.method for p in pages] == ["text", "empty"]
    assert "Dieu 1. Pham vi dieu chinh" in pages[0].text


def test_normalize_number() -> None:
    assert normalize_number(" 168/2024/NÐ-cp ") == "168/2024/NĐ-CP"


def test_load_seeds_rejects_unknown_keys(tmp_path: Path) -> None:
    p = tmp_path / "seeds.yaml"
    p.write_text("documents:\n  - {number: 1/2024/QH15, org: quoc-hoi, foo: bar}\n")
    with pytest.raises(ValueError, match="foo"):
        load_seeds(p)


def test_bundled_seeds_are_valid() -> None:
    seeds = load_seeds(Path(pipeline.__file__).parent / "seeds.yaml")
    assert len(seeds) >= 10
    assert all(s.org and s.number for s in seeds)


def test_crawl_document_end_to_end(tmp_path: Path) -> None:
    detail = (FIXTURES / "detail.html").read_text(encoding="utf-8")
    body = "Dieu 1. Pham vi dieu chinh\n" + "Bo luat nay quy dinh tieu chuan lao dong. " * 10
    pdf = _pdf_bytes([body])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "vanban.chinhphu.vn":
            return httpx.Response(200, text=detail)
        if request.url.path.endswith(".pdf"):
            return httpx.Response(200, content=pdf)
        return httpx.Response(404)

    store = Store(tmp_path)
    with _client(handler) as c:
        rec = crawl_document(c, "198540", store, ocr=False)

    assert rec["metadata"]["document_number"] == "45/2019/QH14"
    assert rec["text"].startswith("Dieu 1. Pham vi dieu chinh")
    assert rec["extraction"]["total_pages"] == 1
    assert rec["extraction"]["needs_review"] is False
    assert (tmp_path / "raw/vanban.chinhphu.vn/198540/files/45.signed.pdf").exists()
    saved = json.loads(store.processed_path("198540").read_text(encoding="utf-8"))
    assert saved["metadata"]["effective_date"] == "2021-01-01"


def _docx_bytes(paragraphs: list[str], *, backslash_names: bool = False) -> bytes:
    import io
    import zipfile

    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    name = "word\\document.xml" if backslash_names else "word/document.xml"
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, xml.encode("utf-8"))
    return buf.getvalue()


@pytest.mark.parametrize("backslash_names", [False, True])
def test_extract_docx(backslash_names: bool) -> None:
    from crawler.extract import extract_document

    paragraphs = ["Điều 1. Phạm vi điều chỉnh", "Luật này quy định."]
    data = _docx_bytes(paragraphs, backslash_names=backslash_names)
    (page,) = extract_document(data, "luat.docx")
    assert page.method == "docx"
    assert page.text == "Điều 1. Phạm vi điều chỉnh\nLuật này quy định."


def test_extract_unsupported_format() -> None:
    from crawler.extract import UnsupportedDocument, extract_document

    with pytest.raises(UnsupportedDocument):
        extract_document(b"x", "bang.xls")
