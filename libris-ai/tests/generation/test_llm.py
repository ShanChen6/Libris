import json

import httpx
import pytest

from app.generation.llm import LLMError, Message, OpenAICompatibleClient


def _client(handler, models=("m1", "m2"), retries=1, monkeypatch=None) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url="https://llm.test/v1", models=list(models), retries=retries,
        transport=httpx.MockTransport(handler), api_key="k", reasoning_effort="low",
    )  # fmt: skip


def _ok(model: str, text: str = "xin chào") -> httpx.Response:
    return httpx.Response(
        200,
        json={"model": model, "choices": [{"message": {"content": text}}], "usage": {"x": 1}},
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.generation.llm.time.sleep", lambda _s: None)


def test_request_format_and_success() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(req.url), req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return _ok("m1")

    out = _client(handler).complete([Message("system", "s"), Message("user", "u")])
    assert out.text == "xin chào" and out.model == "m1" and out.usage == {"x": 1}
    assert seen["url"] == "https://llm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "s"}, {"role": "user", "content": "u"},
    ]  # fmt: skip
    assert seen["body"]["reasoning_effort"] == "low" and seen["body"]["stream"] is False


def test_overloaded_primary_falls_back_immediately() -> None:
    order = []

    def handler(req: httpx.Request) -> httpx.Response:
        model = json.loads(req.content)["model"]
        order.append(model)
        return httpx.Response(503, json=[{"error": {"message": "high demand"}}]) if model == "m1" \
            else _ok(model)  # fmt: skip

    assert _client(handler).complete([Message("user", "u")]).model == "m2"
    assert order == ["m1", "m2"]  # không chờ thử lại m1 trước


def test_retired_model_is_skipped_in_later_rounds() -> None:
    order = []

    def handler(req: httpx.Request) -> httpx.Response:
        model = json.loads(req.content)["model"]
        order.append(model)
        if model == "m1":
            return httpx.Response(404, json={"error": {"message": "no longer available"}})
        return httpx.Response(429) if len(order) < 4 else _ok(model)

    assert _client(handler, retries=2).complete([Message("user", "u")]).model == "m2"
    assert order == ["m1", "m2", "m2", "m2"]


def test_client_error_is_not_retried() -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    with pytest.raises(LLMError, match="bad request"):
        _client(handler).complete([Message("user", "u")])
    assert len(calls) == 1


def test_all_models_fail() -> None:
    with pytest.raises(LLMError, match="m1.*m2|Không gọi được"):
        _client(lambda r: httpx.Response(503)).complete([Message("user", "u")])


def test_stream_parses_sse() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert json.loads(req.content)["stream"] is True
        lines = [
            'data: {"choices":[{"delta":{"content":"Xin "}}]}',
            "",
            'data: {"choices":[{"delta":{"content":"chào"}}]}',
            'data: {"choices":[{"delta":{}}]}',
            "data: [DONE]",
        ]
        return httpx.Response(200, text="\n".join(lines))

    assert "".join(_client(handler).stream([Message("user", "u")])) == "Xin chào"


def test_no_auth_header_without_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert "authorization" not in req.headers
        return _ok("m1")

    c = OpenAICompatibleClient(base_url="https://x/v1", models=["m1"],
                               transport=httpx.MockTransport(handler))  # fmt: skip
    assert c.complete([Message("user", "u")]).text
    with pytest.raises(ValueError):
        OpenAICompatibleClient(base_url="https://x/v1", models=[])
