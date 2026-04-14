from pathlib import Path
from datetime import datetime
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).parent
TRANSCRIPTS = BASE / "transcripts"
TRANSCRIPTS.mkdir(exist_ok=True)

app = FastAPI(title="Podcast Transcripts")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_episodes() -> list[dict]:
    episodes: dict[str, dict] = {}
    for path in sorted(TRANSCRIPTS.iterdir()):
        if not path.is_file() or path.suffix.lower() not in (".txt", ".srt"):
            continue
        stem = path.stem
        ep = episodes.setdefault(
            stem,
            {
                "title": stem.replace("_", " ").replace("-", " ").title(),
                "slug": slugify(stem),
                "stem": stem,
                "formats": {},
                "mtime": 0,
            },
        )
        st = path.stat()
        ep["formats"][path.suffix.lower().lstrip(".")] = {
            "filename": path.name,
            "size": human_size(st.st_size),
        }
        ep["mtime"] = max(ep["mtime"], st.st_mtime)

    out = list(episodes.values())
    for ep in out:
        ep["date"] = datetime.fromtimestamp(ep["mtime"]).strftime("%Y-%m-%d")
    out.sort(key=lambda e: e["mtime"], reverse=True)
    return out


def safe_file(filename: str) -> Path:
    path = (TRANSCRIPTS / filename).resolve()
    if TRANSCRIPTS.resolve() not in path.parents:
        raise HTTPException(404)
    if not path.is_file() or path.suffix.lower() not in (".txt", ".srt"):
        raise HTTPException(404)
    return path


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"episodes": load_episodes()}
    )


@app.get("/api/search")
def search(q: str = ""):
    q = q.strip().lower()
    episodes = load_episodes()
    if not q:
        return {"episodes": episodes}
    hits = []
    for ep in episodes:
        if q in ep["title"].lower() or q in ep["stem"].lower():
            hits.append({**ep, "match": "title"})
            continue
        txt = ep["formats"].get("txt")
        if txt:
            content = (TRANSCRIPTS / txt["filename"]).read_text(
                encoding="utf-8", errors="ignore"
            )
            idx = content.lower().find(q)
            if idx >= 0:
                start = max(0, idx - 60)
                end = min(len(content), idx + len(q) + 60)
                snippet = content[start:end].replace("\n", " ")
                hits.append({**ep, "match": "content", "snippet": f"…{snippet}…"})
    return {"episodes": hits}


@app.get("/download/{filename}")
def download(filename: str):
    path = safe_file(filename)
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


@app.get("/preview/{filename}", response_class=PlainTextResponse)
def preview(filename: str):
    path = safe_file(filename)
    return path.read_text(encoding="utf-8", errors="ignore")
