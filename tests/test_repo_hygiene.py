"""Guards for things that must never be committed: secrets, raw CMS downloads and app state."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", path], cwd=ROOT, capture_output=True
    )
    return result.returncode == 0


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "data/state.db",
        "data/raw/hcpc2026_oct_anweb.zip",
        "data/raw/anything.csv",
        "anywhere/else.sqlite",
        "anywhere/else.db",
    ],
)
def test_secret_raw_and_state_paths_are_ignored(path: str) -> None:
    assert is_ignored(path)


def test_the_reference_database_is_tracked_not_ignored() -> None:
    # It holds only CMS public-use Level II data, so it is committed and shipped in the image.
    assert not is_ignored("data/claimguard.db")


def test_the_test_fixture_database_is_tracked() -> None:
    assert not is_ignored("tests/fixtures/reference.db")


def test_env_example_is_tracked() -> None:
    assert not is_ignored(".env.example")
