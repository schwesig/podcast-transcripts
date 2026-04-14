import json
import re
import secrets
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).parent
PODCASTS = BASE / "podcasts"
PODCASTS.mkdir(exist_ok=True)

UPLOAD_TOKEN_FILE = BASE / ".upload_token"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024


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
        if cl and cl.isdigit() and int(cl) > MAX_TOTAL_BYTES + 64 * 1024:
            return PlainTextResponse(
                f"Request body exceeds {MAX_TOTAL_BYTES // (1024 * 1024)} MB limit",
                status_code=413,
            )
    return await call_next(request)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
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


@app.post("/upload")
async def upload(
    json_file: UploadFile = File(...),
    txt_file: UploadFile = File(...),
    srt_file: UploadFile = File(...),
    upload_token: str = Form(""),
):
    expected = get_upload_token()
    if not expected:
        raise HTTPException(503, "Upload disabled: no server token configured")
    if not secrets.compare_digest(upload_token, expected):
        raise HTTPException(401, "Invalid upload token")

    json_bytes = await json_file.read()
    txt_bytes = await txt_file.read()
    srt_bytes = await srt_file.read()

    for label, b in (("JSON", json_bytes), ("TXT", txt_bytes), ("SRT", srt_bytes)):
        if len(b) > MAX_FILE_BYTES:
            raise HTTPException(
                413,
                f"{label} file exceeds {MAX_FILE_BYTES // (1024 * 1024)} MB limit",
            )
    if len(json_bytes) + len(txt_bytes) + len(srt_bytes) > MAX_TOTAL_BYTES:
        raise HTTPException(
            413,
            f"Total upload exceeds {MAX_TOTAL_BYTES // (1024 * 1024)} MB limit",
        )

    try:
        meta = json.loads(json_bytes.decode("utf-8"))
    except Exception as e:
        raise HTTPException(400, f"JSON parse error: {e}")
    show = meta.get("podcast")
    title = meta.get("title")
    if not show or not title:
        raise HTTPException(400, "JSON must contain 'podcast' and 'title'")

    date_str = parse_date(meta.get("date") or "")
    show_slug = slugify(show)
    title_slug = slugify(title)
    stem_date = date_str or datetime.now().strftime("%Y-%m-%d")
    stem = f"{stem_date}_{title_slug}"
    ep_dir = PODCASTS / show_slug / title_slug
    ep_dir.mkdir(parents=True, exist_ok=True)
    (ep_dir / f"{stem}.json").write_bytes(json_bytes)
    (ep_dir / f"{stem}.txt").write_bytes(txt_bytes)
    (ep_dir / f"{stem}.srt").write_bytes(srt_bytes)
    return RedirectResponse("/", status_code=303)


@app.get("/download/{rel:path}")
def download(rel: str):
    path = safe_subpath(rel)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.get("/preview/{rel:path}", response_class=PlainTextResponse)
def preview(rel: str):
    path = safe_subpath(rel)
    return path.read_text(encoding="utf-8", errors="ignore")


@app.get("/api/search")
def search(q: str = ""):
    q = q.strip().lower()
    shows = load_shows()
    all_eps: list[dict] = []
    for show in shows.values():
        all_eps.extend(show["episodes"])
    if not q:
        return {"episodes": all_eps}
    hits = []
    for ep in all_eps:
        if q in ep["title"].lower() or q in ep["show"].lower():
            hits.append({**ep, "match": "title"})
            continue
        if q in ep["summary"].lower():
            idx = ep["summary"].lower().find(q)
            start = max(0, idx - 60)
            end = min(len(ep["summary"]), idx + len(q) + 60)
            hits.append({**ep, "match": "summary", "snippet": f"…{ep['summary'][start:end]}…"})
            continue
        txt_fmt = ep["formats"].get("txt")
        if txt_fmt:
            content = (PODCASTS / txt_fmt["rel"]).read_text(
                encoding="utf-8", errors="ignore"
            )
            idx = content.lower().find(q)
            if idx >= 0:
                start = max(0, idx - 60)
                end = min(len(content), idx + len(q) + 60)
                snippet = content[start:end].replace("\n", " ")
                hits.append({**ep, "match": "content", "snippet": f"…{snippet}…"})
    return {"episodes": hits}
