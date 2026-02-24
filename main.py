"""
FileSorter – FastAPI entry point.
Start: uvicorn main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api import scan, move, rename, index, triage, ai_gateway, history, deep_sort
from utils.db import init_db

app = FastAPI(title="FileSorter", version="0.1.0")

app.mount("/static", StaticFiles(directory="static"), name="static")

# Register all routers
app.include_router(scan.router, prefix="/scan", tags=["scan"])
app.include_router(move.router, prefix="/move", tags=["move"])
app.include_router(rename.router, prefix="/rename", tags=["rename"])
app.include_router(index.router, prefix="/index", tags=["index"])
app.include_router(triage.router, prefix="/triage", tags=["triage"])
app.include_router(ai_gateway.router, prefix="/ai", tags=["ai"])
app.include_router(history.router, prefix="/history", tags=["history"])
app.include_router(deep_sort.router, prefix="/deep-sort", tags=["deep-sort"])


@app.on_event("startup")
async def startup():
    await init_db()
