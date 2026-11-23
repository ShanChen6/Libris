from datetime import date
from typing import Any

import pytest

from crawler.metadata import (
    build_catalog,
    extract_relations,
    normalize_document_type,
    normalize_title,
)


def _rels(number: str, text: str, title: str | None = None) -> set[tuple[str, str]]:
    return {(r.type, r.target) for r in extract_relations(number, title, text)}


def test_expiry_ignores_amending_laws() -> None:
    text = (
        "3. Luật Giao thông đường bộ số 23/2008/QH12 đã được sửa đổi, bổ sung một số điều theo "
        "Luật số 35/2018/QH14 và Luật số 44/2019/QH14 hết hiệu lực kể từ ngày Luật này có hiệu "
        "lực thi hành, trừ trường hợp quy định tại khoản 1 Điều 89 của Luật này."
    )
    assert _rels("36/2024/QH15", text) == {("replaces", "23/2008/QH12")}


def test_expiry_with_alias_in_parentheses() -> None:
    text = (
        "4. Luật Đất đai số 45/2013/QH13 đã được sửa đổi, bổ sung một số điều theo Luật số "
        "35/2018/QH14 (sau đây gọi là Luật Đất đai số 45/2013/QH13) hết hiệu lực kể từ ngày "
        "Luật này có hiệu lực thi hành."
    )
    assert _rels("31/2024/QH15", text) == {("replaces", "45/2013/QH13")}


def test_expiry_list() -> None:
    text = "\n".join(
        [
            "2. Các nghị định sau đây hết hiệu lực kể từ ngày Nghị định này có hiệu lực thi hành:",
            "a) Nghị định số 43/2014/NĐ-CP ngày 15 tháng 5 năm 2014 của Chính phủ quy định chi "
            "tiết thi hành một số điều của Luật Đất đai;",
            "b) Nghị định số 01/2017/NĐ-CP ngày 06 tháng 01 năm 2017 của Chính phủ;",
            "3. Nội dung khác nhắc tới Nghị định số 99/2020/NĐ-CP.",
        ]
    )
    assert _rels("102/2024/NĐ-CP", text) == {
        ("replaces", "43/2014/NĐ-CP"),
        ("replaces", "01/2017/NĐ-CP"),
    }


def test_effective_from_another_documents_expiry_is_not_replacement() -> None:
    text = (
        "Khoản 9 Điều 60 của Luật này có hiệu lực thi hành từ ngày Nghị quyết số 61/2022/QH15 "
        "hết hiệu lực."
    )
    assert _rels("31/2024/QH15", text) == set()


def test_explicit_expiry_date() -> None:
    text = "Nghị định số 100/2019/NĐ-CP hết hiệu lực kể từ ngày 01 tháng 01 năm 2025."
    (rel,) = extract_relations("168/2024/NĐ-CP", None, text)
    assert rel.type == "replaces" and rel.effective == date(2025, 1, 1)


def test_partial_repeal_and_quoted_text() -> None:
    text = "\n".join(
        [
            "2. Bãi bỏ Điều 57 của Luật Hàng không dân dụng Việt Nam số 66/2006/QH11.",
            "3. Bãi bỏ một số điều, khoản của các nghị định sau đây:",
            "a) Đoạn “theo quy định tại Điều 62 Luật Đất đai số 45/2013/QH13” tại khoản 1 Điều 110 "
            "Nghị định số 15/2021/NĐ-CP;",
            "Điều 5. Điều khoản chuyển tiếp",
            "a) Trường hợp đã thực hiện theo Nghị định số 01/2017/NĐ-CP thì tiếp tục thực hiện.",
        ]
    )
    assert _rels("102/2024/NĐ-CP", text) == {
        ("repeals_part", "66/2006/QH11"),
        ("repeals_part", "15/2021/NĐ-CP"),
    }


def test_whole_repeal() -> None:
    text = "2. Bãi bỏ Nghị quyết số 132/2020/QH14 ngày 17 tháng 11 năm 2020 của Quốc hội."
    assert _rels("31/2024/QH15", text) == {("replaces", "132/2020/QH14")}


def test_amends_from_title() -> None:
    title = (
        "Luật sửa đổi, bổ sung một số điều của Luật Đất đai số 31/2024/QH15, Luật Nhà ở số "
        "27/2023/QH15"
    )
    assert _rels("43/2024/QH15", "", title) == {
        ("amends", "31/2024/QH15"),
        ("amends", "27/2023/QH15"),
    }


