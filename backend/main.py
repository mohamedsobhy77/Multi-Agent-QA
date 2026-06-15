"""
backend/main.py
───────────────
FastAPI application entry point for QA Copilot.

Startup order
  1. Settings loaded via get_settings() (cached, read once).
  2. Logging configured for the target environment.
  3. FastAPI app created with lifespan context manager.
  4. Middleware registered (CORS).
  5. Routers mounted under /api/v1.
  6. Utility routes registered (/, /health).

Run locally
  uvicorn backend.main:app --reload --port 8000

Run in Docker
  uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.v1.endpoints.upload import router as upload_router
from backend.api.v1.endpoints.artifacts import router as artifacts_router
from backend.config import get_settings
from backend.db.database import engine
# ── Settings ──────────────────────────────────────────────────────────────────

settings = get_settings()

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

# Silence chatty third-party loggers in production.
if settings.is_production:
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage resources that must be set up before the first request and torn
    down after the last.

    Startup:  log configuration summary.
    Shutdown: dispose the SQLAlchemy connection pool so all in-flight DB
              connections are cleanly closed before the process exits.
    """
    logger.info(
        "startup  app=%s  version=%s  environment=%s  debug=%s",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.ENVIRONMENT,
        settings.DEBUG,
    )
    logger.info("startup  cors_origins=%s", settings.cors_origins_list)

    yield  # ← application runs here

    logger.info("shutdown  disposing database connection pool")
    await engine.dispose()
    logger.info("shutdown  complete")


# ── Application factory ───────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """
    Build and configure the FastAPI application.

    Splitting creation into a factory function makes the app importable by
    test suites and ASGI runners without side-effects at module import time.
    """
    _app = FastAPI(
        title="QA Copilot API",
        version="0.1.0",
        description=(
            "Upload PDF, DOCX, or TXT requirement documents and generate "
            "comprehensive QA artifacts — user stories, acceptance criteria, "
            "test cases, and more — using an AI pipeline."
        ),
        # Disable interactive docs in production to reduce attack surface.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )

    # ── Middleware ─────────────────────────────────────────────────────────────
    _register_middleware(_app)

    # ── Routers ───────────────────────────────────────────────────────────────
    _register_routers(_app)

    # ── Utility routes ────────────────────────────────────────────────────────
    _register_utility_routes(_app)

    return _app


# ── Middleware registration ───────────────────────────────────────────────────

def _register_middleware(app: FastAPI) -> None:
    """Attach all middleware in the correct order (outermost → innermost)."""

    # ── CORS ──────────────────────────────────────────────────────────────────
    # allow_credentials=True is required when the Next.js frontend sends
    # cookies or Authorization headers from a different origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # ── Request ID + latency ──────────────────────────────────────────────────
    # Attaches a unique X-Request-ID to every response and logs method,
    # path, status code, and duration.  Useful for correlating frontend
    # errors with backend log lines.
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-ID"] = request_id

        logger.info(
            "request  id=%s  method=%s  path=%s  status=%d  duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


# ── Router registration ───────────────────────────────────────────────────────

def _register_routers(app: FastAPI) -> None:
    app.include_router(
        upload_router,
        prefix="/api/v1",
        tags=["Documents & Sessions"],
    )

    app.include_router(
        artifacts_router,
        prefix="/api/v1",
        tags=["Artifacts"],
    )


# ── Utility routes ────────────────────────────────────────────────────────────

def _register_utility_routes(app: FastAPI) -> None:
    """Register lightweight operational endpoints."""

    @app.get(
        "/",
        tags=["Meta"],
        summary="API root",
        include_in_schema=False,
    )
    async def root() -> dict[str, Any]:
        """Return basic API identity information."""
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "docs": "/docs" if not settings.is_production else None,
            "health": "/health",
        }

    @app.get(
        "/health",
        tags=["Meta"],
        summary="Health check",
        status_code=status.HTTP_200_OK,
        responses={
            200: {"description": "Service is healthy."},
            503: {"description": "Service is unavailable."},
        },
    )
    async def health_check() -> dict[str, Any]:
        """
        Liveness probe used by Docker, Kubernetes, and load balancers.

        Returns 200 when the application is running and ready to accept
        requests.  A deeper readiness check (DB connectivity) can be
        layered in here in Sprint 2 when the pipeline is wired.
        """
        return {
            "status": "ok",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        }


# ── Global exception handler ──────────────────────────────────────────────────

def _register_exception_handlers(app: FastAPI) -> None:
    """
    Catch unhandled exceptions that escape all routers and middleware,
    log them server-side, and return a generic 500 without leaking
    internal details to the client.
    """
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(
            "unhandled_exception  method=%s  path=%s  error=%r",
            request.method,
            request.url.path,
            exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred. Please try again.",
                }
            },
        )


# ── App instance ──────────────────────────────────────────────────────────────
# Module-level `app` is what uvicorn and test clients import.

app = create_app()
_register_exception_handlers(app)
