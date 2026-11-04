"""The FastAPI application."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from edgewise import __version__
from edgewise.api.deps import Clock
from edgewise.api.routes import auth, status
from edgewise.config import Settings, get_settings
from edgewise.db.session import make_engine, make_session_factory

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def create_app(
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    clock: Clock = _utcnow,
) -> FastAPI:
    settings = settings or get_settings()
    if session_factory is None:
        session_factory = make_session_factory(make_engine(settings.database_url))

    app = FastAPI(
        title="Edgewise",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.is_lab else None,
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.clock = clock

    @app.middleware("http")
    async def same_origin_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Refuse state-changing requests sent from another website (CSRF defence in depth;
        the session cookie is also SameSite=Strict).

        The browser's Origin must match the host it was talking to: the Host header, or
        X-Forwarded-Host when a proxy rewrote Host. A cross-site page cannot set either.
        """
        if request.method in _UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None:
                hosts = {request.headers.get("host"), request.headers.get("x-forwarded-host")}
                if urlsplit(origin).netloc not in hosts - {None}:
                    return JSONResponse({"detail": "Cross-site request refused."}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.include_router(status.router)
    app.include_router(auth.router)
    return app


def app() -> FastAPI:
    """Factory for uvicorn: `uvicorn --factory edgewise.api.main:app`."""
    return create_app()
