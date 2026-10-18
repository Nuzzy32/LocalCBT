import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException

from app import admin, auth, exams, media, question_import, questions
from app.config import settings
from app.db import database_ok
from app.errors import ApiError

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
            **getattr(record, "extra_fields", {}),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=settings.log_level, handlers=[handler], force=True)
log = logging.getLogger("localcbt.api")

app = FastAPI(
    title="LocalCBT API",
    version="0.1.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    swagger_ui_oauth2_redirect_url=None,
    redoc_url=None,
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(questions.router)
app.include_router(question_import.router)
app.include_router(media.router)
app.include_router(exams.router)


def error_response(
    status: int,
    code: str,
    message: str,
    headers: Mapping[str, str] | None = None,
    details: Any = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(
        status_code=status,
        content={"error": error, "request_id": request_id_var.get()},
        headers=headers,
    )


@app.exception_handler(ApiError)
def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.message, exc.headers)


@app.exception_handler(RequestValidationError)
def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Tanpa "input": nilai yang dikirim (mis. password) tidak dipantulkan balik.
    errors = exc.errors()
    details = [{"loc": e["loc"], "msg": e["msg"]} for e in errors]
    # Pesan aturan bisnis (ValueError di validator) ditampilkan apa adanya ke pengguna.
    message = next(
        (e["msg"].removeprefix("Value error, ") for e in errors if e["type"] == "value_error"),
        "Data yang dikirim tidak valid.",
    )
    return error_response(422, "VALIDATION_ERROR", message, None, details)


@app.exception_handler(IntegrityError)
def handle_integrity(_: Request, exc: IntegrityError) -> JSONResponse:
    return error_response(409, "CONFLICT", "Data sudah ada atau bentrok dengan data lain.")


@app.exception_handler(HTTPException)
def handle_http(_: Request, exc: HTTPException) -> JSONResponse:
    return error_response(exc.status_code, "HTTP_ERROR", str(exc.detail), exc.headers)


def _origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin and (referer := request.headers.get("referer")):
        parts = urlsplit(referer)
        origin = f"{parts.scheme}://{parts.netloc}"
    return origin in settings.allowed_origins


@app.middleware("http")
async def request_id_and_access_log(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    incoming = request.headers.get("x-request-id", "")
    rid = incoming if _SAFE_REQUEST_ID.match(incoming) else str(uuid.uuid4())
    token = request_id_var.set(rid)
    start = time.perf_counter()
    try:
        response: Response
        if request.method not in auth.SAFE_METHODS and not _origin_allowed(request):
            # Lapis kedua CSRF (juga melindungi /auth/login yang belum punya token CSRF).
            response = error_response(403, "ORIGIN_REJECTED", "Asal permintaan tidak diizinkan.")
        else:
            response = await call_next(request)
    except Exception:
        log.exception("unhandled error")
        response = JSONResponse(
            status_code=500,
            content={
                "error": {"code": "INTERNAL", "message": "Terjadi kesalahan server."},
                "request_id": rid,
            },
        )
    # Path saja, tanpa query string: hindari token/PII masuk log.
    log.info(
        "request",
        extra={
            "extra_fields": {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            }
        },
    )
    response.headers["X-Request-ID"] = rid
    if request.url.path.startswith("/api/"):
        # Data ujian/kredensial tidak boleh tersimpan di cache browser/proxy (USER_FLOW §8).
        response.headers["Cache-Control"] = "no-store"
    request_id_var.reset(token)
    return response


@app.get("/api/v1/healthz")
def healthz() -> JSONResponse:
    # Liveness internal, tanpa detail sensitif. Health lengkap ADMIN-only = /ops/health (M8).
    db = database_ok()
    return JSONResponse(
        status_code=200 if db else 503,
        content={"server_status": "OK", "database_status": "OK" if db else "DOWN"},
    )
