import json
import re
import secrets
import shutil
import time
import uuid
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

from rapidfuzz import process as fz_process
from rank_bm25 import BM25L

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

BASE = Path(__file__).parent
PODCASTS = BASE / "podcasts"
PODCASTS.mkdir(exist_ok=True)
PENDING = BASE / ".pending"
PENDING.mkdir(exist_ok=True)
STATIC = BASE / "static"
STATIC.mkdir(exist_ok=True)

UPLOAD_TOKEN_FILE = BASE / ".upload_token"
MAX_FILE_BYTES = 200 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
MAX_PLAN_NAMES = 5000
PENDING_TTL_SECONDS = 3600
UPLOAD_ID_RE = re.compile(r"^[a-f0-9]{32}$")
STEM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*$")
CTRL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
SRT_CUE_RE = re.compile(
    r"^\s*\d+\s*\r?\n\s*\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}",
    re.MULTILINE,
)
MAX_STRING_FIELD = 50_000
REQUIRED_META = ("podcast", "title")
OPTIONAL_STRING_META = (
    "episode_number",
    "date",
    "duration",
    "summary",
    "shownotes",
)


def check_text_blob(label: str, data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, f"{label}: not valid UTF-8")
    if CTRL_CHAR_RE.search(text):
        raise HTTPException(400, f"{label}: contains forbidden control characters")
    return text


def check_json_meta(meta) -> dict:
    if not isinstance(meta, dict):
        raise HTTPException(400, "JSON root must be an object")
    for k in REQUIRED_META:
        v = meta.get(k)
        if not isinstance(v, str) or not v.strip():
            raise HTTPException(400, f"JSON field '{k}' must be a non-empty string")
        if len(v) > 500:
            raise HTTPException(400, f"JSON field '{k}' too long (max 500 chars)")
    for k in OPTIONAL_STRING_META:
        v = meta.get(k)
        if v is None:
            continue
        if isinstance(v, int):
            continue
        if not isinstance(v, str):
            raise HTTPException(400, f"JSON field '{k}' must be a string")
        if len(v) > MAX_STRING_FIELD:
            raise HTTPException(400, f"JSON field '{k}' too long")
    return meta


def classify_filename(raw: str) -> tuple[str, str]:
    """Validate an episode filename and return (stem, ext).

    Single source of truth for the naming rule, used by both the
    multipart /upload path (via classify_upload) and the JSON
    /upload/plan preview endpoint.
    """
    name = (raw or "").strip()
    if not name:
        raise ValueError("empty filename")
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError("filename contains path separators")
    base, _, ext = name.rpartition(".")
    ext = ext.lower()
    if not base or ext not in ("json", "txt", "srt"):
        raise ValueError("unsupported extension, expected .json .txt or .srt")
    if not STEM_RE.match(base):
        raise ValueError(f"stem must match YYYY-MM-DD_slug (got '{base}')")
    return base, ext


def classify_upload(upload: UploadFile) -> tuple[str, str]:
    return classify_filename(upload.filename or "")


def validate_episode_trio(
    json_bytes: bytes,
    txt_bytes: bytes,
    srt_bytes: bytes,
) -> tuple[str, str]:
    for label, b in (("JSON", json_bytes), ("TXT", txt_bytes), ("SRT", srt_bytes)):
        if len(b) > MAX_FILE_BYTES:
            raise HTTPException(413, f"{label} file exceeds {_mb(MAX_FILE_BYTES)} limit")

    try:
        json_text = json_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "JSON file is not valid UTF-8")
    try:
        meta = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"JSON parse error: {e.msg} (line {e.lineno})")
    meta = check_json_meta(meta)

    check_text_blob("TXT", txt_bytes)
    srt_text = check_text_blob("SRT", srt_bytes)
    if not SRT_CUE_RE.search(srt_text):
        raise HTTPException(400, "SRT: does not look like SubRip (no valid cue found)")

    return meta["podcast"], meta["title"]


def episode_dir(show: str, title: str) -> Path:
    return PODCASTS / slugify(show) / slugify(title)


def episode_exists(show: str, title: str, stem: str) -> bool:
    ep_dir = episode_dir(show, title)
    if not ep_dir.exists():
        return False
    return any((ep_dir / f"{stem}.{ext}").exists() for ext in ("json", "txt", "srt"))


