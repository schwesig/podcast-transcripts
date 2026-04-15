"""Baseline coverage for the filename / JSON validation helpers.

These tests pin the current behaviour of main.classify_upload,
main.STEM_RE and main.check_json_meta so that later refactors (e.g.
the /upload/plan endpoint) cannot silently regress them.
"""

import pytest
from fastapi import HTTPException

from main import STEM_RE, check_json_meta, classify_upload


class _FakeUpload:
    """Minimal stand-in for starlette.UploadFile: only .filename is read."""

    def __init__(self, filename):
        self.filename = filename


def test_stem_re_accepts_canonical_slug():
    assert STEM_RE.match("2023-08-23_reverse-meditation-with-andrew-holecek")


@pytest.mark.parametrize(
    "bad",
    [
        "2023-08-23_Reverse-Meditation",  # uppercase
        "23-08-23_foo",                   # short year
        "2023-8-23_foo",                  # single-digit month
        "2023-08-23_foo_bar",             # underscore inside slug
        "2023-08-23_foo bar",             # space inside slug
        "2023-08-23_",                    # empty slug
    ],
)
def test_stem_re_rejects_malformed(bad):
    assert not STEM_RE.match(bad)


def test_classify_upload_happy_path():
    base, ext = classify_upload(_FakeUpload("2023-08-23_foo.json"))
    assert base == "2023-08-23_foo"
    assert ext == "json"


@pytest.mark.parametrize(
    "bad",
    [
        "../evil.json",
        "nested/2023-08-23_foo.json",
        r"back\slash.json",
        "2023-08-23_foo.md",
        "no-extension",
        "",
    ],
)
def test_classify_upload_rejects_bad_names(bad):
    with pytest.raises(ValueError):
        classify_upload(_FakeUpload(bad))


def test_check_json_meta_requires_podcast_and_title():
    with pytest.raises(HTTPException):
        check_json_meta({"podcast": "Show"})
    with pytest.raises(HTTPException):
        check_json_meta({"title": "Ep"})
    with pytest.raises(HTTPException):
        check_json_meta({"podcast": "", "title": "Ep"})


def test_check_json_meta_accepts_minimal_object():
    meta = check_json_meta({"podcast": "Show", "title": "Ep"})
    assert meta["podcast"] == "Show"
    assert meta["title"] == "Ep"


def test_check_json_meta_rejects_oversized_title():
    with pytest.raises(HTTPException):
        check_json_meta({"podcast": "Show", "title": "x" * 501})
