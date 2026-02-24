"""
FileSorter – FastAPI entry point.
Start: uvicorn main:app --reload --port 8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from api import scan, move, rename, index, triage, ai_gateway, history, deep_sort
from utils.db import init_db, cleanup_old_scans


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialise DB schema and remove scan records older than 30 days."""
    await init_db()
    await cleanup_old_scans(days=30)
    yield


app = FastAPI(title="FileSorter", version="0.1.0", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Security Headers Middleware (BUG-5)                                          #
# --------------------------------------------------------------------------- #

@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Add security headers to every response."""
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # 'unsafe-inline' is required for Alpine.js inline directives (x-data, x-on…)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
        "img-src 'self' data:; "
        "font-src 'self';"
    )
    return response


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
