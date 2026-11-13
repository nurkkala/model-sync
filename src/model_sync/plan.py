"""Work out what each consumer file would gain, lose, and change, and stage it.

The one rule with teeth is here: a provider that could not be asked is left exactly as
the consumer has it. A model leaves a file only when its provider answered and did not
list it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from model_sync.consumers import CONSUMERS, Consumer, ConsumerError, Reference
from model_sync.index import Index
from model_sync.probes import ProbeResult
from model_sync.resolve import deep_merge, resolve


class _Absent:
    def __repr__(self) -> str:
        return "ABSENT"


ABSENT = _Absent()


@dataclass
class ProviderPlan:
    provider_id: str
    reachable: bool
    reason: str | None = None
    # Entries left alone because the provider could not be asked.
    kept: int = 0
    live: int = 0
    # The consumer file has no block for this provider yet.
    created: bool = False
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    # Model id -> (key, old value, new value), with ABSENT for a key on one side only.
    changed: dict[str, list[tuple[str, Any, Any]]] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        return bool(self.created or self.added or self.removed or self.changed)


@dataclass
class Stale:
    """A setting that names a model its provider answered without."""

    reference: Reference
    # The index has a table for the model, so its owner expects it back.
    expected: bool


@dataclass
class ConsumerPlan:
    name: str
    kind: str
    path: Path
    providers: list[ProviderPlan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stale: list[Stale] = field(default_factory=list)
    # Every model served in this run, as (provider id, model id): what a stale setting
    # can be repointed to.
    live: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None
    consumer: Consumer | None = None

    @property
    def has_changes(self) -> bool:
        return any(provider.has_changes for provider in self.providers)


def entry_changes(
    old: dict[str, Any], new: dict[str, Any]
) -> list[tuple[str, Any, Any]]:
    """The top-level keys on which two entries differ, in the new entry's order first."""
    keys = list(new) + [key for key in old if key not in new]
    return [
        (key, old.get(key, ABSENT), new.get(key, ABSENT))
        for key in keys
        if old.get(key, ABSENT) != new.get(key, ABSENT)
    ]


def plan_consumer(
    name: str, index: Index, probes: dict[str, ProbeResult]
) -> ConsumerPlan:
    config = index.consumers[name]
    consumer = CONSUMERS[config.kind](name, config)
    plan = ConsumerPlan(
        name=name, kind=config.kind, path=consumer.path, consumer=consumer
    )
    try:
        consumer.load()
    except ConsumerError as error:
        plan.error = str(error)
        return plan

    managed = (
        config.providers
        if config.providers is not None
        else [
            provider_id
            for provider_id, provider in index.providers.items()
            if provider.sync
        ]
    )
    served: dict[str, list[str]] = {}
    for provider_id in managed:
        provider = index.providers[provider_id]
        result = probes[provider_id]
        current = consumer.current(provider_id)
        if not result.reachable:
            plan.providers.append(
                ProviderPlan(provider_id, False, result.error, kept=len(current or {}))
            )
            continue

        entries = {
            model.id: deep_merge(
                consumer.entry(model), model.extra.get(config.kind, {})
            )
            for model in resolve(provider, result.models)
        }
        served[provider_id] = list(entries)
        before = current or {}
        step = ProviderPlan(
            provider_id,
            True,
            live=len(entries),
            created=current is None,
            added=[model_id for model_id in entries if model_id not in before],
            removed=[model_id for model_id in before if model_id not in entries],
        )
        for model_id, entry in entries.items():
            if model_id in before and (
                changes := entry_changes(before[model_id], entry)
            ):
                step.changed[model_id] = changes
        plan.providers.append(step)
        if step.has_changes:
            try:
                consumer.stage(provider_id, provider, entries)
            except ConsumerError as error:
                plan.error = str(error)
                return plan

    plan.live = [
        (provider_id, model_id)
        for provider_id in managed
        for model_id in served.get(provider_id, [])
    ]
    for reference in consumer.references():
        provider_id, model_id = reference.provider_id, reference.model_id
        if provider_id in served and model_id not in served[provider_id]:
            expected = model_id in index.providers[provider_id].models
            plan.stale.append(Stale(reference, expected))
            plan.warnings.append(
                f"{reference.where} names {provider_id}/{model_id}, "
                f"which {provider_id} does not serve"
                + ("; the index has a table for it" if expected else "")
            )
    return plan
