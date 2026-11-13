"""opencode's `opencode.jsonc`: JSON with comments, each provider holding a map of models.

The file is edited as text. Only the span of a provider's `models` value is replaced, so
the owner's comments everywhere else survive; a comment inside a replaced `models` value
does not.
"""

from __future__ import annotations

import json
from typing import Any

from model_sync import jsonc
from model_sync.consumers import Consumer, ConsumerError, consumer, v1_url
from model_sync.index import Provider
from model_sync.resolve import Resolved


def _inline(value: Any) -> str:
    """JSON on one line in the file's own style: `{ "context": 1, "input": ["text"] }`."""
    if isinstance(value, dict):
        if not value:
            return "{}"
        return (
            "{ "
            + ", ".join(f"{json.dumps(k)}: {_inline(v)}" for k, v in value.items())
            + " }"
        )
    if isinstance(value, list):
        return "[" + ", ".join(_inline(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def _block(value: dict[str, Any], indent: str, depth: int) -> str:
    """An object spread over lines for `depth` levels, then inline."""
    if depth == 0 or not value:
        return _inline(value)
    inner = indent + "  "
    lines = [
        f"{inner}{json.dumps(key)}: "
        + (_block(item, inner, depth - 1) if isinstance(item, dict) else _inline(item))
        for key, item in value.items()
    ]
    return "{\n" + ",\n".join(lines) + f"\n{indent}}}"


@consumer("opencode")
class Opencode(Consumer):
    def load(self) -> None:
        try:
            self.source = self.path.read_text()
        except FileNotFoundError:
            self.source = '{\n  "$schema": "https://opencode.ai/config.json",\n  "providers": {}\n}\n'
        self._parse()

    def _parse(self) -> None:
        try:
            self.root = jsonc.parse(self.source)
        except jsonc.JsoncError as error:
            raise ConsumerError(f"{self.path}: {error}") from None
        if not self.root.is_object:
            raise ConsumerError(f"{self.path}: expected an object")

    def current(self, provider_id: str) -> dict[str, dict[str, Any]] | None:
        block = self.root.find("providers", provider_id)
        if block is None:
            return None
        models = block.value.get("models", {}) if block.is_object else {}
        return dict(models) if isinstance(models, dict) else {}

    def entry(self, model: Resolved) -> dict[str, Any]:
        limit = {
            key: value
            for key, value in (
                ("context", model.context),
                ("input", model.max_input),
                ("output", model.max_output),
            )
            if value is not None
        }
        entry: dict[str, Any] = {"name": model.name}
        if limit:
            entry["limit"] = limit
        entry["capabilities"] = {
            "tools": model.tools,
            "input": ["text", "image"] if model.vision else ["text"],
            "output": ["text"],
        }
        return entry

    def stage(
        self, provider_id: str, provider: Provider, entries: dict[str, dict[str, Any]]
    ) -> None:
        providers = self.root.find("providers")
        if providers is None:
            self.source = jsonc.insert_member(self.source, self.root, "providers", "{}")
            self._parse()
            providers = self.root.find("providers")
        if not providers.is_object:
            raise ConsumerError(f"{self.path}: `providers` is not an object")

        block = providers.find(provider_id)
        if block is None:
            # The key is deliberately absent: opencode keeps keys in its own auth store.
            fresh: dict[str, Any] = {}
            if provider.name:
                fresh["name"] = provider.name
            fresh["package"] = "@opencode/ai/providers/openai-compatible"
            fresh["settings"] = {"baseURL": v1_url(provider)}
            fresh["models"] = entries
            indent = jsonc.line_indent(self.source, providers.start) + "  "
            self.source = jsonc.insert_member(
                self.source, providers, provider_id, _block(fresh, indent, 3)
            )
        elif not block.is_object:
            raise ConsumerError(
                f"{self.path}: `providers.{provider_id}` is not an object"
            )
        elif (models := block.find("models")) is None:
            indent = jsonc.line_indent(self.source, block.start) + "  "
            self.source = jsonc.insert_member(
                self.source, block, "models", _block(entries, indent, 2)
            )
        else:
            indent = jsonc.line_indent(self.source, block.members["models"].key_start)
            self.source = jsonc.replace_value(
                self.source, models, _block(entries, indent, 2)
            )
        self._parse()

    def references(self) -> list[tuple[str, str, str]]:
        data = self.root.value
        named = [("`model`", data.get("model"))]
        agents = data.get("agents")
        if isinstance(agents, dict):
            named += [
                (f"`agents.{name}.model`", agent.get("model"))
                for name, agent in agents.items()
                if isinstance(agent, dict)
            ]
        found = []
        for where, value in named:
            if isinstance(value, str) and "/" in value:
                provider_id, model_id = value.split("/", 1)
                found.append((f"{where} in {self.path}", provider_id, model_id))
        return found

    def text(self) -> str:
        return self.source
