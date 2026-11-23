from datetime import date

from app.generation.citations import extract_citations
from app.generation.prompt import REFUSAL_MARKER, SYSTEM_PROMPT, build_messages, describe_validity
from app.retrieval.hybrid import FusedHit
from app.retrieval.router import route


def hit(number="168/2024/NĐ-CP", article="Điều 7", clause="Khoản 2", point=None, **kw) -> FusedHit:
    base = dict(
        chunk_id=f"{number}-{article}-{clause}", document_number=number, document_title="Nghị định",
        status="ACTIVE", effective_date=date(2025, 1, 1), expiry_date=None, article=article,
        clause=clause, point=point, context_prefix="[Văn bản: X]", content="Phạt tiền 400.000 đồng",
        char_start=10, char_end=30, score=0.03, vec_rank=1, kw_rank=1, ref_rank=None,
    )  # fmt: skip
    base.update(kw)
    return FusedHit(**base)


HITS = [
    hit(),
    hit(article="Điều 8", clause=None),
    hit("100/2019/NĐ-CP", "Điều 6", "Khoản 8", status="AMENDED",
        superseded_by=["repealed:168/2024/NĐ-CP"]),
]  # fmt: skip


def test_extract_and_validate_citations() -> None:
    answer = (
        "Bị phạt [Điều 7, Khoản 2 - 168/2024/NĐ-CP]. Cụ thể điểm a "
        "[Điều 7, Khoản 2, Điểm a - 168/2024/nđ-cp]; cả Điều 8 [Điều 8, Khoản 3 - 168/2024/NĐ-CP]."
        " Bịa: [Điều 99 - 168/2024/NĐ-CP] [Điều 7, Khoản 5 - 168/2024/NĐ-CP] "
        "[Điều 1 - 1/2020/QH14]. Gộp: [Điều 6, Khoản 8 - 100/2019/NĐ-CP; Điều 7 - 168/2024/NĐ-CP]"
        " [ghi chú không phải trích dẫn]"
    )
    cites = extract_citations(answer, HITS)
    valid = [(c.document_number, c.article, c.clause) for c in cites if c.valid]
    invalid = [c.label for c in cites if not c.valid]
    assert valid == [
        ("168/2024/NĐ-CP", "Điều 7", "Khoản 2"),
        ("168/2024/NĐ-CP", "Điều 7", "Khoản 2"),
        ("168/2024/NĐ-CP", "Điều 8", "Khoản 3"),  # đoạn của cả Điều 8 chứa mọi Khoản
        ("100/2019/NĐ-CP", "Điều 6", "Khoản 8"),
        ("168/2024/NĐ-CP", "Điều 7", None),
    ]
    assert invalid == [
        "[Điều 99 - 168/2024/NĐ-CP]",
        "[Điều 7, Khoản 5 - 168/2024/NĐ-CP]",
        "[Điều 1 - 1/2020/QH14]",
    ]
    first = cites[0]
    assert answer[first.start : first.end] == first.label and first.hit is HITS[0]


def test_validity_description() -> None:
    assert describe_validity(HITS[0]) == "Còn hiệu lực; có hiệu lực từ 01/01/2025"
    old = describe_validity(HITS[2])
    assert "ĐÃ BỊ BÃI BỎ bởi 168/2024/NĐ-CP" in old
    expired = hit(status="EXPIRED", expiry_date=date(2025, 1, 1), replaced_by=["X/2024/QH15"])
    assert "KHÔNG CÒN HIỆU LỰC" in describe_validity(expired)
    assert "hết hiệu lực từ 01/01/2025" in describe_validity(expired)


def test_messages_contain_rules_context_and_scope() -> None:
    msgs = build_messages("Vào năm 2022 vượt đèn đỏ?", HITS, route("Vào năm 2022 vượt đèn đỏ?"),
                          date(2026, 11, 23))  # fmt: skip
    system, user = msgs
    assert system.role == "system" and system.content == SYSTEM_PROMPT
    assert (
        REFUSAL_MARKER in SYSTEM_PROMPT and "[Điều X, Khoản Y - Số hiệu văn bản]" in SYSTEM_PROMPT
    )
    assert "Trích dẫn: [Điều 7, Khoản 2 - 168/2024/NĐ-CP]" in user.content
    assert "[Đoạn 3]" in user.content and "Ngày hiện tại: 23/11/2026" in user.content
    assert "mốc thời gian 01/01/2022 – 31/12/2022" in user.content
    assert user.content.rstrip().endswith("</cau_hoi>")
