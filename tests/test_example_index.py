"""The sample index in the repo has to load, or it teaches a schema the tool refuses."""

from __future__ import annotations

from pathlib import Path

from model_sync.consumers import CONSUMERS
from model_sync.index import load_index
from model_sync.probes import PROBES

EXAMPLE = Path(__file__).resolve().parent.parent / "index.example.toml"


def test_the_example_index_loads_and_names_known_kinds() -> None:
    index = load_index(EXAMPLE)
    assert {provider.kind for provider in index.providers.values()} == set(PROBES)
    assert {consumer.kind for consumer in index.consumers.values()} == set(CONSUMERS)
    assert all(
        provider_id in index.providers
        for consumer in index.consumers.values()
        for provider_id in consumer.providers or []
    )
