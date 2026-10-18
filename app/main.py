"""InfraPilot AI API and field console."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from .llm import from_env
from .service import FieldPilot, GateError, StateError
from .store import Store
from .synthetic import photo

BASE = Path(__file__).resolve().parent
pilot: FieldPilot | None = None


def p() -> FieldPilot:
    assert pilot is not None
    return pilot


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pilot
    pilot = FieldPilot(Store(), model=from_env())
    yield


app = FastAPI(title="InfraPilot AI", version=__version__, lifespan=lifespan,
              description="Transport infrastructure field perception and closed-loop rectification")


class ReportIn(BaseModel):
    description: str = Field(min_length=4, max_length=8000)
    reporter: str = Field(default="现场人员", max_length=120)
    reported_risk: str = Field(default="AUTO", pattern="^(AUTO|LOW|MEDIUM|HIGH|CRITICAL)$")
    asset_id: str | None = None
    qr: str | None = None
    lat: float | None = None
    lon: float | None = None
    photos: list[str] = Field(default_factory=list)


class Actor(BaseModel):
    actor: str = Field(min_length=1, max_length=120)


class TaskDone(Actor):
    note: str = Field(default="", max_length=2000)


class ReinspectIn(BaseModel):
    inspector: str = Field(min_length=1, max_length=120)
    observation: str = Field(min_length=2, max_length=4000)
    resolved: bool
    photos: list[str] = Field(default_factory=list)
    attest_location: bool = False


def call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, f"not found: {str(exc).strip(chr(39))}")
    except GateError as exc:
        raise HTTPException(403, str(exc))
    except StateError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.get("/health")
def health():
    return {"status": "ok", "product": "InfraPilot AI", "version": __version__,
            "model": p().model.describe() if p().model else "not configured",
            "assets": len(p().assets)}


@app.get("/assets")
def assets():
    return list(p().assets.values())


@app.get("/workspace")
def workspace():
    return p().workspace()


@app.post("/media", status_code=201)
async def upload(file: UploadFile = File(...)):
    content = await file.read(25 * 1024 * 1024 + 1)
    try:
        return p().store_media(content)
    except ValueError as exc:
        raise HTTPException(415 if "signature" in str(exc) else 413, str(exc))


@app.get("/media/{sha}")
def media(sha: str):
    row = call(p().media, sha, True)
    return Response(bytes(row["content"]), media_type=row["media_type"],
                    headers={"ETag": sha, "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"})


@app.post("/events", status_code=201)
def report(payload: ReportIn):
    return call(p().report, **payload.model_dump())


@app.get("/events")
def board():
    return p().board()


@app.get("/events/{event_id}")
def event(event_id: str):
    return call(p().event, event_id)


@app.get("/events/{event_id}/evidence")
def evidence(event_id: str):
    return call(p().evidence_bundle, event_id)


@app.post("/events/{event_id}/analyse")
def analyse(event_id: str):
    return call(p().analyse, event_id)


@app.post("/events/{event_id}/approve")
def approve(event_id: str, body: Actor):
    return call(p().approve, event_id, body.actor)


@app.post("/events/{event_id}/dispatch")
def dispatch(event_id: str, body: Actor):
    return call(p().dispatch, event_id, body.actor)


@app.post("/tasks/{task_id}/done")
def task_done(task_id: str, body: TaskDone):
    return call(p().complete_task, task_id, body.actor, body.note)


@app.post("/events/{event_id}/reinspect")
def reinspect(event_id: str, body: ReinspectIn):
    return call(p().reinspect, event_id, **body.model_dump())


@app.post("/events/{event_id}/close")
def close(event_id: str, body: Actor):
    return call(p().close, event_id, body.actor)


@app.get("/dashboard")
def dashboard():
    return p().dashboard()


@app.post("/demo/photo", status_code=201)
def demo_photo(scene: str = "before", asset_id: str = "P47", minutes_from_now: int = 0, at_asset: bool = True, variant: int = 0):
    """Generate a synthetic site photo with EXIF time and GPS (demo only; not a real photo)."""
    asset = p().assets.get(asset_id) or next(iter(p().assets.values()))
    lat, lon = (asset["lat"] + 0.0002, asset["lon"] + 0.0002) if at_asset else (asset["lat"] + 0.05, asset["lon"] + 0.05)
    taken = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
    return p().store_media(photo(scene, captured_at=taken.replace(tzinfo=None), lat=lat, lon=lon, variant=variant))


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(BASE / "static" / "index.html")
