# Podcast Transcripts

A lightweight FastAPI + DaisyUI site to browse, search, preview, and download
podcast transcripts. Episodes live on disk as a `JSON` (metadata) + `TXT`
(transcript) + `SRT` (subtitles) triple, grouped by show.

## Features

- Per-show tabs plus an **All** view
- Episode cards with title, number, date, duration, and summary
- Download and inline preview for all three formats
- Full-text search across titles, show names, JSON summaries, and transcripts
- Batch upload of many episodes at once, with:
  - token-protected endpoint
  - filename convention check (`YYYY-MM-DD_slug.{json,txt,srt}`)
  - per-file and per-batch size caps
  - UTF-8, JSON schema, and SRT format validation
  - replace-or-ignore prompt when an episode already exists

## Stack

- Python 3.11+, FastAPI, Uvicorn, Jinja2
- Tailwind CSS + DaisyUI via CDN (no build step)
- No database — the filesystem is the source of truth

## Layout

```
podcast-site/
├── main.py                  # FastAPI app, validation, upload flow
├── templates/
│   ├── index.html           # Browse + search UI, upload modal
│   └── upload_result.html   # Upload outcome + conflict resolver
├── podcasts/                # Episode tree (gitignored)
│   └── <show-slug>/
│       └── <episode-slug>/
│           ├── YYYY-MM-DD_<slug>.json
│           ├── YYYY-MM-DD_<slug>.txt
│           └── YYYY-MM-DD_<slug>.srt
├── .upload_token            # Server secret (gitignored)
└── .pending/                # Temporary conflict staging (gitignored)
```

Episode content is intentionally **not** tracked in git. Only the site
machinery is.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install fastapi uvicorn jinja2 python-multipart
```

## Run

```bash
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080
```

Then open `http://localhost:8080/`.

## Upload Token

Uploads require a shared secret stored in `.upload_token` at the project
root. Without it, every `POST /upload` returns `503`.

### Generate a token

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > .upload_token
chmod 600 .upload_token
```

The token is read fresh on every upload request, so you can rotate it
without restarting the server. The file is listed in `.gitignore` and
must never be committed.

### Rotate a token

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > .upload_token
```

### Read the current token

```bash
cat .upload_token
```

Paste the value into the password field of the upload modal. For scripted
uploads, send it as the `upload_token` form field.

## JSON metadata schema

The JSON file must be an object with at least these fields:

```json
{
  "podcast": "Show Name",
  "title": "Episode Title",
  "episode_number": "84",
  "date": "Wed, 23 Aug 2023 20:02:00 -0000",
  "duration": "00:48:49",
  "summary": "<p>HTML-capable summary…</p>",
  "shownotes": "Plain text show notes"
}
```

`podcast` and `title` are required and capped at 500 characters. Optional
string fields are capped at 50k characters. The `date` field accepts
RFC 2822 or ISO-8601.

## Filename convention

All three files in an episode must share the same stem:

```
2023-08-23_reverse-meditation-with-andrew-holecek.json
2023-08-23_reverse-meditation-with-andrew-holecek.txt
2023-08-23_reverse-meditation-with-andrew-holecek.srt
```

Regex: `^\d{4}-\d{2}-\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*$`

## Upload flow

1. Click **+ Upload** in the navbar.
2. Select all files for one or many episodes (JSON + TXT + SRT per episode).
3. Paste the upload token.
4. Submit. The server:
   - groups files by stem,
   - validates filenames, sizes, UTF-8, JSON schema, SRT format,
   - saves clean episodes that do not collide with existing ones,
   - stashes episodes whose stem already exists in a pending area.
5. The result page shows four buckets: **Gespeichert**, **Ignoriert**,
   **Konflikte**, **Fehler**. For conflicts, pick **Ignorieren** or
   **Ersetzen** per episode (or bulk) and re-confirm the token to finalize.

## Limits

| Setting             | Default    |
| ------------------- | ---------- |
| Per-file size       | 0.2 MB     |
| Per-batch total     | 10 MB      |
| Pending TTL         | 1 hour     |
| JSON string field   | 50k chars  |
| JSON title/podcast  | 500 chars  |

Tweak these in `main.py` (`MAX_FILE_BYTES`, `MAX_TOTAL_BYTES`,
`PENDING_TTL_SECONDS`, `MAX_STRING_FIELD`).

## Security

- Upload token compared in constant time (`secrets.compare_digest`)
- Request `Content-Length` gate blocks oversized bodies before parsing
- FastAPI auto-docs (`/docs`, `/redoc`, `/openapi.json`) disabled
- Path traversal blocked on download, preview, and upload filenames
- Control characters and non-UTF-8 rejected in TXT and SRT
- Template output auto-escaped by Jinja, so JSON fields cannot XSS
- Downloads served as `application/octet-stream` (forced download)

When exposing the site publicly (for example via `sprite url update --auth
public` on sprites.dev), make sure `.upload_token` is set and not the
sample token.

## License

Code: add your preferred license here. Episode content is not part of
this repository.
