"""Snippet must show context even when the match is via fuzzy expansion.

If the user types 'Devanye' but the text contains 'Devaney', the fuzzy
expander adds 'devaney' to the query tokens.  The snippet should show
the 'Devaney' context, not be empty.
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
def devaney_corpus(client, tmp_tree):
    podcasts, _, _ = tmp_tree
    _write_episode(
        podcasts, "2023-07-13_devaney", "show", "ep-devaney",
        content="A Conversation with Kati Devaney about nonduality",
    )
    _write_episode(
        podcasts, "2023-01-01_unrelated", "show", "ep-unrelated",
        content="completely different topic about cooking",
    )
    return client


def test_fuzzy_match_has_nonempty_snippet(devaney_corpus):
    """Typo 'Devanye' should return a snippet containing 'Devaney'."""
    r = devaney_corpus.get("/api/search", params={"q": "Devanye"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    ep = next((e for e in eps if e["title"] == "ep-devaney"), None)
    assert ep is not None, "ep-devaney should be in results"
    assert ep["snippet"], "snippet must not be empty for fuzzy match"
    assert "devaney" in ep["snippet"].lower()
