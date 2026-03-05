from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def git_identity_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", os.getenv("GIT_AUTHOR_NAME", "agvv-test"))
    monkeypatch.setenv(
        "GIT_AUTHOR_EMAIL", os.getenv("GIT_AUTHOR_EMAIL", "agvv-test@example.com")
    )
    monkeypatch.setenv(
        "GIT_COMMITTER_NAME", os.getenv("GIT_COMMITTER_NAME", "agvv-test")
    )
    monkeypatch.setenv(
        "GIT_COMMITTER_EMAIL", os.getenv("GIT_COMMITTER_EMAIL", "agvv-test@example.com")
    )
