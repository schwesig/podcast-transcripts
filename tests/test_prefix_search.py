"""Prefix search tests.

Short query tokens (e.g. 'mor') should match all vocabulary tokens that
start with that prefix (e.g. 'more', 'morphine', 'morning').  Results
must include a non-empty snippet with the matched word highlighted.
"""

import json
import pytest


def _write_episode(podcasts_dir, stem, show, title, txt_content):
    ep_dir = podcasts_dir / show / title
    ep_dir.mkdir(parents=True, exist_ok=True)
    meta = {"podcast": show, "title": title}
    (ep_dir / f"{stem}.json").write_text(json.dumps(meta), encoding="utf-8")
    (ep_dir / f"{stem}.txt").write_text(txt_content, encoding="utf-8")
    (ep_dir / f"{stem}.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nok\n", encoding="utf-8"
    )


@pytest.fixture
def prefix_corpus(client, tmp_tree):
    podcasts, _, _ = tmp_tree
    _write_episode(podcasts, "2023-01-01_ep-morphine", "show", "ep-morphine",
                   txt_content="she had a morphine pump implanted to manage pain")
    _write_episode(podcasts, "2023-01-02_ep-morning", "show", "ep-morning",
                   txt_content="every morning she practiced mindfulness")
    _write_episode(podcasts, "2023-01-03_ep-unrelated", "show", "ep-unrelated",
                   txt_content="cooking recipes and kitchen tips")
    return client


def test_prefix_finds_matching_episodes(prefix_corpus):
    """'mor' should match episodes containing 'morphine' and 'morning'."""
    r = prefix_corpus.get("/api/search", params={"q": "mor"})
    assert r.status_code == 200
    titles = {ep["title"] for ep in r.json()["episodes"]}
    assert "ep-morphine" in titles
    assert "ep-morning" in titles
    assert "ep-unrelated" not in titles


def test_prefix_results_have_snippet(prefix_corpus):
    """All prefix-matched episodes must have a non-empty snippet."""
    r = prefix_corpus.get("/api/search", params={"q": "mor"})
    assert r.status_code == 200
    for ep in r.json()["episodes"]:
        assert ep["snippet"], f"{ep['title']} has empty snippet"


def test_prefix_match_term_starts_with_query(prefix_corpus):
    """match_term must start with the query prefix so the frontend can highlight."""
    r = prefix_corpus.get("/api/search", params={"q": "mor"})
    assert r.status_code == 200
    for ep in r.json()["episodes"]:
        assert ep["match_term"].startswith("mor"), (
            f"match_term '{ep['match_term']}' does not start with 'mor'"
        )
