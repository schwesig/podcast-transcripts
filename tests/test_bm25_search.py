"""BM25 search tests.

The /api/search endpoint should rank results by BM25 relevance instead of
returning them in filesystem order.  The key invariant: a document where the
query term appears many times (or where it is rare across the corpus) should
rank above one where it appears only once.
"""

import json
import pytest

TOKEN = "secret-token-123"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_episode(podcasts_dir, stem, show, title, content, summary=""):
    ep_dir = podcasts_dir / show / title
    ep_dir.mkdir(parents=True, exist_ok=True)
    meta = {"podcast": show, "title": title, "summary": summary}
    (ep_dir / f"{stem}.json").write_text(json.dumps(meta), encoding="utf-8")
    (ep_dir / f"{stem}.txt").write_text(content, encoding="utf-8")
    (ep_dir / f"{stem}.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nok\n", encoding="utf-8"
    )


@pytest.fixture
def corpus(tmp_tree):
    podcasts, _, _ = tmp_tree
    # ep_a mentions "meditation" 10 times → should rank higher
    _write_episode(
        podcasts, "2023-01-01_ep-a", "show", "ep-a",
        content=" ".join(["meditation"] * 10),
    )
    # ep_b mentions "meditation" once
    _write_episode(
        podcasts, "2023-01-02_ep-b", "show", "ep-b",
        content="meditation and other things",
    )
    # ep_c has no mention of "meditation"
    _write_episode(
        podcasts, "2023-01-03_ep-c", "show", "ep-c",
        content="completely unrelated topic",
    )
    return podcasts


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_search_returns_only_matching_docs(client, corpus):
    r = client.get("/api/search", params={"q": "meditation"})
    assert r.status_code == 200
    titles = [ep["title"] for ep in r.json()["episodes"]]
    assert "ep-c" not in titles


def test_search_ranks_high_frequency_first(client, corpus):
    r = client.get("/api/search", params={"q": "meditation"})
    assert r.status_code == 200
    titles = [ep["title"] for ep in r.json()["episodes"]]
    assert titles.index("ep-a") < titles.index("ep-b")


def test_search_empty_query_returns_all(client, corpus):
    r = client.get("/api/search", params={"q": ""})
    assert r.status_code == 200
    titles = {ep["title"] for ep in r.json()["episodes"]}
    assert {"ep-a", "ep-b", "ep-c"} == titles


def test_search_no_results_for_unknown_term(client, corpus):
    r = client.get("/api/search", params={"q": "xyzzy"})
    assert r.status_code == 200
    assert r.json()["episodes"] == []


def test_search_result_has_snippet(client, corpus):
    r = client.get("/api/search", params={"q": "meditation"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    assert len(eps) >= 1
    for ep in eps:
        assert "snippet" in ep
        assert "meditation" in ep["snippet"].lower()


def test_search_result_has_timestamp_when_match_in_srt(client, corpus, tmp_tree):
    """When the query term appears in a SRT cue, the result includes the
    timestamp of that cue (HH:MM:SS) in the `timestamp` field."""
    podcasts, _, _ = tmp_tree
    ep_dir = podcasts / "show" / "ep-ts"
    ep_dir.mkdir(parents=True)
    meta = {"podcast": "show", "title": "ep-ts"}
    (ep_dir / "2023-01-01_ep-ts.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )
    (ep_dir / "2023-01-01_ep-ts.txt").write_text(
        "some content", encoding="utf-8"
    )
    srt = (
        "1\n00:03:15,000 --> 00:03:18,000\ndeep meditation practice\n\n"
        "2\n00:10:00,000 --> 00:10:03,000\nsomething else\n"
    )
    (ep_dir / "2023-01-01_ep-ts.srt").write_text(srt, encoding="utf-8")

    r = client.get("/api/search", params={"q": "meditation"})
    assert r.status_code == 200
    eps = r.json()["episodes"]
    ts_ep = next((ep for ep in eps if ep["title"] == "ep-ts"), None)
    assert ts_ep is not None
    assert ts_ep["timestamp"] == "00:03:15"
