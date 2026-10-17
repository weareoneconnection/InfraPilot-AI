from __future__ import annotations
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from .db import init_db, connect
from .models import EventCreate, ApprovalRequest, DispatchRequest, ReinspectionRequest, GoldenDemoRequest
from . import service

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app=FastAPI(title="InfraPilot AI",version="1.0.0",description="Transport infrastructure field multimodal autonomous sensing and closed-loop response", lifespan=lifespan)

STATIC=Path(__file__).parent/'static'
app.mount('/static',StaticFiles(directory=STATIC),name='static')

@app.get('/',include_in_schema=False)
def home(): return FileResponse(STATIC/'index.html')

@app.get('/health')
def health(): return {"status":"ok","product":"InfraPilot AI","version":"1.0.0","architecture":"sense-decide-act-verify"}

@app.get('/projects')
def projects():
    with connect() as c: return [dict(r) for r in c.execute("SELECT * FROM projects ORDER BY id")]

@app.post('/media',status_code=201)
async def media(file:UploadFile=File(...)):
    content=await file.read(25*1024*1024+1)
    if len(content)>25*1024*1024: raise HTTPException(413,'file too large')
    try:return service.store_media(content,file.content_type)
    except ValueError as e:raise HTTPException(415,str(e))

@app.get('/media/{sha}')
def media_get(sha:str):
    with connect() as c:r=c.execute("SELECT * FROM media WHERE sha256=?",(sha,)).fetchone()
    if not r:raise HTTPException(404,'media not found')
    return Response(bytes(r['content']),media_type=r['media_type'],headers={'ETag':sha,'X-Content-Type-Options':'nosniff','Cache-Control':'private, max-age=86400'})

@app.post('/events',status_code=201)
async def create(payload:EventCreate):
    try:return await service.create_event(payload.model_dump())
    except ValueError as e:raise HTTPException(422,str(e))

@app.get('/events/{event_id}')
def get_event(event_id:str):
    try:return service.get_event(event_id)
    except KeyError:raise HTTPException(404,'event not found')

@app.post('/events/{event_id}/analyze')
def analyze(event_id:str):
    try:return service.analyze(event_id)
    except KeyError:raise HTTPException(404,'event not found')

@app.post('/events/{event_id}/approve')
def approve(event_id:str,payload:ApprovalRequest):
    try:return service.approve(event_id,payload.actor)
    except KeyError:raise HTTPException(404,'event not found')
    except ValueError as e:raise HTTPException(409,str(e))

@app.post('/events/{event_id}/dispatch')
def dispatch(event_id:str,payload:DispatchRequest):
    try:return service.dispatch(event_id,payload.actor)
    except KeyError:raise HTTPException(404,'event not found')
    except ValueError as e:raise HTTPException(409,str(e))

@app.post('/events/{event_id}/reinspect')
def reinspect(event_id:str,payload:ReinspectionRequest):
    try:return service.reinspect(event_id,payload.observation,payload.resolved,payload.media_sha,payload.actor)
    except KeyError:raise HTTPException(404,'event not found')
    except ValueError as e:raise HTTPException(409,str(e))

@app.post('/events/{event_id}/close')
def close(event_id:str):
    try:return service.close(event_id)
    except KeyError:raise HTTPException(404,'event not found')
    except ValueError as e:raise HTTPException(409,str(e))

@app.get('/dashboard')
def dashboard(): return service.dashboard()

@app.post('/demo/golden')
async def golden(payload:GoldenDemoRequest):
    event=await service.create_event({"project_id":1,"description":payload.description,"event_type":"hse","reported_risk":"AUTO","asset_ref":payload.asset_ref})
    event=service.analyze(event['id'])
    event=service.approve(event['id'],'demo_project_manager')
    event=service.dispatch(event['id'],'demo_site_manager')
    event=service.reinspect(event['id'],'Edge protection installed and workface re-inspected before restart.',True,None,'demo_inspector')
    event=service.close(event['id'],'demo_project_manager')
    return {"story":"Sense -> Understand -> Decide -> Human Gate -> Act -> Verify -> Close","event":event}
