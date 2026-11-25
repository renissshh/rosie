import json

import httpx
import pytest

from rosie.config import LLMConfig
from rosie.llm import (
    ChatResult,
    FallbackLLM,
    LLMError,
    OpenAICompatibleLLM,
    parse_chat_response,
)

MSGS = [{"role": "user", "content": "hi"}]


def reply(content=None, tool_calls=None):
    return {"model": "m", "choices": [{"message": {"content": content, "tool_calls": tool_calls}}]}


def client_with(handler, **cfg):
    return OpenAICompatibleLLM(
        LLMConfig(**cfg), http=httpx.Client(transport=httpx.MockTransport(handler)), environ={}
    )


def test_text_reply_and_request_shape():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=reply("Hello, VinsmokE."))

    result = client_with(handler).chat(MSGS)
    assert result.text == "Hello, VinsmokE."
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["body"] == {"model": "qwen3:8b", "messages": MSGS}


def test_tools_are_sent_and_calls_parsed():
    tools = [{"type": "function", "function": {"name": "add_task", "parameters": {}}}]

    def handler(request):
        assert json.loads(request.content)["tools"] == tools
        call = {"id": "c1", "function": {"name": "add_task", "arguments": '{"title": "DBMS"}'}}
        return httpx.Response(200, json=reply(tool_calls=[call]))

    result = client_with(handler).chat(MSGS, tools)
    assert result.tool_calls[0].name == "add_task"
    assert result.tool_calls[0].arguments == {"title": "DBMS"}


def test_api_key_read_from_named_env_var():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, json=reply("ok"))

    llm = OpenAICompatibleLLM(
        LLMConfig(provider="openai_compatible", api_key_env="KEY"),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        environ={"KEY": "secret"},
    )
    assert llm.chat(MSGS).text == "ok"


def test_missing_api_key_is_an_error():
    llm = client_with(lambda r: httpx.Response(200), api_key_env="NOPE")
    with pytest.raises(LLMError, match="NOPE"):
        llm.chat(MSGS)


def test_http_error_becomes_llm_error():
    with pytest.raises(LLMError, match="429"):
        client_with(lambda r: httpx.Response(429, text="rate limited")).chat(MSGS)


def test_connection_error_becomes_llm_error():
    def handler(request):
        raise httpx.ConnectError("ollama not running")

    with pytest.raises(LLMError, match="unreachable"):
        client_with(handler).chat(MSGS)


def test_bad_shape_and_bad_arguments():
    with pytest.raises(LLMError):
        parse_chat_response({"nope": 1})
    bad = reply(tool_calls=[{"function": {"name": "x", "arguments": "{not json"}}])
    with pytest.raises(LLMError, match="invalid tool arguments"):
        parse_chat_response(bad)


class Fake:
    def __init__(self, result=None, fail=False):
        self.result, self.fail, self.calls = result, fail, 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.fail:
            raise LLMError("down")
        return self.result


def test_fallback_uses_second_model_when_first_fails():
    local, cloud = Fake(fail=True), Fake(ChatResult(text="from cloud"))
    assert FallbackLLM(local, cloud).chat(MSGS).text == "from cloud"
    assert local.calls == cloud.calls == 1


def test_fallback_skips_cloud_when_local_works():
    local, cloud = Fake(ChatResult(text="local")), Fake(ChatResult(text="cloud"))
    assert FallbackLLM(local, cloud).chat(MSGS).text == "local"
    assert cloud.calls == 0


def test_fallback_all_fail():
    with pytest.raises(LLMError, match="all models failed"):
        FallbackLLM(Fake(fail=True), Fake(fail=True)).chat(MSGS)
