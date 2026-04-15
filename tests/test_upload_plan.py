"""Red-green tests for the /upload/plan endpoint used by the folder
upload preview.

The endpoint receives a list of candidate filenames (the flat basenames
the browser exposes from <input webkitdirectory>) plus the upload
token. It reuses the server-side filename validation and returns three
buckets: complete trios ready to upload, incomplete trios, and files
that did not match the naming convention at all. The client renders
that preview and only submits the 'episodes' list via /upload after
the user confirms.
"""

import pytest

TOKEN = "secret-token-123"


@pytest.fixture
def client_with_token(client, tmp_tree):
    _, _, token_file = tmp_tree
    token_file.write_text(TOKEN, encoding="utf-8")
    return client


def test_upload_plan_requires_server_token(client):
    r = client.post("/upload/plan", json={"upload_token": "", "names": []})
    assert r.status_code == 503


def test_upload_plan_rejects_wrong_client_token(client_with_token):
    r = client_with_token.post(
        "/upload/plan", json={"upload_token": "nope", "names": []}
    )
    assert r.status_code == 401


def test_upload_plan_groups_complete_trio(client_with_token):
    r = client_with_token.post(
        "/upload/plan",
        json={
            "upload_token": TOKEN,
            "names": [
                "2023-08-23_foo.json",
                "2023-08-23_foo.txt",
                "2023-08-23_foo.srt",
            ],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["episodes"]) == 1
    ep = data["episodes"][0]
    assert ep["stem"] == "2023-08-23_foo"
    assert sorted(ep["files"]) == [
        "2023-08-23_foo.json",
        "2023-08-23_foo.srt",
        "2023-08-23_foo.txt",
    ]
    assert data["incomplete"] == []
    assert data["rejected"] == []


def test_upload_plan_flags_incomplete_trio(client_with_token):
    r = client_with_token.post(
        "/upload/plan",
        json={
            "upload_token": TOKEN,
            "names": ["2023-08-23_foo.json", "2023-08-23_foo.txt"],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["episodes"] == []
    assert len(data["incomplete"]) == 1
    inc = data["incomplete"][0]
    assert inc["stem"] == "2023-08-23_foo"
    assert inc["missing"] == ["srt"]


def test_upload_plan_rejects_invalid_filenames(client_with_token):
    r = client_with_token.post(
        "/upload/plan",
        json={
            "upload_token": TOKEN,
            "names": [
                "README.md",
                "../evil.json",
                "2023-08-23_Reverse.json",
            ],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["episodes"] == []
    assert data["incomplete"] == []
    assert len(data["rejected"]) == 3
    names = [item["name"] for item in data["rejected"]]
    assert set(names) == {
        "README.md",
        "../evil.json",
        "2023-08-23_Reverse.json",
    }
    for item in data["rejected"]:
        assert item["reason"]  # non-empty reason string


def test_upload_plan_flags_duplicate_extension(client_with_token):
    r = client_with_token.post(
        "/upload/plan",
        json={
            "upload_token": TOKEN,
            "names": [
                "2023-08-23_foo.json",
                "2023-08-23_foo.json",
                "2023-08-23_foo.txt",
                "2023-08-23_foo.srt",
            ],
        },
    )
    assert r.status_code == 200
    data = r.json()
    # The first occurrence forms the trio, the second shows up as rejected
    assert len(data["episodes"]) == 1
    assert data["episodes"][0]["stem"] == "2023-08-23_foo"
    assert len(data["rejected"]) == 1
    assert data["rejected"][0]["name"] == "2023-08-23_foo.json"
    assert "duplicate" in data["rejected"][0]["reason"].lower()


def test_upload_plan_mixed_bag(client_with_token):
    r = client_with_token.post(
        "/upload/plan",
        json={
            "upload_token": TOKEN,
            "names": [
                # complete trio A
                "2023-08-23_foo.json",
                "2023-08-23_foo.txt",
                "2023-08-23_foo.srt",
                # trio B missing srt
                "2023-08-24_bar.json",
                "2023-08-24_bar.txt",
                # garbage
                "README.md",
                # webkitdirectory-style nested path (defensive)
                "nested/2023-08-25_baz.json",
            ],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert [e["stem"] for e in data["episodes"]] == ["2023-08-23_foo"]
    assert [e["stem"] for e in data["incomplete"]] == ["2023-08-24_bar"]
    rejected_names = {item["name"] for item in data["rejected"]}
    assert "README.md" in rejected_names
    assert "nested/2023-08-25_baz.json" in rejected_names


def test_upload_plan_caps_payload_size(client_with_token):
    # Absurdly large name list should be rejected rather than processed.
    too_many = [f"2023-08-23_ep{i}.json" for i in range(5001)]
    r = client_with_token.post(
        "/upload/plan",
        json={"upload_token": TOKEN, "names": too_many},
    )
    assert r.status_code == 413
