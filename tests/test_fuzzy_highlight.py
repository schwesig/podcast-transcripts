"""Tests for correct timestamp and highlight term for fuzzy matches.

1. _find_timestamp must be case-insensitive (SRT cues may have mixed case).
2. Search results must include a `match_term` field containing the token
   that actually matched, so the frontend can highlight the right word.
"""

import json
import pytest


def _write_episode(podcasts_dir, stem, show, title, txt_content, srt_content):
    ep_dir = podcasts_dir / show / title
    ep_dir.mkdir(parents=True, exist_ok=True)
    meta = {"podcast": show, "title": title}
    (ep_dir / f"{stem}.json").write_text(json.dumps(meta), encoding="utf-8")
    (ep_dir / f"{stem}.txt").write_text(txt_content, encoding="utf-8")
    (ep_dir / f"{stem}.srt").write_text(srt_content, encoding="utf-8")


SRT_WITH_DEVANEY = (
    "1\n00:05:30,000 --> 00:05:33,000\nA Conversation with Kati Devaney\n\n"
    "2\n00:10:00,000 --> 00:10:03,000\nsomething else\n"
)


@pytest.fixture
def devaney_corpus(client, tmp_tree):
    podcasts, _, _ = tmp_tree
    _write_episode(
        podcasts, "2023-07-13_devaney", "show", "ep-devaney",
        txt_content="A Conversation with Kati Devaney about nonduality",
        srt_content=SRT_WITH_DEVANEY,
    )
    _write_episode(
        podcasts, "2023-01-01_unrelated", "show", "ep-unrelated",
        txt_content="completely different topic about cooking",
        srt_content="1\n00:00:00,000 --> 00:00:01,000\ncooking tips\n",
    )
    return client


def test_timestamp_is_correct_not_zero(devaney_corpus):
    """Fuzzy match 'Devanye' → 'Devaney' should find cue at 00:05:30, not 00:00:00."""
    r = devaney_corpus.get("/api/search", params={"q": "Devanye"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    ep = next((e for e in eps if e["title"] == "ep-devaney"), None)
    assert ep is not None
    assert ep["timestamp"] == "00:05:30"


def test_result_includes_match_term(devaney_corpus):
    """Result must include `match_term` so the frontend can highlight it."""
    r = devaney_corpus.get("/api/search", params={"q": "Devanye"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    ep = next((e for e in eps if e["title"] == "ep-devaney"), None)
    assert ep is not None
    assert "match_term" in ep
    assert ep["match_term"].lower() == "devaney"


def test_exact_query_match_term_equals_query(devaney_corpus):
    """For exact matches, match_term should equal the query token."""
    r = devaney_corpus.get("/api/search", params={"q": "devaney"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    ep = next((e for e in eps if e["title"] == "ep-devaney"), None)
    assert ep is not None
    assert ep["match_term"].lower() == "devaney"
