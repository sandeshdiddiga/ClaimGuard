"""The ClaimGuard web app: JSON API under /api and the built React front end at /."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.refdb import ReferenceDbError, reference_is_loaded, reference_smoke
from app.routes import RateLimiter, router
from app.settings import Settings

CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # The reference database ships with the app. Without it every check would be wrong, so do not start.
        if not reference_is_loaded(settings.reference_db):
            raise ReferenceDbError("reference database not found or empty: build it with `python -m ingest`")
        yield

    app = FastAPI(title="ClaimGuard", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.limiter = RateLimiter(settings.max_cases_per_hour)
    app.state.lookup_limiter = RateLimiter(settings.max_lookups_per_hour)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = CSP
        return response

    @app.get("/health")
    def health() -> JSONResponse:
        """Healthy only when the reference database opens and a smoke query works: without it every check would be wrong."""
        if not reference_smoke(settings.reference_db):
            return JSONResponse(
                {"status": "unavailable", "reason": "reference database not loaded"}, status_code=503
            )
        return JSONResponse({"status": "ok"})

    app.include_router(router)
    if settings.static_dir is not None:
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="web")
    return app


