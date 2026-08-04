from __future__ import annotations

import importlib
import json

import httpx
import pytest


def test_client_requests_and_parses_json_output() -> None:
    try:
        deepseek_module = importlib.import_module("app.ai.deepseek")
    except ModuleNotFoundError:
        pytest.fail("DeepSeek client is not implemented")

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"lines": [{"surface": "君"}]},
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    client = deepseek_module.DeepSeekClient(
        api_key="test-secret",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        transport=httpx.MockTransport(handler),
    )

    result = client.complete_json(
        system_prompt="只输出 JSON",
        user_prompt='{"lines":["君"]}',
    )

    assert result == {"lines": [{"surface": "君"}]}
    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.headers["Authorization"] == "Bearer test-secret"
    body = json.loads(request.content)
    assert body["model"] == "deepseek-v4-flash"
    assert body["thinking"] == {"type": "disabled"}
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"] == [
        {"role": "system", "content": "只输出 JSON"},
        {"role": "user", "content": '{"lines":["君"]}'},
    ]

