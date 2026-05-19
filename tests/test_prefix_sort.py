"""Prefix expansion must prefer shorter matches over alphabetically earlier ones.

'mor' expands to ['moral', 'more', 'moreover', ...] alphabetically.
'more' (4 chars) is shorter than 'moral' (5 chars) — the shortest
prefix match is closest to the query and should be preferred.

The snippet for an episode that only contains 'more' (not 'moral')
must show 'more' as match_term, not 'moral'.
"""

import json
import pytest


def _write_episode(podcasts_dir, stem, show, title, txt_content, srt_content=None):
    ep_dir = podcasts_dir / show / title
    ep_dir.mkdir(parents=True, exist_ok=True)
    meta = {"podcast": show, "title": title}
    (ep_dir / f"{stem}.json").write_text(json.dumps(meta), encoding="utf-8")
    (ep_dir / f"{stem}.txt").write_text(txt_content, encoding="utf-8")
    srt = srt_content or "1\n00:00:39,000 --> 00:00:42,000\nand so much more\n"
    (ep_dir / f"{stem}.srt").write_text(srt, encoding="utf-8")


@pytest.fixture
def more_moral_corpus(client, tmp_tree):
    """Corpus where an episode contains BOTH 'more' and 'moral' in different cues."""
    podcasts, _, _ = tmp_tree
    # ep-both: has 'more' early (00:00:39) and 'moral' late (01:00:06)
    _write_episode(
        podcasts, "2023-01-01_ep-both", "show", "ep-both",
        txt_content="awakening and so much more to explore, with a moral dimension",
        srt_content=(
            "1\n00:00:39,000 --> 00:00:42,000\nand so much more to explore\n\n"
            "2\n01:00:06,000 --> 01:00:09,000\nthe moral dimension of practice\n"
        ),
    )
    _write_episode(podcasts, "2023-01-02_ep-unrelated", "show", "ep-unrelated",
                   txt_content="cooking recipes and kitchen tips")
    return client


def test_shorter_prefix_match_wins(more_moral_corpus):
    """'mor' → 'more' (4 chars) is shorter than 'moral' (5 chars).
    The episode has 'more' at 00:00:39 and 'moral' at 01:00:06.
    match_term must be 'more' and timestamp must be 00:00:39."""
    r = more_moral_corpus.get("/api/search", params={"q": "mor"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    ep = next((e for e in eps if e["title"] == "ep-both"), None)
    assert ep is not None
    assert ep["match_term"] == "more", f"expected 'more', got '{ep['match_term']}'"
    assert ep["timestamp"] == "00:00:39", f"expected '00:00:39', got '{ep['timestamp']}'"
