"""One probe per provider kind: ask a server which models it serves right now.

Adding a provider kind means writing one function here and decorating it with
`@probe("<kind>")`. It receives the provider's index entry and an HTTP client already
carrying the base URL, the timeout, and the bearer key, and returns the models it found
with whatever facts the server reports. Fields the server does not report stay `None`.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatchcase

import httpx
from pydantic import BaseModel

from model_sync.index import Provider, SecretError, resolve_secret


class Model(BaseModel):
    """What one probe learned about one model."""

    id: str
    name: str | None = None
    context: int | None = None
    max_input: int | None = None
    max_output: int | None = None
    vision: bool | None = None
    tools: bool | None = None
    reasoning: bool | None = None


@dataclass
class ProbeResult:
    """`models` is None exactly when the provider could not be asked; `error` says why."""

    models: list[Model] | None
    error: str | None = None

    @property
    def reachable(self) -> bool:
        return self.models is not None


Probe = Callable[[Provider, httpx.Client], list[Model]]
PROBES: dict[str, Probe] = {}


def probe(kind: str) -> Callable[[Probe], Probe]:
    def register(function: Probe) -> Probe:
        PROBES[kind] = function
        return function

    return register


# `gpt-oss.context_length`, and never `gpt-oss.rope.scaling.original_context_length`.
_CONTEXT_KEY = re.compile(r"[^.]+\.context_length")


@probe("ollama")
def ollama(provider: Provider, client: httpx.Client) -> list[Model]:
    """`/api/tags` lists what is pulled; `/api/show` gives each one's context and capabilities."""
    tags = client.get("/api/tags").raise_for_status().json()
    models = []
    for tag in tags.get("models", []):
        shown = (
            client.post("/api/show", json={"model": tag["name"]})
            .raise_for_status()
            .json()
        )
        capabilities = shown.get("capabilities") or []
        # An embedding model answers `/api/tags` too, and no agent can chat with it.
        if capabilities and "completion" not in capabilities:
            continue
        info = shown.get("model_info") or {}
        context = next(
            (value for key, value in info.items() if _CONTEXT_KEY.fullmatch(key)), None
        )
        models.append(
            Model(
                id=tag["name"],
                context=context,
                vision="vision" in capabilities if capabilities else None,
                tools="tools" in capabilities if capabilities else None,
                reasoning="thinking" in capabilities if capabilities else None,
            )
        )
    return models


@probe("litellm")
def litellm(provider: Provider, client: httpx.Client) -> list[Model]:
    """A LiteLLM gateway: `/model/info` carries the limits and flags its operator configured."""
    rows = client.get("/model/info").raise_for_status().json().get("data", [])
    models = []
    for row in rows:
        info = row.get("model_info") or {}
        if info.get("mode") not in (None, "chat", "responses"):
            continue
        models.append(
            Model(
                id=row["model_name"],
                context=info.get("max_input_tokens") or info.get("max_tokens"),
                max_input=info.get("max_input_tokens"),
                max_output=info.get("max_output_tokens"),
                vision=info.get("supports_vision"),
                tools=info.get("supports_function_calling"),
                reasoning=info.get("supports_reasoning"),
            )
        )
    return models


@probe("openai")
def openai(provider: Provider, client: httpx.Client) -> list[Model]:
    """Any OpenAI-compatible server: `/v1/models` gives ids and nothing else."""
    rows = client.get("/v1/models").raise_for_status().json().get("data", [])
    return [Model(id=row["id"]) for row in rows]


def run_probe(
    provider: Provider, transport: httpx.BaseTransport | None = None
) -> ProbeResult:
    """Probe one provider, turning every way of failing to ask into an unreachable result."""
    try:
        key = resolve_secret(provider.api_key)
    except SecretError as error:
        return ProbeResult(None, str(error))
    except (subprocess.SubprocessError, OSError) as error:  # it hung or could not start
        return ProbeResult(None, f"key command failed: {error}")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        with httpx.Client(
            base_url=provider.base_url.rstrip("/"),
            headers=headers,
            timeout=provider.timeout,
            transport=transport,
        ) as client:
            found = PROBES[provider.kind](provider, client)
    except httpx.HTTPStatusError as error:
        return ProbeResult(
            None, f"HTTP {error.response.status_code} from {error.request.url.path}"
        )
    except httpx.ConnectError:
        return ProbeResult(None, "connection refused")
    except httpx.TimeoutException:
        return ProbeResult(None, f"no answer in {provider.timeout:g}s")
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        return ProbeResult(None, f"unreadable answer: {type(error).__name__}: {error}")
    kept = [
        model
        for model in found
        if not any(fnmatchcase(model.id, pattern) for pattern in provider.exclude)
    ]
    return ProbeResult(kept)
