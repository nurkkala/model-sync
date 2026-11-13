"""Combine what a probe reported with what the index says, the index winning."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, Field

from model_sync.index import ModelOverride, Provider
from model_sync.probes import Model


class Resolved(BaseModel):
    """One model as it will be written: every question a consumer asks has an answer."""

    id: str
    name: str
    context: int | None
    max_input: int | None
    max_output: int | None
    vision: bool
    tools: bool
    reasoning: bool
    # Consumer kind -> keys to merge into the entry.
    extra: dict[str, dict[str, Any]] = Field(default_factory=dict)


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """`over` laid on `base`: tables merge key by key, anything else is replaced."""
    merged = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def derived_name(model_id: str) -> str:
    """A display name for a model the index does not name: `qwen3:4b` reads as `qwen3 4b`."""
    return model_id.removesuffix(":latest").replace(":", " ")


def _first(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _capped(reported: int | None, cap: int | None) -> int | None:
    """The reported value held to the provider's cap; the cap itself when nothing is reported."""
    if reported is None or cap is None:
        return _first(reported, cap)
    return min(reported, cap)


def resolve(provider: Provider, probed: list[Model]) -> list[Resolved]:
    """Lay the index over the probe. Models the index names come first, in its order."""
    by_id = {model.id: model for model in probed}
    listed = [model_id for model_id in provider.models if model_id in by_id]
    ordered = listed + sorted(
        model_id for model_id in by_id if model_id not in provider.models
    )

    resolved = []
    for model_id in ordered:
        found = by_id[model_id]
        over = provider.models.get(model_id, ModelOverride())
        # A model with no word either way is assumed to call tools, since an agent that
        # cannot is no use, and assumed neither to see images nor to reason.
        tools = _first(over.tools, found.tools, True)
        vision = _first(over.vision, found.vision, False)
        reasoning = _first(over.reasoning, found.reasoning, False)

        kinds = set(provider.extra) | set(over.extra)
        if reasoning:
            kinds |= set(provider.reasoning_extra)
        extra = {}
        for kind in sorted(kinds):
            merged = provider.extra.get(kind, {})
            if reasoning:
                merged = deep_merge(merged, provider.reasoning_extra.get(kind, {}))
            extra[kind] = deep_merge(merged, over.extra.get(kind, {}))

        resolved.append(
            Resolved(
                id=model_id,
                name=_first(over.name, found.name, derived_name(model_id)),
                # A model's own override is the last word, so it may exceed the cap. No
                # input limit is invented for a model that reports none.
                context=_first(over.context, _capped(found.context, provider.context)),
                max_input=_first(
                    over.max_input,
                    None
                    if found.max_input is None
                    else _capped(found.max_input, provider.context),
                ),
                # The provider-wide default is an index value too, so it also beats the probe.
                max_output=_first(
                    over.max_output, provider.max_output, found.max_output
                ),
                vision=vision,
                tools=tools,
                reasoning=reasoning,
                extra=extra,
            )
        )
    return resolved
