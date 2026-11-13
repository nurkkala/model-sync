"""The plan and both writers, end to end, through the command."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from model_sync import cli, jsonc
from model_sync.plan import ABSENT, entry_changes, plan_consumer
from model_sync.probes import Model, ProbeResult

runner = CliRunner()


@pytest.fixture
def run(root, probes, monkeypatch):
    monkeypatch.setattr(cli, "run_probe", lambda provider: probes[_id_of(provider)])

    def invoke(*arguments: str):
        return runner.invoke(cli.app, list(arguments))

    return invoke


def _id_of(provider) -> str:
    return "local" if "local" in provider.base_url else "gateway"


def test_entry_changes_reports_both_directions_of_absence():
    old = {"same": 1, "moved": 1, "dropped": True}
    new = {"moved": 2, "same": 1, "added": "x"}
    assert entry_changes(old, new) == [
        ("moved", 1, 2),
        ("added", ABSENT, "x"),
        ("dropped", True, ABSENT),
    ]


def test_plan_adds_removes_and_changes_for_a_reachable_provider(index, probes):
    plan = plan_consumer("pi", index, probes)
    local = plan.providers[0]
    assert local.reachable and local.live == 2 and not local.created
    assert local.added == ["new:3b"]
    assert local.removed == ["gone:1b"]
    assert ("name", "old name", "Big 7B") in local.changed["big:7b"]
    assert ("maxTokens", ABSENT, 2000) in local.changed["big:7b"]


def test_an_unreachable_provider_is_left_exactly_as_it_was(index, probes):
    for name in ("pi", "opencode"):
        plan = plan_consumer(name, index, probes)
        gateway = plan.providers[1]
        assert not gateway.reachable
        assert gateway.reason == "connection refused"
        assert gateway.kept == 1
        assert not gateway.has_changes
        assert (
            plan.consumer.current("gateway")
            == {
                "pi": {"remote-a": {"id": "remote-a", "name": "hand written"}},
                "opencode": {"remote-a": {"name": "hand written"}},
            }[name]
        )


def test_a_reachable_provider_serving_nothing_empties_its_list(index, probes):
    probes["local"] = ProbeResult([])
    plan = plan_consumer("pi", index, probes)
    assert plan.providers[0].removed == ["big:7b", "gone:1b"]
    assert plan.consumer.current("local") == {}


def test_a_vanished_default_is_warned_about_only_for_a_reachable_provider(
    index, probes, root
):
    (root / "pi" / "settings.json").write_text(
        json.dumps({"defaultProvider": "local", "defaultModel": "gone:1b"})
    )
    pi = plan_consumer("pi", index, probes)
    assert len(pi.warnings) == 1
    assert "names local/gone:1b, which local does not serve" in pi.warnings[0]
    # opencode's `model` names the removed one; its title agent names a model on the
    # unreachable gateway, about which nothing is known and so nothing is said.
    opencode = plan_consumer("opencode", index, probes)
    assert len(opencode.warnings) == 1
    assert opencode.warnings[0].startswith("`model` in ")

    (root / "pi" / "settings.json").write_text(
        json.dumps({"defaultProvider": "local", "defaultModel": "big:7b"})
    )
    assert plan_consumer("pi", index, probes).warnings == []


def test_diff_writes_nothing_and_reports_through_its_exit_code(run, root):
    before = {
        path: path.read_text()
        for path in (root / "pi/models.json", root / "opencode.jsonc")
    }
    result = run("diff")
    assert result.exit_code == 0
    assert "+ new:3b" in result.output and "- gone:1b" in result.output
    assert "unreachable (connection refused); 1 entry left as they are" in result.output
    assert run("diff", "--exit-code").exit_code == 1
    assert {path: path.read_text() for path in before} == before
    assert not (root / "state").exists()


def test_apply_writes_pi_keeping_everything_it_does_not_own(run, root):
    path = root / "pi" / "models.json"
    path.chmod(0o640)  # not what a fresh temporary file gets
    original = path.read_text()
    assert run("apply", "pi").exit_code == 0
    data = json.loads(path.read_text())

    assert data["providers"]["local"]["models"] == [
        {
            "id": "big:7b",
            "name": "Big 7B",
            "contextWindow": 8192,
            "maxTokens": 2000,
            "reasoning": True,
            "input": ["text", "image"],
        },
        {
            "id": "new:3b",
            "name": "new 3b",
            "contextWindow": 4096,
            "maxTokens": 1000,
            "reasoning": False,
            "input": ["text"],
        },
    ]
    assert data["providers"]["local"]["apiKey"] == "sk-keep-me"
    assert data["providers"]["gateway"] == json.loads(original)["providers"]["gateway"]
    assert data["providers"]["untouched"] == {"models": [{"id": "mine"}]}
    assert data["other"] is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o640

    (backup,) = (root / "state" / "backups" / "pi").iterdir()
    assert backup.read_text() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    # opencode was not named, so it was not written.
    assert not (root / "state" / "backups" / "opencode").exists()


def test_apply_edits_opencode_inside_the_models_span_only(run, root):
    path = root / "opencode.jsonc"
    original = path.read_text()
    assert run("apply", "opencode").exit_code == 0
    text = path.read_text()

    expected_models = """{
        "big:7b": {
          "name": "Big 7B",
          "limit": { "context": 8192, "output": 2000 },
          "capabilities": { "tools": true, "input": ["text", "image"], "output": ["text"] },
          "compatibility": { "reasoningField": "reasoning" }
        },
        "new:3b": {
          "name": "new 3b",
          "limit": { "context": 4096, "output": 1000 },
          "capabilities": { "tools": true, "input": ["text"], "output": ["text"] }
        }
      }"""
    old_models = '{\n        "gone:1b": { "name": "Gone" }\n      }'
    assert original.count(old_models) == 1
    assert text == original.replace(old_models, expected_models)
    for comment in (
        "// the owner's opening comment",
        "// a comment above the models",
        "// a comment after local",
    ):
        assert comment in text


def test_apply_twice_changes_nothing_the_second_time(run, root):
    assert run("apply").exit_code == 0
    written = {
        path: path.read_text()
        for path in (root / "pi/models.json", root / "opencode.jsonc")
    }
    backups = sorted((root / "state").rglob("*.*"))
    result = run("apply")
    assert result.exit_code == 0
    assert "wrote" not in result.output
    assert result.output.count("up to date") == 2
    assert {path: path.read_text() for path in written} == written
    assert sorted((root / "state").rglob("*.*")) == backups
    assert run("diff", "--exit-code").exit_code == 0


def test_a_provider_missing_from_a_file_gets_a_block(run, root, probes):
    (root / "pi" / "models.json").write_text('{"providers": {}}')
    (root / "opencode.jsonc").write_text('{\n  // mine\n  "theme": "dark"\n}\n')
    probes["gateway"] = ProbeResult([Model(id="remote-a", context=10, max_input=10)])
    result = run("apply")
    assert result.exit_code == 0, result.output
    assert result.output.count("new provider block") == 4

    pi = json.loads((root / "pi" / "models.json").read_text())["providers"]
    assert pi["local"]["baseUrl"] == "http://local.test/v1"
    assert pi["local"]["api"] == "openai-completions"
    assert pi["local"]["apiKey"] == "none"
    assert [model["id"] for model in pi["gateway"]["models"]] == ["remote-a"]

    text = (root / "opencode.jsonc").read_text()
    assert "// mine" in text
    data = jsonc.parse(text).value
    assert data["theme"] == "dark"
    assert list(data["providers"]) == ["local", "gateway"]
    assert data["providers"]["gateway"] == {
        "package": "@opencode/ai/providers/openai-compatible",
        "settings": {"baseURL": "http://gateway.test/v1"},
        "models": {
            "remote-a": {
                "name": "remote-a",
                "limit": {"context": 10, "input": 10},
                "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
            }
        },
    }
    assert run("diff", "--exit-code").exit_code == 0


def test_a_missing_pi_file_is_created_private(run, root):
    path = root / "pi" / "models.json"
    path.unlink()
    assert run("apply", "pi").exit_code == 0
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(json.loads(path.read_text())["providers"]) == ["local"]


def test_a_symlinked_file_is_written_through(run, root):
    real = root / "real.json"
    link = root / "pi" / "models.json"
    link.rename(real)
    link.symlink_to(real)
    assert run("apply", "pi").exit_code == 0
    assert link.is_symlink()
    assert "new:3b" in real.read_text()


def test_an_unreadable_consumer_is_skipped_and_the_other_still_written(run, root):
    (root / "opencode.jsonc").write_text('{ "providers": oops }')
    result = run("apply")
    assert result.exit_code == 2
    assert "skipped:" in result.output and "line 1" in result.output
    assert (root / "opencode.jsonc").read_text() == '{ "providers": oops }'
    assert "new:3b" in (root / "pi" / "models.json").read_text()


def test_a_consumer_restricted_to_some_providers_ignores_the_rest(run, root, probes):
    index = root / "index.toml"
    index.write_text(
        index.read_text().replace('kind = "pi"', 'kind = "pi"\nproviders = ["gateway"]')
    )
    probes["gateway"] = ProbeResult([])
    assert run("apply", "pi").exit_code == 0
    data = json.loads((root / "pi" / "models.json").read_text())["providers"]
    assert [model["id"] for model in data["local"]["models"]] == ["big:7b", "gone:1b"]
    assert data["gateway"]["models"] == []


def test_a_status_only_provider_is_shown_and_never_written(run, root):
    index = root / "index.toml"
    index.write_text(
        index.read_text().replace(
            'base_url = "http://local.test"',
            'base_url = "http://local.test"\nsync = false',
        )
    )
    status = run("status")
    assert "status only" in status.output and "big:7b" in status.output
    assert (
        "gateway  litellm  http://gateway.test  unreachable (connection refused)"
        in status.output
    )
    result = run("diff", "--exit-code")
    assert result.exit_code == 0
    assert "local" not in result.output.replace(str(root), "")


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (
            ('kind = "ollama"', 'kind = "ollma"'),
            "providers.local.kind: no probe named 'ollma'",
        ),
        (('kind = "pi"', 'kind = "pie"'), "consumers.pi.kind: no consumer named 'pie'"),
        (("max_output = 1000", "max_outptu = 1000"), "providers.local.max_outptu"),
        (
            ('kind = "pi"', 'kind = "pi"\nproviders = ["nope"]'),
            "consumers.pi.providers: no provider named 'nope'",
        ),
        (("[providers.gateway]", "[providers.gateway"), "index.toml"),
    ],
)
def test_a_bad_index_is_refused_naming_the_field(run, root, edit, message):
    index = root / "index.toml"
    index.write_text(index.read_text().replace(*edit))
    result = run("diff")
    assert result.exit_code == 2
    assert message in result.output


def test_a_missing_index_and_an_unknown_consumer_are_refused(run, root, monkeypatch):
    assert "no consumer named 'nope'" in run("diff", "nope").output
    monkeypatch.setenv("MODEL_SYNC_CONFIG", str(Path(root) / "absent.toml"))
    result = run("status")
    assert result.exit_code == 2 and "no index at" in result.output


def test_a_provider_with_nothing_to_change_keeps_its_hand_formatting(run, root, probes):
    path = root / "opencode.jsonc"
    hand = '"remote-a": {"capabilities": {"output": ["text"], "input": ["text"], "tools": true}, "name": "remote-a"},'
    path.write_text(
        path.read_text().replace('"remote-a": { "name": "hand written" },', hand)
    )
    probes["gateway"] = ProbeResult([Model(id="remote-a")])
    result = run("apply", "opencode")
    assert result.exit_code == 0
    assert "gateway  1 live  up to date" in result.output
    text = path.read_text()
    assert hand in text
    assert "new:3b" in text


# --- `apply` asks about a setting that names a model no longer served (TODO-001-apply-asks)


@pytest.fixture
def answer(run, monkeypatch):
    """Run `apply` as if on a terminal, typing `keys` at its questions."""
    monkeypatch.setattr(cli, "_interactive", lambda: True)

    def invoke(keys: str, *arguments: str):
        return runner.invoke(cli.app, ["apply", *arguments], input=keys)

    return invoke


def _backups(root: Path, consumer: str) -> list[str]:
    folder = root / "state" / "backups" / consumer
    return sorted(path.name.split("-", 2)[2] for path in folder.iterdir())


def test_replace_repoints_the_setting_and_nothing_around_it(answer, root):
    result = answer("1\n", "opencode")
    assert result.exit_code == 0, result.output
    assert " 1  local/big:7b" in result.output and " 2  local/new:3b" in result.output
    text = (root / "opencode.jsonc").read_text()
    data = jsonc.parse(text).value
    assert data["model"] == "local/big:7b"
    # The title agent names a model on the unreachable gateway: unknown, so unasked.
    assert data["agents"] == {"title": {"model": "gateway/remote-a"}}
    assert result.output.count("choice") == 1
    assert "// the owner's opening comment" in text
    assert _backups(root, "opencode") == ["opencode.jsonc"]


def test_remove_deletes_the_setting_and_leaves_valid_text(answer, root):
    result = answer("r\n", "opencode")
    assert result.exit_code == 0, result.output
    text = (root / "opencode.jsonc").read_text()
    data = jsonc.parse(text).value
    assert "model" not in data
    assert data["agents"] == {"title": {"model": "gateway/remote-a"}}
    assert '// the owner\'s opening comment\n  "agents"' in text


def test_leave_is_the_default_and_keeps_the_warning(answer, root):
    result = answer("\n", "opencode")
    assert result.exit_code == 0, result.output
    assert jsonc.parse((root / "opencode.jsonc").read_text()).value["model"] == (
        "local/gone:1b"
    )
    assert "warning:" in result.output


def test_a_wrong_answer_is_asked_again(answer, root):
    result = answer("9\nx\n2\n", "opencode")
    assert result.exit_code == 0, result.output
    assert "no such choice: 9" in result.output and "no such choice: x" in result.output
    assert jsonc.parse((root / "opencode.jsonc").read_text()).value["model"] == (
        "local/new:3b"
    )


def test_apply_off_a_terminal_warns_and_edits_no_setting(run, root):
    result = run("apply", "opencode")
    assert result.exit_code == 0, result.output
    assert "warning:" in result.output and "choice" not in result.output
    assert jsonc.parse((root / "opencode.jsonc").read_text()).value["model"] == (
        "local/gone:1b"
    )


def test_a_model_the_index_names_draws_the_warning_and_no_question(
    answer, root, probes
):
    # `big:7b` has a table in the index; here its provider answers without it.
    probes["local"] = ProbeResult([Model(id="new:3b", context=4096, tools=True)])
    path = root / "opencode.jsonc"
    path.write_text(path.read_text().replace("local/gone:1b", "local/big:7b"))
    result = answer("r\n", "opencode")
    assert result.exit_code == 0, result.output
    assert "the index has a table for it" in result.output
    assert "choice" not in result.output
    assert jsonc.parse(path.read_text()).value["model"] == "local/big:7b"


def test_a_setting_is_written_when_the_models_are_already_current(answer, root):
    assert answer("l\n", "opencode").exit_code == 0
    path = root / "opencode.jsonc"
    before = path.read_text()
    result = answer("2\n", "opencode")
    assert result.exit_code == 0, result.output
    assert "up to date" in result.output and "wrote" in result.output
    assert path.read_text() == before.replace("local/gone:1b", "local/new:3b")


def test_pi_default_is_replaced_in_settings_json_with_a_backup(answer, root):
    settings = root / "pi" / "settings.json"
    settings.write_text(
        json.dumps(
            {"theme": "dark", "defaultProvider": "local", "defaultModel": "gone:1b"}
        )
    )
    result = answer("1\n", "pi")
    assert result.exit_code == 0, result.output
    assert json.loads(settings.read_text()) == {
        "theme": "dark",
        "defaultProvider": "local",
        "defaultModel": "big:7b",
    }
    assert list(json.loads(settings.read_text())) == [
        "theme",
        "defaultProvider",
        "defaultModel",
    ]
    assert _backups(root, "pi") == ["models.json", "settings.json"]


def test_pi_default_is_removed_and_the_rest_of_settings_kept(answer, root):
    settings = root / "pi" / "settings.json"
    settings.write_text(
        json.dumps(
            {"theme": "dark", "defaultProvider": "local", "defaultModel": "gone:1b"}
        )
    )
    result = answer("r\n", "pi")
    assert result.exit_code == 0, result.output
    assert json.loads(settings.read_text()) == {"theme": "dark"}


def test_pi_settings_are_untouched_when_the_answer_is_leave(answer, root):
    settings = root / "pi" / "settings.json"
    written = json.dumps({"defaultProvider": "local", "defaultModel": "gone:1b"})
    settings.write_text(written)
    result = answer("l\n", "pi")
    assert result.exit_code == 0, result.output
    assert settings.read_text() == written
    assert _backups(root, "pi") == ["models.json"]


def test_removing_an_agents_one_key_removes_the_block_and_then_agents(
    answer, root, probes
):
    # Both providers answer, so both settings are stale, and neither model is served.
    probes["gateway"] = ProbeResult([Model(id="remote-b")])
    result = answer("l\nr\n", "opencode")
    assert result.exit_code == 0, result.output
    text = (root / "opencode.jsonc").read_text()
    data = jsonc.parse(text).value
    assert "agents" not in data and data["model"] == "local/gone:1b"
    assert "// the owner's opening comment" in text


def test_an_agent_holding_other_keys_keeps_its_block(answer, root, probes):
    probes["gateway"] = ProbeResult([Model(id="remote-b")])
    path = root / "opencode.jsonc"
    path.write_text(
        path.read_text().replace(
            '{ "title": { "model": "gateway/remote-a" } }',
            '{ "title": { "model": "gateway/remote-a", "temperature": 0 },'
            ' "other": { "model": "gateway/remote-a" } }',
        )
    )
    result = answer("l\nr\nr\n", "opencode")
    assert result.exit_code == 0, result.output
    assert jsonc.parse(path.read_text()).value["agents"] == {
        "title": {"temperature": 0}
    }


def test_input_ending_at_the_question_leaves_settings_and_still_writes(answer, root):
    settings = root / "pi" / "settings.json"
    written = json.dumps({"defaultProvider": "local", "defaultModel": "gone:1b"})
    settings.write_text(written)
    result = answer("")
    assert result.exit_code == 0, result.output
    # One question, at the first consumer; none at the second.
    assert result.output.count("choice") == 1
    assert "input ended" in result.output
    assert settings.read_text() == written
    assert jsonc.parse((root / "opencode.jsonc").read_text()).value["model"] == (
        "local/gone:1b"
    )
    pi = json.loads((root / "pi" / "models.json").read_text())
    assert "new:3b" in [model["id"] for model in pi["providers"]["local"]["models"]]
    assert "new:3b" in (root / "opencode.jsonc").read_text()
