"""Timestamp must match the same term as the snippet, not an arbitrary
earlier prefix expansion.

Scenario: query 'mor', prefix-expanded to ['moral', 'more', ...].
Episode has SRT cues with 'more' at 00:00:39 and 'moral' at 01:00:06.
Snippet shows 'more' context → timestamp must be 00:00:39, not 01:00:06.
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


SRT_MORE_FIRST = (
    "1\n00:00:39,000 --> 00:00:42,000\nand so much more to explore\n\n"
    "2\n01:00:06,000 --> 01:00:09,000\nthe moral dimension of practice\n"
)


@pytest.fixture
def more_corpus(client, tmp_tree):
    podcasts, _, _ = tmp_tree
    _write_episode(
        podcasts, "2023-01-01_ep-more", "show", "ep-more",
        txt_content="awakening and so much more to explore in this podcast",
        srt_content=SRT_MORE_FIRST,
    )
    _write_episode(
        podcasts, "2023-01-02_ep-unrelated", "show", "ep-unrelated",
        txt_content="cooking recipes and kitchen tips",
        srt_content="1\n00:00:00,000 --> 00:00:01,000\ncooking\n",
    )
    return client


def test_timestamp_matches_snippet_term(more_corpus):
    """'mor' → snippet shows 'more' context → timestamp must be 00:00:39."""
    r = more_corpus.get("/api/search", params={"q": "mor"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    ep = next((e for e in eps if e["title"] == "ep-more"), None)
    assert ep is not None
    assert ep["match_term"] == "more"
    assert ep["timestamp"] == "00:00:39"
