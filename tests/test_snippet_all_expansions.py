"""All matched episodes must have a snippet, even when the match is via
a fuzzy-expanded token that differs from match_term.

Scenario: query 'meditatoin' expands to ['meditating', 'meditation', ...].
Episode A contains 'meditating', episode B contains 'meditation'.
Both must show a snippet — not just the first one found.
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
def multi_expansion_corpus(client, tmp_tree):
    podcasts, _, _ = tmp_tree
    # ep-a contains "meditating" (one expansion of "meditatoin")
    _write_episode(podcasts, "2023-01-01_ep-a", "show", "ep-a",
                   txt_content="she was meditating deeply every morning")
    # ep-b contains "meditation" (another expansion)
    _write_episode(podcasts, "2023-01-02_ep-b", "show", "ep-b",
                   txt_content="the practice of meditation brings clarity")
    # ep-c is unrelated
    _write_episode(podcasts, "2023-01-03_ep-c", "show", "ep-c",
                   txt_content="cooking recipes and kitchen tips")
    return client


def test_all_matched_episodes_have_snippet(multi_expansion_corpus):
    """Every episode in results must have a non-empty snippet."""
    r = multi_expansion_corpus.get("/api/search", params={"q": "meditatoin"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    matched = {ep["title"] for ep in eps}
    assert "ep-c" not in matched, "unrelated ep should not appear"
    assert matched, "should have at least one result"
    for ep in eps:
        assert ep["snippet"], f"{ep['title']} has empty snippet"
