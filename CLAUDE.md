# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python3 -m venv .venv
.venv/bin/pip install fastapi uvicorn jinja2 python-multipart pytest httpx rank-bm25

# Run all tests
.venv/bin/pytest -q

# Run a single test file
.venv/bin/pytest tests/test_upload_plan.py -q

# Run a single test by name
.venv/bin/pytest -q -k "test_upload_plan_groups_complete_trio"

# Run the server locally
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080
```

## Architecture

Single-file FastAPI app (`main.py`). No database — the filesystem is the source of truth.

### Episode storage layout

```
podcasts/
  <show-slug>/
    <episode-slug>/
      YYYY-MM-DD_<slug>.json   # metadata
      YYYY-MM-DD_<slug>.txt    # transcript
      YYYY-MM-DD_<slug>.srt    # subtitles
```

`load_shows()` walks this tree at request time (no cache). `slugify()` converts show/title strings to directory names.

### Upload flow (two-phase)

1. **`POST /upload/plan`** — dry-run, filename-only. Client sends flat list of basenames; server returns three buckets (`episodes`, `incomplete`, `rejected`) using the same `classify_filename()` validation as the real upload. No bytes read, nothing written.
2. **`POST /upload`** — real multipart upload. Groups files by stem, validates each trio (size, UTF-8, JSON schema, SRT format), saves clean episodes. Episodes that collide with an existing stem are stashed in `.pending/<upload_id>/` with a `.meta` sidecar.
3. **`POST /upload/resolve`** — resolves conflicts: reads the `.meta` sidecar, applies per-episode `replace`/`ignore` decisions, cleans up `.pending/`.

### Key validation functions

- `classify_filename(raw)` — single source of truth for the `YYYY-MM-DD_slug.{json,txt,srt}` naming rule. Used by both `/upload` and `/upload/plan`.
- `validate_episode_trio(json_bytes, txt_bytes, srt_bytes)` — validates sizes, UTF-8, JSON schema (`check_json_meta`), and SRT cue presence.
- `safe_subpath(rel)` — path-traversal guard for download/preview endpoints.

### Auth

Upload token read fresh from `.upload_token` on every request. Compared with `secrets.compare_digest`. No token file → 503. Wrong token → 401.

## Test isolation

`conftest.py` provides two fixtures:
- `tmp_tree` — monkeypatches `main.PODCASTS`, `main.PENDING`, `main.UPLOAD_TOKEN_FILE` into `tmp_path`. Tests never touch real episode data.
- `client` — `TestClient(main.app)` built on top of `tmp_tree`.

Tests use `TestClient` (synchronous) not `httpx.AsyncClient`.

## Red-Green TDD is mandatory for code changes

For every commit that touches production code (`main.py`, anything under
`templates/` that has logic, future modules, etc.), follow strict
Red-Green-Refactor:

1. **Red** — write a failing test first.
   - Run the test and show the failing output in the conversation
     before writing any implementation.
   - The failure must be for the right reason (assertion mismatch,
     not `ImportError` or `SyntaxError` on unrelated code).
2. **Green** — write the minimum implementation to make the test pass.
   - Run the test again and show it passing.
   - Do not add unrelated changes in the same step.
3. **Refactor** — only after green. Keep the tests green throughout.

Commit order:
- Prefer a single commit that contains both the new test and the
  implementation, so the tree is always green on `main`.
- If a change is large, a `test:` commit immediately followed by a
  `feat:`/`fix:` commit is also acceptable, but never push an
  implementation commit without its test.

### What does *not* require TDD

- Docs-only changes (`README.md`, `CLAUDE.md`, comments).
- Pure dependency bumps with no code edits.
- Template/CSS tweaks that are visual-only and have no branching logic.
- Build/config files (`.gitignore`, service definitions).

When in doubt, write the test.

## Branch discipline

All development on this project happens on the feature branch assigned
for the session. Never push to `main` directly.
