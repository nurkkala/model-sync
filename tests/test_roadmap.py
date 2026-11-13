"""A ticket that no longer parses, or a link to one that is gone, has to fail here rather than accumulate.

Both tests shell out to the console script rather than importing the module: a packaging
mistake, such as an entry point naming a function that moved, then fails in the suite instead
of the next time someone types `make todo`.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


@pytest.fixture(scope="module")
def roadmap() -> str:
    exe = shutil.which("roadmap")
    if exe is None:
        pytest.skip("roadmap-ledger is not installed in this environment")
    return exe


def test_roadmap_is_valid_and_current(roadmap: str) -> None:
    result = subprocess.run(
        [roadmap, "check"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_resolves_the_roadmap_from_the_working_directory(roadmap: str) -> None:
    """One installed copy serves every repo only while resolution walks up from the cwd.

    A regression here would not fail loudly: it would quietly answer about whichever repo
    holds the tool's own source.
    """
    result = subprocess.run(
        [roadmap, "check"], cwd=HERE, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
