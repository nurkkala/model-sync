"""pi's `~/.pi/agent/models.json`: plain JSON, each provider holding a list of models."""

from __future__ import annotations

import json
from typing import Any

from model_sync.consumers import Consumer, ConsumerError, consumer, v1_url
from model_sync.index import Provider
from model_sync.resolve import Resolved


@consumer("pi")
class Pi(Consumer):
    def load(self) -> None:
        try:
            self.data = json.loads(self.path.read_text())
        except FileNotFoundError:
            self.data = {}
        except json.JSONDecodeError as error:
            raise ConsumerError(f"{self.path}: {error}") from None
        if not isinstance(self.data, dict) or not isinstance(
            self.data.get("providers", {}), dict
        ):
            raise ConsumerError(
                f"{self.path}: expected an object holding a `providers` object"
            )

    def current(self, provider_id: str) -> dict[str, dict[str, Any]] | None:
        block = self.data.get("providers", {}).get(provider_id)
        if block is None:
            return None
        return {entry["id"]: entry for entry in block.get("models", [])}

    def entry(self, model: Resolved) -> dict[str, Any]:
        entry: dict[str, Any] = {"id": model.id, "name": model.name}
        if model.context is not None:
            entry["contextWindow"] = model.context
        if model.max_output is not None:
            entry["maxTokens"] = model.max_output
        entry["reasoning"] = model.reasoning
        entry["input"] = ["text", "image"] if model.vision else ["text"]
        return entry

    def stage(
        self, provider_id: str, provider: Provider, entries: dict[str, dict[str, Any]]
    ) -> None:
        providers = self.data.setdefault("providers", {})
        if provider_id not in providers:
            block: dict[str, Any] = {}
            if provider.name:
                block["name"] = provider.name
            block["baseUrl"] = v1_url(provider)
            block["api"] = "openai-completions"
            # pi resolves `$NAME` and `!command` itself, and hides a provider that has no
            # key at all, so a keyless server gets a placeholder.
            block["apiKey"] = provider.api_key or "none"
            providers[provider_id] = block
        providers[provider_id]["models"] = list(entries.values())

    def references(self) -> list[tuple[str, str, str]]:
        settings = self.path.with_name("settings.json")
        try:
            data = json.loads(settings.read_text())
        except (OSError, json.JSONDecodeError):
            return []
        provider_id, model_id = data.get("defaultProvider"), data.get("defaultModel")
        if isinstance(provider_id, str) and isinstance(model_id, str):
            return [(f"the default in {settings}", provider_id, model_id)]
        return []

    def text(self) -> str:
        return json.dumps(self.data, indent=2, ensure_ascii=False) + "\n"