def save_episode(
    stem: str,
    show: str,
    title: str,
    json_bytes: bytes,
    txt_bytes: bytes,
    srt_bytes: bytes,
) -> None:
    ep_dir = episode_dir(show, title)
    ep_dir.mkdir(parents=True, exist_ok=True)
    (ep_dir / f"{stem}.json").write_bytes(json_bytes)
    (ep_dir / f"{stem}.txt").write_bytes(txt_bytes)
    (ep_dir / f"{stem}.srt").write_bytes(srt_bytes)


def stash_pending(
    uid: str,
    stem: str,
    show: str,
    title: str,
    json_bytes: bytes,
    txt_bytes: bytes,
    srt_bytes: bytes,
) -> None:
    pdir = PENDING / uid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{stem}.json").write_bytes(json_bytes)
    (pdir / f"{stem}.txt").write_bytes(txt_bytes)
    (pdir / f"{stem}.srt").write_bytes(srt_bytes)
    (pdir / f"{stem}.meta").write_text(
        json.dumps({"show": show, "title": title}), encoding="utf-8"
    )


def cleanup_pending() -> None:
    cutoff = time.time() - PENDING_TTL_SECONDS
    if not PENDING.exists():
        return
    for child in PENDING.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except FileNotFoundError:
            continue


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.2f} MB"


def get_upload_token() -> str | None:
    if not UPLOAD_TOKEN_FILE.exists():
        return None
    tok = UPLOAD_TOKEN_FILE.read_text(encoding="utf-8").strip()
    return tok or None


app = FastAPI(
    title="Podcast Transcripts",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    if request.url.path == "/upload" and request.method == "POST":
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_TOTAL_BYTES + 16 * 1024:
            return PlainTextResponse(
                f"Request body exceeds {_mb(MAX_TOTAL_BYTES)} limit",
                status_code=413,
            )
    return await call_next(request)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))

HTML_TAG = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    return unescape(HTML_TAG.sub(" ", s or "")).strip()


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "unknown"


def human_size(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024:
            return f"{f:.0f} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} TB"


def parse_date(s: str) -> str:
    if not s:
        return ""
    try:
        return parsedate_to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s).strftime("%Y-%m-%d")
    except Exception:
        return s[:10] if len(s) >= 10 else s


def safe_subpath(rel: str) -> Path:
    root = PODCASTS.resolve()
    path = (root / rel).resolve()
    if root != path and root not in path.parents:
        raise HTTPException(404)
    if not path.is_file():
        raise HTTPException(404)
    if path.suffix.lower().lstrip(".") not in ("txt", "srt", "json"):
        raise HTTPException(404)
    return path


