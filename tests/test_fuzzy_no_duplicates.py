"""Fuzzy query must not produce duplicate match entries.

When 'Devanye' fuzzy-expands to multiple tokens that all resolve to
'devaney', the result must contain the same number of matches as an
exact 'devaney' search — no duplicates.
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


SRT = (
    "1\n00:00:47,000 --> 00:00:50,000\nKatie Devaney. Catherine Devaney is a Neuroscientist\n\n"
    "2\n00:01:33,000 --> 00:01:36,000\nthat I call A Conversation with Katie Devaney. Katie welcome\n\n"
    "3\n00:16:08,000 --> 00:16:11,000\naffects the brain? What does it even do according to Katie Devaney\n"
)


@pytest.fixture
def devaney_corpus(client, tmp_tree):
    podcasts, _, _ = tmp_tree
    _write_episode(
        podcasts, "2023-07-13_ep-devaney", "show", "ep-devaney",
        txt_content="speaking with guest Katie Devaney today",
        srt_content=SRT,
    )
    return client


def test_fuzzy_match_count_equals_exact(devaney_corpus):
    """Fuzzy 'devanye' must return same number of matches as exact 'devaney'."""
    r_exact = devaney_corpus.get("/api/search", params={"q": "devaney"})
    r_fuzzy = devaney_corpus.get("/api/search", params={"q": "devanye"})

    eps_exact = r_exact.json()["episodes"]
    eps_fuzzy = r_fuzzy.json()["episodes"]

    ep_exact = next((e for e in eps_exact if e["title"] == "ep-devaney"), None)
    ep_fuzzy = next((e for e in eps_fuzzy if e["title"] == "ep-devaney"), None)

    assert ep_exact is not None
    assert ep_fuzzy is not None

    n_exact = len(ep_exact["matches"])
    n_fuzzy = len(ep_fuzzy["matches"])
    assert n_exact == n_fuzzy, (
        f"exact 'devaney' → {n_exact} matches, fuzzy 'devanye' → {n_fuzzy} matches; "
        f"fuzzy should not produce duplicates"
    )


def test_no_duplicate_timestamp_term_pairs(devaney_corpus):
    """No two match entries may share the same (match_term, timestamp) pair."""
    r = devaney_corpus.get("/api/search", params={"q": "devanye"})
    eps = r.json()["episodes"]
    ep = next((e for e in eps if e["title"] == "ep-devaney"), None)
    assert ep is not None
    pairs = [(m["match_term"], m["timestamp"]) for m in ep["matches"]]
    assert len(pairs) == len(set(pairs)), f"duplicate (match_term, timestamp) pairs: {pairs}"