def test_sets_effective_date_of_other_document() -> None:
    text = (
        "Luật Đất đai số 31/2024/QH15 có hiệu lực thi hành từ ngày 01 tháng 8 năm 2024.\n"
        "Điều 190 của Luật Nhà ở số 27/2023/QH15 có hiệu lực thi hành "
        "từ ngày 01 tháng 4 năm 2024.\n"
        "Luật này có hiệu lực thi hành từ ngày 01 tháng 8 năm 2024."
    )
    rels = extract_relations("43/2024/QH15", None, text)
    assert [(r.type, r.target, r.effective) for r in rels] == [
        ("sets_effective_date", "31/2024/QH15", date(2024, 8, 1))
    ]


def _rec(
    source_id: str, number: str, effective: str | None, text: str = "", title: str = "Văn bản"
) -> dict[str, Any]:
    return {
        "metadata": {
            "source_id": source_id,
            "document_number": number,
            "document_type": None,
            "title": title,
            "issuing_body": "Quốc hội",
            "signer": None,
            "issue_date": "2020-01-01",
            "effective_date": effective,
            "url": f"https://example.test/{source_id}",
        },
        "text": text,
        "extraction": {"needs_review": False},
    }


def test_build_catalog_statuses() -> None:
    records = [
        _rec("1", "45/2013/QH13", "2014-07-01"),
        _rec(
            "2",
            "31/2024/QH15",
            "2025-01-01",
            "Luật Đất đai số 45/2013/QH13 hết hiệu lực kể từ ngày Luật này có hiệu lực thi hành.",
        ),
        _rec(
            "3",
            "43/2024/QH15",
            "2024-08-01",
            "Luật Đất đai số 31/2024/QH15 có hiệu lực thi hành từ ngày 01 tháng 8 năm 2024.",
            title="Luật sửa đổi, bổ sung một số điều của Luật Đất đai số 31/2024/QH15",
        ),
        _rec("4", "99/2030/QH16", "2030-01-01"),
    ]
    by_number = {e.document_number: e for e in build_catalog(records, date(2026, 1, 1))}

    land_2024 = by_number["31/2024/QH15"]
    assert land_2024.effective_date == date(2024, 8, 1)  # điều chỉnh theo Luật 43/2024
    assert land_2024.status == "AMENDED"
    assert land_2024.amended_by == ["43/2024/QH15"]
    assert land_2024.warnings

    land_2013 = by_number["45/2013/QH13"]
    assert land_2013.status == "EXPIRED"
    assert land_2013.expiry_date == date(2024, 8, 1)  # theo ngày hiệu lực đã điều chỉnh
    assert land_2013.replaced_by == ["31/2024/QH15"]
    assert land_2013.evidence

    assert by_number["43/2024/QH15"].status == "ACTIVE"
    assert by_number["99/2030/QH16"].status == "PENDING"


def test_build_catalog_before_replacement_takes_effect() -> None:
    records = [
        _rec("1", "45/2013/QH13", "2014-07-01"),
        _rec(
            "2",
            "31/2024/QH15",
            "2025-01-01",
            "Luật Đất đai số 45/2013/QH13 hết hiệu lực kể từ ngày Luật này có hiệu lực thi hành.",
        ),
    ]
    by_number = {e.document_number: e for e in build_catalog(records, date(2024, 6, 1))}
    assert by_number["45/2013/QH13"].status == "ACTIVE"
    assert by_number["31/2024/QH15"].status == "PENDING"


@pytest.mark.parametrize(
    ("raw", "number", "expected"),
    [
        ("Luật", "45/2019/QH14", "Luật"),
        ("Bộ luật", "45/2019/QH14", "Luật"),
        (None, "168/2024/NĐ-CP", "Nghị định"),
        (None, "38/2024/TT-BCA", "Thông tư"),
        (None, "2292/QĐ-TTg", "Quyết định"),
        (None, "123/ABC", None),
    ],
)
def test_normalize_document_type(raw: str | None, number: str, expected: str | None) -> None:
    assert normalize_document_type(raw, number) == expected


def test_normalize_title() -> None:
    assert normalize_title("Bộ Luật Lao động") == "Bộ luật Lao động"
    assert normalize_title("LUẬT HÔN NHÂN VÀ GIA ĐÌNH") == "Luật hôn nhân và gia đình"


# --- Điều/Khoản bị bãi bỏ / thay nội dung ------------------------------------------------------
from crawler.metadata import analyze, extract_provisions, parse_spec  # noqa: E402

