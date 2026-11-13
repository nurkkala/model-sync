from __future__ import annotations

import json

import httpx
import pytest

from model_sync.index import Provider
from model_sync.probes import run_probe


def serve(routes: dict[str, object], seen: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        answer = routes.get(request.url.path)
        if answer is None:
            return httpx.Response(404)
        if callable(answer):
            answer = answer(request)
        if isinstance(answer, int):
            return httpx.Response(answer)
        return httpx.Response(200, json=answer)

    return httpx.MockTransport(handler)


def show(request: httpx.Request) -> dict:
    return {
        "chat:7b": {
            "capabilities": ["completion", "tools", "thinking", "vision"],
            "model_info": {
                "fam.rope.scaling.original_context_length": 4096,
                "fam.context_length": 131072,
            },
        },
        "plain:1b": {"capabilities": ["completion"], "model_info": {}},
        "embed:latest": {"capabilities": ["embedding"]},
    }[json.loads(request.content)["model"]]


OLLAMA = {
    "/api/tags": {
        "models": [{"name": "chat:7b"}, {"name": "plain:1b"}, {"name": "embed:latest"}]
    },
    "/api/show": show,
}


def test_ollama_reads_context_and_capabilities_and_drops_embedders():
    result = run_probe(Provider(kind="ollama", base_url="http://x/"), serve(OLLAMA))
    assert [model.id for model in result.models] == ["chat:7b", "plain:1b"]
    chat, plain = result.models
    assert (chat.context, chat.vision, chat.tools, chat.reasoning) == (
        131072,
        True,
        True,
        True,
    )
    assert (plain.context, plain.vision, plain.tools, plain.reasoning) == (
        None,
        False,
        False,
        False,
    )


def test_exclude_patterns_drop_models():
    provider = Provider(kind="ollama", base_url="http://x", exclude=["plain:*"])
    assert [model.id for model in run_probe(provider, serve(OLLAMA)).models] == [
        "chat:7b"
    ]


def test_litellm_reads_model_info_and_sends_the_key(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY", "sk-from-env")
    seen: list[httpx.Request] = []
    routes = {
        "/model/info": {
            "data": [
                {
                    "model_name": "a",
                    "model_info": {
                        "mode": "chat",
                        "max_input_tokens": 1000,
                        "max_output_tokens": 500,
                        "supports_vision": True,
                        "supports_function_calling": False,
                        "supports_reasoning": None,
                    },
                },
                {"model_name": "emb", "model_info": {"mode": "embedding"}},
                {"model_name": "bare"},
            ]
        }
    }
    provider = Provider(kind="litellm", base_url="http://x", api_key="${GATEWAY_KEY}")
    result = run_probe(provider, serve(routes, seen))
    assert [model.id for model in result.models] == ["a", "bare"]
    a = result.models[0]
    assert (a.context, a.max_input, a.max_output) == (1000, 1000, 500)
    assert (a.vision, a.tools, a.reasoning) == (True, False, None)
    assert seen[0].headers["authorization"] == "Bearer sk-from-env"


def test_openai_lists_ids_only():
    routes = {"/v1/models": {"data": [{"id": "m1"}, {"id": "m2"}]}}
    result = run_probe(Provider(kind="openai", base_url="http://x"), serve(routes))
    assert [model.model_dump(exclude_none=True) for model in result.models] == [
        {"id": "m1"},
        {"id": "m2"},
    ]


def refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


def stall(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("slow", request=request)


@pytest.mark.parametrize(
    ("transport", "reason"),
    [
        (httpx.MockTransport(refuse), "connection refused"),
        (httpx.MockTransport(stall), "no answer in 5s"),
        (serve({"/api/tags": 401}), "HTTP 401 from /api/tags"),
        (serve({"/api/tags": {"models": [{"nameless": 1}]}}), "unreadable answer"),
        (serve({"/api/tags": ["not", "an", "object"]}), "unreadable answer"),
    ],
)
def test_every_failure_to_ask_is_unreachable_with_a_reason(transport, reason):
    result = run_probe(Provider(kind="ollama", base_url="http://x"), transport)
    assert result.models is None
    assert not result.reachable
    assert reason in result.error


def test_an_empty_answer_is_reachable_and_empty():
    result = run_probe(
        Provider(kind="ollama", base_url="http://x"), serve({"/api/tags": {}})
    )
    assert result.reachable
    assert result.models == []


def test_an_unset_key_variable_is_unreachable_and_never_asks(monkeypatch):
    monkeypatch.delenv("NO_SUCH_KEY", raising=False)
    seen: list[httpx.Request] = []
    provider = Provider(kind="openai", base_url="http://x", api_key="$NO_SUCH_KEY")
    result = run_probe(provider, serve({"/v1/models": {"data": []}}, seen))
    assert result.error == "$NO_SUCH_KEY is not set"
    assert seen == []


def test_a_key_command_supplies_the_key_and_a_failing_one_is_unreachable():
    seen: list[httpx.Request] = []
    routes = {"/v1/models": {"data": []}}
    good = Provider(kind="openai", base_url="http://x", api_key="!printf 'sk-cmd\\n'")
    assert run_probe(good, serve(routes, seen)).reachable
    assert seen[0].headers["authorization"] == "Bearer sk-cmd"
    bad = Provider(kind="openai", base_url="http://x", api_key="!exit 3")
    assert "exited 3" in run_probe(bad, serve(routes)).error
