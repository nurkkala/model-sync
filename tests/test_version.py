"""The `--version` flag: what it prints, from where, and that it never fails."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from model_sync import version
from model_sync.cli import app

ROOT = Path(__file__).resolve().parent.parent
DECLARED = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def _git(*args: str) -> list[str]:
    done = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return done.stdout.split() if done.returncode == 0 else []


def _key(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def test_first_line_is_name_and_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.splitlines()[0] == f"model-sync {DECLARED}"


def test_flag_answers_before_arguments_are_validated() -> None:
    result = CliRunner().invoke(app, ["--version", "no-such-command"])
    assert result.exit_code == 0
    assert result.stdout.startswith("model-sync ")


def test_number_is_the_file_when_metadata_disagrees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(version.importlib.metadata, "version", lambda _: "9.9.9")
    assert version.report()[0] == f"model-sync {DECLARED}"


def test_another_projects_pyproject_is_passed_over(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "other"\nversion = "7.0.0"\n'
    )
    assert version.checkout_version(tmp_path) == ""


def test_unreadable_pyproject_falls_through(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("not = [toml")
    assert version.checkout_version(tmp_path) == ""


def test_every_line_states_a_value() -> None:
    text = "\n".join(version.report())
    assert f"  repository  {ROOT}" in text
    assert re.search(r"  tag         (none yet|\S+, \d+ commits? back)", text)
    assert re.search(r"  commit      [0-9a-f]{7,40}", text)
    assert re.search(r"  tree        (clean|\d+ files? changed)", text)


def test_flag_survives_no_git_and_no_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_: str) -> None:
        raise version.importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(version, "git_lines", lambda *_: [])
    monkeypatch.setattr(version.importlib.metadata, "distribution", missing)
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        f"model-sync {DECLARED}",
        f"  code        {version.HERE}",
    ]


def test_version_file_agrees_with_the_tags() -> None:
    newest = _git("tag", "--list", "v*", "--sort=-v:refname")
    if not newest:
        pytest.skip("no git, or no release tag yet")
    here = _git("tag", "--points-at", "HEAD", "--list", "v*")
    if here:
        assert f"v{DECLARED}" in here
    else:
        assert _key(DECLARED) >= _key(newest[0])
