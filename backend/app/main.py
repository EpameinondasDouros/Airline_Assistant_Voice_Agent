import logging
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.routes.admin import router as admin_router
from app.api.routes.chat import router as chat_router
from app.api.routes.bookings import router as bookings_router
from app.api.routes.flights import router as flights_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.testing import router as testing_router
from app.api.errors import integrity_error_response
from app.db.flight_schema import ensure_flight_seat_columns
from app.db.seat_inventory import sync_seat_inventory
from app.db.session import engine
from app.config import get_settings


settings = get_settings()
REPO_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("app.validation")


@lru_cache
def _resolve_deploy_git_commit_hash() -> str | None:
    for key in (
        "GIT_COMMIT_SHA",
        "RAILWAY_GIT_COMMIT_SHA",
        "RAILWAY_GIT_COMMIT_HASH",
        "SOURCE_VERSION",
    ):
        value = os.getenv(key)
        if value:
            return value
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            .strip()
        )
    except Exception:
        return None

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin_router, prefix=settings.api_prefix)
app.include_router(chat_router, prefix=settings.api_prefix)
app.include_router(flights_router, prefix=settings.api_prefix)
app.include_router(bookings_router, prefix=settings.api_prefix)
app.include_router(knowledge_router, prefix=settings.api_prefix)
app.include_router(testing_router, prefix=settings.api_prefix)


@app.exception_handler(IntegrityError)
def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
    return integrity_error_response(exc)


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    try:
        raw_body = await request.body()
        request_body = raw_body.decode("utf-8", errors="replace")
    except Exception:
        request_body = "<unavailable>"
    if len(request_body) > 4000:
        request_body = request_body[:4000] + "...<truncated>"

    logger.warning(
        "Request validation error | method=%s path=%s errors=%s body=%s",
        request.method,
        request.url.path,
        exc.errors(),
        request_body,
    )
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "error_code": "request_validation_error",
            "message": "The request body failed validation.",
            "details": exc.errors(),
        },
    )


@app.on_event("startup")
def repair_flight_schema() -> None:
    ensure_flight_seat_columns(engine)
    sync_seat_inventory(engine)


@app.get("/health")
def healthcheck() -> dict[str, str | None]:
    return {"status": "ok", "git_commit_hash": _resolve_deploy_git_commit_hash()}


@app.get(f"{settings.api_prefix}/meta")
def metadata() -> dict[str, str | None]:
    return {
        "status": "ok",
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "git_commit_hash": _resolve_deploy_git_commit_hash(),
    }