def load_episode(ep_dir: Path) -> dict | None:
    files: dict[str, Path] = {}
    for p in ep_dir.iterdir():
        if p.is_file():
            ext = p.suffix.lower().lstrip(".")
            if ext in ("json", "txt", "srt"):
                files[ext] = p
    if not files:
        return None
    meta: dict = {}
    if "json" in files:
        try:
            meta = json.loads(files["json"].read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    base_file = files.get("txt") or files.get("srt") or files["json"]
    show = meta.get("podcast") or ep_dir.parent.name
    ep = {
        "show": show,
        "show_slug": slugify(show),
        "title": meta.get("title") or base_file.stem,
        "episode_number": str(meta.get("episode_number") or ""),
        "date": parse_date(meta.get("date") or ""),
        "duration": meta.get("duration") or "",
        "summary": strip_html(meta.get("summary") or meta.get("shownotes") or ""),
        "stem": base_file.stem,
        "rel_dir": str(ep_dir.relative_to(PODCASTS)),
        "formats": {},
        "mtime": max(p.stat().st_mtime for p in files.values()),
    }
    for ext, p in files.items():
        ep["formats"][ext] = {
            "filename": p.name,
            "rel": str(p.relative_to(PODCASTS)),
            "size": human_size(p.stat().st_size),
        }
    return ep


def load_shows() -> dict[str, dict]:
    shows: dict[str, dict] = {}
    if not PODCASTS.exists():
        return shows
    for show_dir in sorted(PODCASTS.iterdir()):
        if not show_dir.is_dir():
            continue
        for ep_dir in sorted(show_dir.iterdir()):
            if not ep_dir.is_dir():
                continue
            ep = load_episode(ep_dir)
            if not ep:
                continue
            show = shows.setdefault(
                ep["show"],
                {"name": ep["show"], "slug": slugify(ep["show"]), "episodes": []},
            )
            show["episodes"].append(ep)
    for show in shows.values():
        show["episodes"].sort(key=lambda e: (e["date"], e["mtime"]), reverse=True)
    return dict(sorted(shows.items(), key=lambda kv: kv[0].lower()))


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    shows = load_shows()
    total = sum(len(s["episodes"]) for s in shows.values())
    return templates.TemplateResponse(
        request,
        "index.html",
        {"shows": shows, "total": total},
    )


@app.post("/upload", response_class=HTMLResponse)
async def upload(
    request: Request,
    files: list[UploadFile] = File(...),
    upload_token: str = Form(""),
):
    expected = get_upload_token()
    if not expected:
        raise HTTPException(503, "Upload disabled: no server token configured")
    if not secrets.compare_digest(upload_token, expected):
        raise HTTPException(401, "Invalid upload token")
    if not files:
        raise HTTPException(400, "No files provided")

    cleanup_pending()

    groups: dict[str, dict[str, UploadFile]] = {}
    errors: list[dict] = []

    for f in files:
        raw_name = (f.filename or "").strip() or "<empty>"
        try:
            base, ext = classify_upload(f)
        except ValueError as e:
            errors.append({"file": raw_name, "error": str(e)})
            continue
        grp = groups.setdefault(base, {})
        if ext in grp:
            errors.append({"file": raw_name, "error": f"duplicate .{ext} for stem {base}"})
            continue
        grp[ext] = f

    successes: list[dict] = []
    pending: list[dict] = []
    upload_id = uuid.uuid4().hex

    for stem, trio in groups.items():
        missing = {"json", "txt", "srt"} - set(trio.keys())
        if missing:
            errors.append(
                {"file": stem, "error": f"incomplete trio, missing: {', '.join(sorted(missing))}"}
            )
            continue
        try:
            json_bytes = await trio["json"].read()
            txt_bytes = await trio["txt"].read()
            srt_bytes = await trio["srt"].read()
            show, title = validate_episode_trio(json_bytes, txt_bytes, srt_bytes)
            if episode_exists(show, title, stem):
                stash_pending(upload_id, stem, show, title, json_bytes, txt_bytes, srt_bytes)
                pending.append({"stem": stem, "show": show, "title": title})
            else:
                save_episode(stem, show, title, json_bytes, txt_bytes, srt_bytes)
                successes.append({"stem": stem, "show": show, "title": title})
        except HTTPException as e:
            errors.append({"file": stem, "error": str(e.detail)})
        except Exception as e:
            errors.append({"file": stem, "error": f"{type(e).__name__}: {e}"})

    if not pending:
        upload_id = ""

    return templates.TemplateResponse(
        request,
        "upload_result.html",
        {
            "successes": successes,
            "errors": errors,
            "pending": pending,
            "ignored": [],
            "upload_id": upload_id,
        },
    )


@app.post("/upload/resolve", response_class=HTMLResponse)
async def upload_resolve(request: Request):
    form = await request.form()
    expected = get_upload_token()
    if not expected:
        raise HTTPException(503, "Upload disabled: no server token configured")
    token = str(form.get("upload_token", ""))
    if not secrets.compare_digest(token, expected):
        raise HTTPException(401, "Invalid upload token")
    upload_id = str(form.get("upload_id", ""))
    if not UPLOAD_ID_RE.match(upload_id):
        raise HTTPException(400, "Invalid upload_id")

    cleanup_pending()

    pdir = PENDING / upload_id
    if not pdir.is_dir():
        raise HTTPException(404, "Pending upload not found or expired")
    try:
        pdir_mtime = pdir.stat().st_mtime
    except FileNotFoundError:
        raise HTTPException(404, "Pending upload not found or expired")
    if time.time() - pdir_mtime > PENDING_TTL_SECONDS:
        shutil.rmtree(pdir, ignore_errors=True)
        raise HTTPException(410, "Pending upload expired")

    successes: list[dict] = []
    ignored: list[dict] = []
    errors: list[dict] = []

    for meta_file in sorted(pdir.glob("*.meta")):
        stem = meta_file.stem
        try:
            info = json.loads(meta_file.read_text(encoding="utf-8"))
            show = info["show"]
            title = info["title"]
        except Exception as e:
            errors.append({"file": stem, "error": f"pending meta unreadable: {e}"})
            continue
        decision = str(form.get(f"decision_{stem}", "ignore"))
        if decision == "replace":
            try:
                json_bytes = (pdir / f"{stem}.json").read_bytes()
                txt_bytes = (pdir / f"{stem}.txt").read_bytes()
                srt_bytes = (pdir / f"{stem}.srt").read_bytes()
                save_episode(stem, show, title, json_bytes, txt_bytes, srt_bytes)
                successes.append({"stem": stem, "show": show, "title": title})
            except Exception as e:
                errors.append({"file": stem, "error": f"{type(e).__name__}: {e}"})
        else:
            ignored.append({"stem": stem, "show": show, "title": title})

    shutil.rmtree(pdir, ignore_errors=True)

    return templates.TemplateResponse(
        request,
        "upload_result.html",
        {
            "successes": successes,
            "errors": errors,
            "pending": [],
            "ignored": ignored,
            "upload_id": "",
        },
    )


class PlanPayload(BaseModel):
    upload_token: str = ""
    names: list[str] = []


@app.post("/upload/plan")
def upload_plan(payload: PlanPayload):
    """Dry-run preview for the folder-upload flow.

    Given the flat list of basenames from the browser's folder picker,
    group them into complete episode trios, incomplete trios, and
    rejections. No bytes are read, nothing is written — this is a
    pure classification pass over the filenames so the client can
    render a confirmation list before POSTing the real files to
    /upload.
    """
    expected = get_upload_token()
    if not expected:
        raise HTTPException(503, "Upload disabled: no server token configured")
    if not secrets.compare_digest(payload.upload_token, expected):
        raise HTTPException(401, "Invalid upload token")
    if len(payload.names) > MAX_PLAN_NAMES:
        raise HTTPException(413, f"Too many names (max {MAX_PLAN_NAMES})")

    groups: dict[str, dict[str, str]] = {}
    rejected: list[dict] = []

    for name in payload.names:
        try:
            base, ext = classify_filename(name)
        except ValueError as e:
            rejected.append({"name": name, "reason": str(e)})
            continue
        grp = groups.setdefault(base, {})
        if ext in grp:
            rejected.append(
                {"name": name, "reason": f"duplicate .{ext} for stem {base}"}
            )
            continue
        grp[ext] = name

    episodes: list[dict] = []
    incomplete: list[dict] = []
    for stem in sorted(groups):
        trio = groups[stem]
        have = set(trio.keys())
        if {"json", "txt", "srt"} <= have:
            episodes.append(
                {"stem": stem, "files": [trio[k] for k in ("json", "txt", "srt")]}
            )
        else:
            missing = sorted({"json", "txt", "srt"} - have)
            incomplete.append(
                {
                    "stem": stem,
                    "files": [trio[k] for k in sorted(have)],
                    "missing": missing,
                }
            )

    return {"episodes": episodes, "incomplete": incomplete, "rejected": rejected}


@app.get("/download/{rel:path}")
def download(rel: str):
    path = safe_subpath(rel)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.get("/preview/{rel:path}", response_class=PlainTextResponse)
def preview(rel: str):
    path = safe_subpath(rel)
    return path.read_text(encoding="utf-8", errors="ignore")


def _ep_txt(ep: dict) -> str:
    txt_fmt = ep["formats"].get("txt")
    if txt_fmt:
        return (PODCASTS / txt_fmt["rel"]).read_text(encoding="utf-8", errors="ignore")
    return ""


# Each cue: (timestamp_str "HH:MM:SS", cue_text)
_SRT_CUE_BLOCK = re.compile(
    r"\d+\s*\n(\d{2}:\d{2}:\d{2})[,\.]\d{3}\s*-->[^\n]+\n([\s\S]*?)(?=\n\s*\n|\Z)",
    re.MULTILINE,
)


def _parse_srt_cues(ep: dict) -> list[tuple[str, str]]:
    """Return list of (timestamp, text) for every cue in the SRT file."""
    srt_fmt = ep["formats"].get("srt")
    if not srt_fmt:
        return []
    raw = (PODCASTS / srt_fmt["rel"]).read_text(encoding="utf-8", errors="ignore")
    return [(m.group(1), m.group(2).replace("\n", " ").strip()) for m in _SRT_CUE_BLOCK.finditer(raw)]


def _ep_tokens(ep: dict, txt: str, cues: list[tuple[str, str]]) -> list[str]:
    """Build the token bag for one episode (title + show + summary + txt + srt)."""
    srt_text = " ".join(text for _, text in cues)
    return " ".join([ep["title"], ep["show"], ep["summary"], txt, srt_text]).lower().split()


def _make_snippet(text: str, q: str, context: int = 60) -> str:
    idx = text.lower().find(q)
    if idx < 0:
        return ""
    start = max(0, idx - context)
    end = min(len(text), idx + len(q) + context)
    return f"…{text[start:end].replace(chr(10), ' ')}…"


def _find_timestamp(cues: list[tuple[str, str]], q: str) -> str:
    """Return timestamp of the first SRT cue containing q, or empty string."""
    for ts, text in cues:
        if q in text.lower():
            return ts
    return ""


def _fuzzy_expand(query_tokens: list[str], vocab: set[str], cutoff: int = 80) -> tuple[list[str], list[str]]:
    """Expand query tokens with prefix matches and/or close fuzzy vocab matches.

    Strategy per token:
    1. Exact match → keep as-is.
    2. Prefix match (vocab token starts with query token, min 2 chars) → use
       all prefix matches; best (shortest) becomes the match_term.
    3. Fuzzy match (rapidfuzz score ≥ cutoff) → use top-3; best becomes match_term.
    4. No match → pass through unchanged.

    Returns (all_tokens, match_terms) where match_terms are the best
    representative tokens per original query token — used for snippet
    highlighting.
    """
    all_tokens: list[str] = []
    match_terms: list[str] = []
    for tok in query_tokens:
        if tok in vocab:
            all_tokens.append(tok)
            match_terms.append(tok)
            continue
        # Prefix expansion (only meaningful for tokens >= 2 chars)
        if len(tok) >= 2:
            prefix_hits = sorted(v for v in vocab if v.startswith(tok))
            if prefix_hits:
                all_tokens.extend(prefix_hits)
                match_terms.append(prefix_hits[0])  # shortest = most specific
                continue
        # Fuzzy expansion (only against tokens >= 4 chars to avoid short noise)
        long_vocab = {v for v in vocab if len(v) >= 4}
        hits = fz_process.extract(tok, long_vocab, score_cutoff=cutoff, limit=3)
        if hits:
            best = hits[0][0]
            all_tokens.extend(h[0] for h in hits)
            match_terms.append(best)
        else:
            all_tokens.append(tok)
            match_terms.append(tok)
    return all_tokens, match_terms


@app.get("/api/search")
def search(q: str = ""):
    q = q.strip().lower()
    shows = load_shows()
    all_eps: list[dict] = []
    for show in shows.values():
        all_eps.extend(show["episodes"])
    if not q:
        return {"episodes": all_eps}

    txts = [_ep_txt(ep) for ep in all_eps]
    cues_list = [_parse_srt_cues(ep) for ep in all_eps]
    corpus = [_ep_tokens(ep, txt, cues) for ep, txt, cues in zip(all_eps, txts, cues_list)]
    bm25 = BM25L(corpus)

    vocab: set[str] = {tok for doc in corpus for tok in doc}
    query_tokens, match_terms = _fuzzy_expand(q.split(), vocab)
    scores = bm25.get_scores(query_tokens)

    ranked = []
    for score, ep, txt, cues in zip(scores, all_eps, txts, cues_list):
        if score <= 0:
            continue
        snippet = ""
        timestamp = ""
        match_term = match_terms[0] if match_terms else q
        # Try all expanded tokens for snippet/timestamp — match_terms only
        # covers the "best" representative per query token, but the actual
        # text may contain a different expansion (e.g. "meditation" vs "meditating").
        for term in query_tokens:
            if not snippet:
                s = (
                    _make_snippet(ep["title"] + " " + ep["show"], term)
                    or _make_snippet(ep["summary"], term)
                    or _make_snippet(txt, term)
                )
                if s:
                    snippet = s
                    # Use the match_term that corresponds to this expansion
                    # if we can find it, otherwise fall back to the term itself.
                    match_term = term if term in match_terms else (match_terms[0] if match_terms else term)
            if not timestamp:
                timestamp = _find_timestamp(cues, term)
            if snippet and timestamp:
                break
        ranked.append((score, {**ep, "snippet": snippet, "timestamp": timestamp, "match_term": match_term}))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return {"episodes": [ep for _, ep in ranked]}
