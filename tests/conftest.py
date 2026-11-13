"""Shared fixtures. No test reaches a real provider or a real configuration file."""

from __future__ import annotations

from pathlib import Path

import pytest

from model_sync.index import CONFIG_ENV, STATE_ENV, Index, load_index
from model_sync.probes import Model, ProbeResult

INDEX = """
[providers.local]
kind = "ollama"
base_url = "http://local.test"
max_output = 1000

[providers.local.reasoning_extra.opencode]
compatibility = { reasoningField = "reasoning" }

[providers.local.models."big:7b"]
name = "Big 7B"
max_output = 2000

[providers.gateway]
kind = "litellm"
base_url = "http://gateway.test"

[consumers.pi]
kind = "pi"
path = "{root}/pi/models.json"

[consumers.opencode]
kind = "opencode"
path = "{root}/opencode.jsonc"
"""

PI = """{
  "providers": {
    "local": {
      "baseUrl": "http://local.test/v1",
      "apiKey": "sk-keep-me",
      "models": [
        {"id": "big:7b", "name": "old name"},
        {"id": "gone:1b", "name": "Gone"}
      ]
    },
    "gateway": {
      "baseUrl": "http://gateway.test/v1",
      "models": [{"id": "remote-a", "name": "hand written"}]
    },
    "untouched": {"models": [{"id": "mine"}]}
  },
  "other": true
}
"""

OPENCODE = """{
  // the owner's opening comment
  "model": "local/gone:1b",
  "agents": { "title": { "model": "gateway/remote-a" } },
  "providers": {
    "local": {
      "name": "Local",
      // a comment above the models
      "models": {
        "gone:1b": { "name": "Gone" }
      }
    }, // a comment after local
    "gateway": {
      "models": {
        "remote-a": { "name": "hand written" },
      },
    },
  },
}
"""


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "pi").mkdir()
    (tmp_path / "pi" / "models.json").write_text(PI)
    (tmp_path / "opencode.jsonc").write_text(OPENCODE)
    (tmp_path / "index.toml").write_text(INDEX.replace("{root}", str(tmp_path)))
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / "index.toml"))
    monkeypatch.setenv(STATE_ENV, str(tmp_path / "state"))
    return tmp_path


@pytest.fixture
def index(root: Path) -> Index:
    return load_index(root / "index.toml")


@pytest.fixture
def probes() -> dict[str, ProbeResult]:
    """`local` answers with two models; `gateway` cannot be reached."""
    return {
        "local": ProbeResult(
            [
                Model(id="new:3b", context=4096, tools=True),
                Model(id="big:7b", context=8192, vision=True, reasoning=True),
            ]
        ),
        "gateway": ProbeResult(None, "connection refused"),
    }
