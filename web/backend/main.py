"""
FastAPI application entry point — Search Metric Analyzer backend, Phase 1.

Routes:
  GET  /api/health    — liveness check (used by frontend to confirm backend is up)
  POST /api/diagnose  — return a mock investigation fixture for the requested metric

CORS is configured to allow requests from the Vite dev server (localhost:5173).
In production, replace the origin list with the actual frontend domain.

To run locally:
  uvicorn web.backend.main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from web.backend.routes.diagnose import router as diagnose_router

app = FastAPI(
    title="Search Metric Analyzer API",
    description="Phase 1 demo backend — serves mock investigation fixtures",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# CORS — allow the Vite dev server to call this API without browser blocks.
# "allow_credentials=True" is not needed for this API (no cookies/auth),
# but the origin list must be explicit when using allow_credentials in future.
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vite dev server default
        "http://localhost:3000",   # Create React App default (in case it's used)
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Register routers — all routes are prefixed with /api
# ---------------------------------------------------------------------------
app.include_router(diagnose_router, prefix="/api")


@app.get("/api/health")
async def health() -> dict:
    """
    Liveness check — returns 200 with {"status": "ok"} when the server is up.
    The frontend polls this on load to confirm the backend is reachable.
    """
    return {
        "status": "ok",
        "service": "search-metric-analyzer-api",
        "version": "1.0.0",
    }
