"""Shared fixtures: isolate every test from the real podcast tree.

main.py resolves PODCASTS / PENDING / UPLOAD_TOKEN_FILE at import time and
the route handlers look them up via the module globals, so monkeypatching
those attributes is enough to redirect all filesystem state into tmp_path.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402


@pytest.fixture
def tmp_tree(tmp_path, monkeypatch):
    podcasts = tmp_path / "podcasts"
    pending = tmp_path / ".pending"
    podcasts.mkdir()
    pending.mkdir()
    token_file = tmp_path / ".upload_token"

    monkeypatch.setattr(main, "PODCASTS", podcasts)
    monkeypatch.setattr(main, "PENDING", pending)
    monkeypatch.setattr(main, "UPLOAD_TOKEN_FILE", token_file)
    return podcasts, pending, token_file


@pytest.fixture
def client(tmp_tree):
    return TestClient(main.app)