AMENDING = "\n".join(
    [
        "Điều 52. Sửa đổi, bổ sung một số điều của Nghị định số 100/2019/NĐ-CP ngày 30 tháng 12 "
        "năm 2019 của Chính phủ đã được sửa đổi, bổ sung bởi Nghị định số 123/2021/NĐ-CP",
        "1. Sửa đổi, bổ sung khoản 4 Điều 82 như sau:",
        "“4. Nội dung mới.”",
        "2. Sửa đổi, bổ sung tên Điều 53 như sau:",
        "“Điều 53. Tên mới”",
        "8. Bãi bỏ một số điểm, khoản, điều sau đây:",
        "a) Bãi bỏ khoản 1 Điều 3;",
        "b) Bãi bỏ điểm b, điểm e khoản 2 Điều 4;",
        "d) Bãi bỏ Điều 5, Điều 6, Điêu 7;",
        "e) Bãi bỏ Điều 16, Điều 17; ø) Bãi bỏ điểm a khoản 1; khoản 2; khoản 4 Điều 23;",
        "0 Bãi bỏ Điều 25; :",
        "9. Bỏ một số cụm từ tại các điểm, khoản, điều sau đây:",
        "a) Bỏ cụm từ “camera” tại điểm p khoản 2 Điều 4;",
        "Điều 53. Hiệu lực thi hành",
        "1. Nghị định này có hiệu lực thi hành từ ngày 01 tháng 01 năm 2025.",
    ]
)


@pytest.mark.parametrize(
    ("spec", "default", "expected"),
    [
        ("Điều 5, Điều 6, Điêu 7;", None, [("Điều 5", None), ("Điều 6", None), ("Điều 7", None)]),
        ("khoản 1; điểm c khoản 2; khoản 7 Điều 12;", None,
         [("Điều 12", "Khoản 1"), ("Điều 12", "Khoản 7")]),
        ("khoản 1, khoản 3 Điêu 82.", None, [("Điều 82", "Khoản 1"), ("Điều 82", "Khoản 3")]),
        ("điểm c khoản 2 Điều 7", None, []),  # cấp Điểm: đoạn vẫn còn nội dung hiệu lực
        ("khoản 2 và khoản 3", "Điều 3", [("Điều 3", "Khoản 2"), ("Điều 3", "Khoản 3")]),
        ("tên Điều 53", None, []),
        ("tên điều, khoản 5 Điều 53", None, [("Điều 53", "Khoản 5")]),
        ("cụm từ “Điều 9” tại điểm đ khoản 3", None, []),
        ("khoản 2", None, []),  # không xác định được Điều
    ],
)  # fmt: skip
def test_parse_spec(spec: str, default: str | None, expected: list) -> None:
    assert parse_spec(spec, default) == expected


def test_extract_provisions_from_amending_decree() -> None:
    provs = extract_provisions("168/2024/NĐ-CP", AMENDING)
    assert {p.target for p in provs} == {"100/2019/NĐ-CP"}  # không phải 123/2021 (đã sửa đổi theo)
    got = {(p.kind, p.article, p.clause) for p in provs}
    assert got == {
        ("amended", "Điều 82", "Khoản 4"),
        ("repealed", "Điều 3", "Khoản 1"),
        ("repealed", "Điều 5", None),
        ("repealed", "Điều 6", None),
        ("repealed", "Điều 7", None),
        ("repealed", "Điều 16", None),
        ("repealed", "Điều 17", None),
        ("repealed", "Điều 23", "Khoản 2"),
        ("repealed", "Điều 23", "Khoản 4"),
        ("repealed", "Điều 25", None),
    }


def test_provisions_only_inside_amending_articles() -> None:
    text = "Điều 5. Hiệu lực thi hành\n2. Bãi bỏ Điều 3 của Nghị định số 1/2020/NĐ-CP."
    assert extract_provisions("2/2024/NĐ-CP", text) == []


def test_analyze_sets_provision_effective_date() -> None:
    records = [
        _rec("1", "100/2019/NĐ-CP", "2020-01-01"),
        _rec("2", "168/2024/NĐ-CP", "2025-01-01", AMENDING),
    ]
    catalog = analyze(records, date(2026, 1, 1))
    assert catalog.provisions
    assert {p.effective for p in catalog.provisions} == {date(2025, 1, 1)}
    assert catalog.to_dict()["provisions"][0]["effective"] == "2025-01-01"
