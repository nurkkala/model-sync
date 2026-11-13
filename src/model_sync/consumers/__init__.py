"""One consumer per file format: a program whose configuration lists models.

Adding a consumer kind means subclassing `Consumer` in a module of this package,
decorating the class with `@consumer("<kind>")`, and importing the module at the bottom
of this file.

A consumer owns exactly one thing in its file: the model list of each provider it is
handed. Every other key belongs to the file's owner and is left as it was.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from model_sync.index import ConsumerConfig, Provider
from model_sync.resolve import Resolved


class ConsumerError(Exception):
    """This consumer's file cannot be read or edited; the others can still be planned."""


class Consumer(ABC):
    kind: str

    def __init__(self, name: str, config: ConsumerConfig) -> None:
        self.name = name
        self.path = config.path.expanduser()

    @abstractmethod
    def load(self) -> None:
        """Read the file. Raise `ConsumerError` when it cannot be understood."""

    @abstractmethod
    def current(self, provider_id: str) -> dict[str, dict[str, Any]] | None:
        """The provider's model entries by id, or None when the file has no such provider."""

    @abstractmethod
    def entry(self, model: Resolved) -> dict[str, Any]:
        """One model in this file's vocabulary, before the index's `extra` keys are merged."""

    @abstractmethod
    def stage(
        self, provider_id: str, provider: Provider, entries: dict[str, dict[str, Any]]
    ) -> None:
        """Make `entries` the provider's whole model list, in memory."""

    @abstractmethod
    def references(self) -> list[tuple[str, str, str]]:
        """Settings that name a model, as (where, provider id, model id)."""

    @abstractmethod
    def text(self) -> str:
        """The file as it would be written."""

    def save(self, backup_dir: Path) -> Path | None:
        """Write the staged file. Returns the backup made of the one it replaced, if any."""
        target = self.path.resolve()  # write through a symlink, never over it
        backup = None
        mode = 0o600
        if target.exists():
            mode = stat.S_IMODE(target.stat().st_mode)
            folder = backup_dir / self.name
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = folder / f"{stamp}-{target.name}"
            shutil.copy2(target, backup)
            backup.chmod(0o600)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}."
        )
        try:
            with os.fdopen(handle, "w") as out:
                out.write(self.text())
            os.chmod(temporary, mode)
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return backup


CONSUMERS: dict[str, type[Consumer]] = {}


def consumer(kind: str) -> Callable[[type[Consumer]], type[Consumer]]:
    def register(cls: type[Consumer]) -> type[Consumer]:
        cls.kind = kind
        CONSUMERS[kind] = cls
        return cls

    return register


def v1_url(provider: Provider) -> str:
    """The OpenAI-compatible endpoint both agents talk to."""
    return provider.base_url.rstrip("/") + "/v1"


from model_sync.consumers import opencode, pi  # noqa: F401
