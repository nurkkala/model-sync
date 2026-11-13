"""The provider index: the one hand-kept file, validated where it enters the program.

The index names every provider to probe and every consumer file to write. It also holds
the corrections a probe cannot supply (a display name, an output limit, a flag the
provider reports wrongly). A value written here beats the probed one.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONFIG_ENV = "MODEL_SYNC_CONFIG"
STATE_ENV = "MODEL_SYNC_STATE"

_ENV_REFERENCE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


class ConfigError(Exception):
    """The index is missing or malformed; the message names the file and the field."""


class SecretError(Exception):
    """An `api_key` reference could not be resolved."""


class ModelOverride(BaseModel):
    """Corrections for one model. Every field left out falls through to the probe."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    context: int | None = None
    max_input: int | None = None
    max_output: int | None = None
    vision: bool | None = None
    tools: bool | None = None
    reasoning: bool | None = None
    # Consumer kind -> keys merged into this model's entry in that consumer's file.
    extra: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    # The server's root, without `/v1`: each probe appends its own paths.
    base_url: str
    name: str | None = None
    # A literal, `$NAME` / `${NAME}` from the environment, or `!command` whose output is the key.
    api_key: str | None = None
    # False probes the provider for `status` and writes it to no consumer.
    sync: bool = True
    timeout: float = 5.0
    # Glob patterns of model ids to leave out.
    exclude: list[str] = Field(default_factory=list)
    # Output limit for every model here that has no override of its own.
    max_output: int | None = None
    # The window the server runs its models with, where that is smaller than what a
    # model reports: no model here is written with a larger context or input limit,
    # unless its own override says so.
    context: int | None = Field(default=None, gt=0)
    # Consumer kind -> keys merged into every model entry (`extra`), or into the entries
    # of models that reason (`reasoning_extra`).
    extra: dict[str, dict[str, Any]] = Field(default_factory=dict)
    reasoning_extra: dict[str, dict[str, Any]] = Field(default_factory=dict)
    models: dict[str, ModelOverride] = Field(default_factory=dict)


class ConsumerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    path: Path
    # Provider ids this consumer receives; absent means every provider with `sync = true`.
    providers: list[str] | None = None


class Index(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: dict[str, Provider] = Field(default_factory=dict)
    consumers: dict[str, ConsumerConfig] = Field(default_factory=dict)


def config_path() -> Path:
    if override := os.environ.get(CONFIG_ENV):
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "model-sync" / "index.toml"


def state_dir() -> Path:
    if override := os.environ.get(STATE_ENV):
        return Path(override).expanduser()
    base = os.environ.get("XDG_STATE_HOME") or "~/.local/state"
    return Path(base).expanduser() / "model-sync"


def load_index(path: Path) -> Index:
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise ConfigError(
            f"no index at {path}; see the README for its format"
        ) from None
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from None
    try:
        index = Index.model_validate(raw)
    except ValidationError as error:
        lines = [
            f"  {'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
            for issue in error.errors()
        ]
        raise ConfigError(f"{path}:\n" + "\n".join(lines)) from None
    for name, consumer in index.consumers.items():
        for provider_id in consumer.providers or []:
            if provider_id not in index.providers:
                raise ConfigError(
                    f"{path}:\n  consumers.{name}.providers: no provider named {provider_id!r}"
                )
    return index


def resolve_secret(value: str | None) -> str | None:
    """Turn an `api_key` setting into the key itself."""
    if value is None:
        return None
    if value.startswith("!"):
        done = subprocess.run(
            value[1:],
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if done.returncode != 0 or not done.stdout.strip():
            raise SecretError(f"key command exited {done.returncode} with no key")
        return done.stdout.strip()
    if match := _ENV_REFERENCE.fullmatch(value):
        name = match.group(1)
        if not os.environ.get(name):
            raise SecretError(f"${name} is not set")
        return os.environ[name]
    return value
