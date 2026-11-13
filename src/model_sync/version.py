"""`--version`: the release, and the code behind it.

A version says which release. Between releases it stops saying which code, and on an
editable install the two come apart without limit, so the flag prints both.
"""

from __future__ import annotations

import datetime
import importlib.metadata
import subprocess
import tomllib
from pathlib import Path

DIST = "model-sync"
HERE = Path(__file__).resolve().parent


def git_lines(cwd: Path, *args: str) -> list[str]:
    """The output lines of one git command, or none when git or a repository is missing."""
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return done.stdout.splitlines() if done.returncode == 0 else []


def checkout_version(start: Path | None = None) -> str:
    """The version in the `pyproject.toml` of the checkout this code runs from; "" outside one.

    An editable install writes its metadata once and never revisits it, so the metadata
    reports the version in place at install time. Where the code runs from a tree, the
    tree's file is the source of the number.
    """
    here = start or HERE
    for directory in (here, *here.parents):
        pyproject = directory / "pyproject.toml"
        if not pyproject.exists():
            continue
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            return ""
        # The walk can reach a workspace root or an unrelated repo, whose version is
        # somebody else's.
        project = data.get("project")
        if isinstance(project, dict) and project.get("name") == DIST:
            return str(project.get("version", ""))
    return ""


def metadata_version() -> str:
    """The version the installer recorded, which is the one copy a wheel carries."""
    try:
        return importlib.metadata.version(DIST)
    except importlib.metadata.PackageNotFoundError:
        return ""


def current_version() -> str:
    return checkout_version() or metadata_version() or "unknown"


def installed_at() -> str:
    """When the distribution was put in place, read from its own metadata directory."""
    try:
        path = getattr(importlib.metadata.distribution(DIST), "_path", None)
        stamp = datetime.datetime.fromtimestamp(
            Path(path).stat().st_mtime, datetime.UTC
        )
    except (OSError, TypeError, ValueError, importlib.metadata.PackageNotFoundError):
        return ""
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def provenance() -> list[str]:
    """One labeled fact per line. A field with nothing wrong still states its value."""
    when = installed_at()
    lines = [f"  installed   {when}"] if when else []
    top = git_lines(HERE, "rev-parse", "--show-toplevel")
    if not top:
        return [*lines, f"  code        {HERE}"]
    repo = Path(top[0])
    lines.append(f"  repository  {repo}")
    tag = git_lines(repo, "describe", "--tags", "--abbrev=0")
    if tag:
        back = git_lines(repo, "rev-list", "--count", f"{tag[0]}..HEAD")
        n = int(back[0]) if back and back[0].strip().isdigit() else 0
        lines.append(f"  tag         {tag[0]}, {_count(n, 'commit')} back")
    else:
        lines.append("  tag         none yet")
    head = git_lines(repo, "rev-parse", "--short", "HEAD")
    if head:
        lines.append(f"  commit      {head[0]}")
    changed = sum(
        1 for line in git_lines(repo, "status", "--porcelain") if line.strip()
    )
    lines.append(
        f"  tree        {_count(changed, 'file') + ' changed' if changed else 'clean'}"
    )
    return lines


def report() -> list[str]:
    """What `--version` prints: the name and number first, then what is running."""
    return [f"{DIST} {current_version()}", *provenance()]
