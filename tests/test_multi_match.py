"""Each episode in search results must expose ALL matches, not just the first.

When an episode contains 'more' and 'moral' and the query is 'mor',
the response must include both as separate entries in ep['matches'],
each with its own snippet and timestamp.
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


SRT_TWO_MATCHES = (
    "1\n00:00:39,000 --> 00:00:42,000\nand so much more to explore\n\n"
    "2\n01:00:06,000 --> 01:00:09,000\nthe moral dimension of practice\n"
)


@pytest.fixture
def two_match_corpus(client, tmp_tree):
    podcasts, _, _ = tmp_tree
    _write_episode(
        podcasts, "2023-01-01_ep-both", "show", "ep-both",
        txt_content="awakening and so much more to explore, with a moral dimension",
        srt_content=SRT_TWO_MATCHES,
    )
    _write_episode(
        podcasts, "2023-01-02_ep-unrelated", "show", "ep-unrelated",
        txt_content="cooking recipes and kitchen tips",
        srt_content="1\n00:00:00,000 --> 00:00:01,000\ncooking\n",
    )
    return client


def test_episode_has_matches_list(two_match_corpus):
    """Result episodes must have a 'matches' list."""
    r = two_match_corpus.get("/api/search", params={"q": "mor"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    ep = next((e for e in eps if e["title"] == "ep-both"), None)
    assert ep is not None
    assert "matches" in ep
    assert isinstance(ep["matches"], list)


def test_all_expanded_terms_produce_matches(two_match_corpus):
    """'mor' expands to 'more' and 'moral' — both must appear as matches."""
    r = two_match_corpus.get("/api/search", params={"q": "mor"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    ep = next((e for e in eps if e["title"] == "ep-both"), None)
    assert ep is not None
    match_terms = {m["match_term"] for m in ep["matches"]}
    assert "more" in match_terms
    assert "moral" in match_terms


def test_each_match_has_snippet_and_timestamp(two_match_corpus):
    """Every match entry must have snippet and timestamp."""
    r = two_match_corpus.get("/api/search", params={"q": "mor"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    ep = next((e for e in eps if e["title"] == "ep-both"), None)
    assert ep is not None
    for m in ep["matches"]:
        assert m["snippet"], f"match {m['match_term']} has empty snippet"
        assert m["timestamp"], f"match {m['match_term']} has empty timestamp"


def test_timestamps_are_correct(two_match_corpus):
    """'more' match → 00:00:39, 'moral' match → 01:00:06."""
    r = two_match_corpus.get("/api/search", params={"q": "mor"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    ep = next((e for e in eps if e["title"] == "ep-both"), None)
    assert ep is not None
    by_term = {m["match_term"]: m for m in ep["matches"]}
    assert by_term["more"]["timestamp"] == "00:00:39"
    assert by_term["moral"]["timestamp"] == "01:00:06"
