"""Fuzzy search tests.

The /api/search endpoint should tolerate minor typos by fuzzy-expanding
the query tokens before BM25 scoring.
"""

import json
import pytest


def _write_episode(podcasts_dir, stem, show, title, content):
    ep_dir = podcasts_dir / show / title
    ep_dir.mkdir(parents=True, exist_ok=True)
    meta = {"podcast": show, "title": title}
    (ep_dir / f"{stem}.json").write_text(json.dumps(meta), encoding="utf-8")
    (ep_dir / f"{stem}.txt").write_text(content, encoding="utf-8")
    (ep_dir / f"{stem}.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nok\n", encoding="utf-8"
    )


@pytest.fixture
def fuzzy_corpus(client, tmp_tree):
    """Two-episode corpus attached to the same tmp_tree as `client`."""
    podcasts, _, _ = tmp_tree
    _write_episode(podcasts, "2023-01-01_ep-med", "show", "ep-med",
                   content="meditation is a daily practice")
    _write_episode(podcasts, "2023-01-02_ep-unrelated", "show", "ep-unrelated",
                   content="completely different topic about cooking")
    return client


def test_exact_typo_still_finds_result(fuzzy_corpus):
    """'meditaton' (missing i) should still return the meditation episode."""
    r = fuzzy_corpus.get("/api/search", params={"q": "meditaton"})
    assert r.status_code == 200
    titles = [ep["title"] for ep in r.json()["episodes"]]
    assert "ep-med" in titles


def test_typo_does_not_return_unrelated(fuzzy_corpus):
    """Fuzzy match should not return completely unrelated episodes."""
    r = fuzzy_corpus.get("/api/search", params={"q": "meditaton"})
    assert r.status_code == 200
    titles = [ep["title"] for ep in r.json()["episodes"]]
    assert "ep-unrelated" not in titles


def test_exact_query_still_works(fuzzy_corpus):
    """Exact queries must continue to work as before (corpus has 2 docs)."""
    r = fuzzy_corpus.get("/api/search", params={"q": "meditation"})
    assert r.status_code == 200
    titles = [ep["title"] for ep in r.json()["episodes"]]
    assert "ep-med" in titles
    assert "ep-unrelated" not in titles
