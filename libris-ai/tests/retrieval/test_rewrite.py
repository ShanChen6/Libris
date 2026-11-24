from app.retrieval.rewrite import QueryRewriter, clean
from tests.fakes import FakeLLM


def test_clean() -> None:
    assert clean('Truy vấn: "điều kiện kết hôn, độ tuổi"\nGiải thích...') == (
        "điều kiện kết hôn, độ tuổi"
    )
    assert clean("") is None
    assert clean(" ".join(["từ"] * 60)) is None


def test_rewriter_caches(tmp_path) -> None:
    llm = FakeLLM("đơn phương chấm dứt hợp đồng lao động trái pháp luật")
    path = tmp_path / "rw.json"
    rw = QueryRewriter(llm, path)
    assert rw("Nghỉ ngang thì sao?") == "đơn phương chấm dứt hợp đồng lao động trái pháp luật"
    assert QueryRewriter(llm, path)("Nghỉ ngang thì sao?") is not None
    assert len(llm.calls) == 1  # lần sau lấy từ tệp cache
