from __future__ import annotations

from model_sync.index import Provider
from model_sync.probes import Model
from model_sync.resolve import deep_merge, derived_name, resolve


def provider(**settings) -> Provider:
    return Provider(kind="ollama", base_url="http://x", **settings)


def test_the_index_beats_the_probe_field_by_field():
    probed = [
        Model(
            id="m", name="probed", context=100, max_output=50, vision=True, tools=False
        )
    ]
    over = {"m": {"name": "mine", "max_output": 7, "vision": False, "tools": True}}
    (model,) = resolve(provider(models=over), probed)
    assert (model.name, model.max_output) == ("mine", 7)
    assert (model.vision, model.tools) == (False, True)
    # Fields the index leaves out keep the probed value.
    assert model.context == 100
    (bare,) = resolve(provider(), probed)
    assert (bare.vision, bare.tools) == (True, False)


def test_output_limit_precedence_is_model_then_provider_then_probe():
    probed = [Model(id="a", max_output=50), Model(id="b", max_output=50)]
    a, b = resolve(provider(max_output=30, models={"a": {"max_output": 7}}), probed)
    assert (a.max_output, b.max_output) == (7, 30)
    (c,) = resolve(provider(), [Model(id="c", max_output=50)])
    assert c.max_output == 50


def test_unreported_flags_default_to_tools_without_vision_or_reasoning():
    (model,) = resolve(provider(), [Model(id="some:latest")])
    assert (model.tools, model.vision, model.reasoning) == (True, False, False)
    assert model.name == "some"
    assert (model.context, model.max_output) == (None, None)


def test_derived_name():
    assert derived_name("qwen3:4b") == "qwen3 4b"
    assert derived_name("plain") == "plain"


def test_index_order_first_then_the_rest_sorted_and_absent_overrides_ignored():
    probed = [
        Model(id="zeta"),
        Model(id="alpha"),
        Model(id="second"),
        Model(id="first"),
    ]
    over = {"first": {}, "not-served": {"name": "ghost"}, "second": {}}
    assert [model.id for model in resolve(provider(models=over), probed)] == [
        "first",
        "second",
        "alpha",
        "zeta",
    ]


def test_extras_merge_provider_then_reasoning_then_model():
    settings = {
        "extra": {"pi": {"compat": {"a": 1, "b": 1}}},
        "reasoning_extra": {"pi": {"compat": {"b": 2}}, "opencode": {"r": True}},
        "models": {"thinker": {"extra": {"pi": {"compat": {"a": 3}}}}},
    }
    probed = [Model(id="thinker", reasoning=True), Model(id="plain", reasoning=False)]
    thinker, plain = resolve(provider(**settings), probed)
    assert thinker.extra == {
        "pi": {"compat": {"a": 3, "b": 2}},
        "opencode": {"r": True},
    }
    assert plain.extra == {"pi": {"compat": {"a": 1, "b": 1}}}


def test_deep_merge_copies_and_replaces_non_tables():
    base = {"t": {"x": [1]}, "s": 1}
    merged = deep_merge(base, {"t": {"y": 2}, "s": {"now": "a table"}})
    assert merged == {"t": {"x": [1], "y": 2}, "s": {"now": "a table"}}
    merged["t"]["x"].append(2)
    assert base == {"t": {"x": [1]}, "s": 1}
