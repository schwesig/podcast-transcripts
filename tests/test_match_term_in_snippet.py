"""match_term must always be a substring of the snippet.

If the term that triggered the snippet is not itself in the snippet text
(e.g. 'moreover' triggered BM25 but snippet only contains 'more'),
the API must fall back to a term that IS in the snippet so the frontend
can highlight it.
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
def mor_corpus(client, tmp_tree):
    podcasts, _, _ = tmp_tree
    _write_episode(podcasts, "2023-01-01_ep-moral", "show", "ep-moral",
                   txt_content="there is a moral dimension to this practice")
    _write_episode(podcasts, "2023-01-02_ep-more", "show", "ep-more",
                   txt_content="and more importantly we need to understand")
    _write_episode(podcasts, "2023-01-03_ep-unrelated", "show", "ep-unrelated",
                   txt_content="cooking recipes and kitchen tips")
    return client


def test_match_term_is_substring_of_snippet(mor_corpus):
    """For every result, match_term must appear in the snippet."""
    r = mor_corpus.get("/api/search", params={"q": "mor"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    assert len(eps) >= 2
    for ep in eps:
        assert ep["snippet"], f"{ep['title']} has empty snippet"
        assert ep["match_term"].lower() in ep["snippet"].lower(), (
            f"match_term '{ep['match_term']}' not in snippet '{ep['snippet']}'"
        )
