"""Exact query term must show ALL occurrences across text sources.

When 'Devaney' appears in the title, summary/txt, and SRT at different
timestamps, searching for 'devaney' must return one match entry per
distinct occurrence (distinct snippet or distinct timestamp).
"""

import json
import pytest


def _write_episode(podcasts_dir, stem, show, title, txt_content, srt_content, meta_extra=None):
    ep_dir = podcasts_dir / show / title
    ep_dir.mkdir(parents=True, exist_ok=True)
    meta = {"podcast": show, "title": title}
    if meta_extra:
        meta.update(meta_extra)
    (ep_dir / f"{stem}.json").write_text(json.dumps(meta), encoding="utf-8")
    (ep_dir / f"{stem}.txt").write_text(txt_content, encoding="utf-8")
    (ep_dir / f"{stem}.srt").write_text(srt_content, encoding="utf-8")


SRT_TWO_DEVANEY = (
    "1\n00:00:47,000 --> 00:00:50,000\nA Conversation with Kati Devaney\n\n"
    "2\n00:16:08,000 --> 00:16:11,000\nKathryn Devaney Ph.D. is a neuroscientist\n"
)


@pytest.fixture
def devaney_corpus(client, tmp_tree):
    podcasts, _, _ = tmp_tree
    _write_episode(
        podcasts, "2023-07-13_ep-devaney", "show", "ep-devaney",
        txt_content="in this episode I'm speaking with guest Katie Devaney. Catherine Devaney is a Neuroscientist",
        srt_content=SRT_TWO_DEVANEY,
    )
    _write_episode(
        podcasts, "2023-01-01_ep-unrelated", "show", "ep-unrelated",
        txt_content="cooking recipes and kitchen tips",
        srt_content="1\n00:00:00,000 --> 00:00:01,000\ncooking\n",
    )
    return client


def test_exact_term_multiple_occurrences(devaney_corpus):
    """'devaney' appears in txt (twice) and srt (twice) — must return >1 match."""
    r = devaney_corpus.get("/api/search", params={"q": "devaney"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    ep = next((e for e in eps if e["title"] == "ep-devaney"), None)
    assert ep is not None
    assert len(ep["matches"]) > 1, (
        f"expected multiple matches for 'devaney', got {len(ep['matches'])}: {ep['matches']}"
    )


def test_different_timestamps_per_occurrence(devaney_corpus):
    """Different SRT cues must produce different timestamps in matches."""
    r = devaney_corpus.get("/api/search", params={"q": "devaney"})
    eps = r.json()["episodes"]
    ep = next(e for e in eps if e["title"] == "ep-devaney")
    timestamps = [m["timestamp"] for m in ep["matches"] if m["timestamp"]]
    assert len(set(timestamps)) > 1, (
        f"expected multiple distinct timestamps, got: {timestamps}"
    )
